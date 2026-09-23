r"""
corridors.py — estimate origin -> Bahrain -> destination corridors via
proportional allocation with a trailing-window (dwell-time) lag, plus
summary metrics and saved outputs.

Bahrain buys goods from a bunch of countries, then later resells some
of that stuff to other countries. The trade data never tells us which
import turned into which re-export — we just see totals on each side.
So here we make an assumption: whatever Bahrain re-exports in a given
month probably came from whoever it was importing from recently, split
in proportion to how much came from each of them. That gives us a
"corridor": origin country -> Bahrain -> destination country, with an
estimated dollar value attached.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

# project root is one level up from src/, and that's where the cleaned
# data files live
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"


def load_flow(flow: str, hs2: str | None = None) -> pd.DataFrame:
    # flow is just the filename, e.g. "import" -> import.parquet
    df = pd.read_parquet(PROC / f"{flow}.parquet")
    df = df[df["value_usd"] > 0]  # zero/negative rows aren't real trade, drop them
    if hs2 is not None:
        df = df[df["hs2"] == hs2]  # optionally narrow to one product category
    return df


def build_corridors(imp_df, rex_df, value_col="value_usd", lag_months=2):
    # lag_months exists because goods don't get re-exported the instant
    # they arrive — they usually sit around for a bit first. So this
    # month's re-exports are more likely tied to imports from the last
    # couple months, not just the current one.

    # turn the raw rows into a month x country table so we can compare
    # countries side by side for any given month
    imp = imp_df.groupby(["period", "country_iso2"])[value_col].sum().unstack(fill_value=0.0)
    rex = rex_df.groupby(["period", "country_iso2"])[value_col].sum().unstack(fill_value=0.0)

    # make sure we've got one row per month across the whole date
    # range, even months with zero imports, so nothing gets skipped
    start = min(imp.index.min(), rex.index.min())
    end   = max(imp.index.max(), rex.index.max())
    full  = pd.date_range(start, end, freq="MS")
    imp   = imp.reindex(full, fill_value=0.0)

    # rolling sum over the current month + the lag window = our guess
    # at what's sitting in Bahrain available to be shipped back out
    imp_trail = imp.rolling(window=lag_months + 1, min_periods=1).sum()

    frames, attributed, unattributed = [], 0.0, 0.0
    for period in rex.index:
        rex_row = rex.loc[period]; rex_row = rex_row[rex_row > 0]  # who actually got shipped to this month
        if rex_row.empty:
            continue
        rex_total = rex_row.sum()

        trail = imp_trail.loc[period]; trail = trail[trail > 0]  # who we'd been importing from lately
        if trail.sum() <= 0:
            # nothing to attribute this to (e.g. right at the start of
            # the dataset before there's import history) — just log it
            # as unexplained instead of making something up
            unattributed += rex_total
            continue

        # each origin's cut of recent imports — if a country supplied
        # 30% of the trailing imports, we assume it's behind 30% of
        # whatever gets re-exported this month too
        shares = trail / trail.sum()

        # spread every destination's total across all the origins by
        # those shares — this outer product is the actual corridor
        # estimate, an origin x destination grid of dollar amounts
        mat = np.outer(shares.values, rex_row.values)
        block = pd.DataFrame(mat, index=shares.index, columns=rex_row.index)
        block.index.name, block.columns.name = "origin", "dest"
        block = block.stack().rename("est_value").reset_index()  # flatten grid to one row per pair
        block["period"] = period
        frames.append(block)
        attributed += rex_total

    corridors = pd.concat(frames, ignore_index=True)[["period", "origin", "dest", "est_value"]]

    # a few sanity-check numbers: overall import/re-export volume, and
    # how much of the re-export total we could actually trace back to
    # an origin vs. had to write off as unexplained
    total_imp = float(imp.values.sum()); total_rex = attributed + unattributed
    diagnostics = {
        "lag_months": lag_months,
        "total_import_usd": total_imp,
        "total_reexport_usd": total_rex,
        "reexport_to_import_ratio": total_rex / total_imp,
        "attributed_reexport_usd": attributed,
        "unattributed_reexport_usd": unattributed,
        "attributed_pct": attributed / total_rex,
    }
    return corridors, diagnostics


# metrics
#
# everything below turns the raw corridor estimates above into the
# summary numbers/tables an app or report would actually want to show

def iso_name_map() -> pd.Series:
    """iso2 -> readable country name, built from the processed panels."""
    # the corridor tables only have 2-letter country codes (e.g. "US"),
    # which isn't great to show people, so grab the full names from the
    # same source files and build a code -> name lookup
    frames = [pd.read_parquet(PROC / f"{f}.parquet")[["country_iso2", "country_name"]]
              for f in ("import", "reexport")]
    m = pd.concat(frames).dropna().drop_duplicates("country_iso2")
    return m.set_index("country_iso2")["country_name"]


def corridor_totals(corridors: pd.DataFrame) -> pd.DataFrame:
    """Sum each corridor over time, add its share of the total, attach names."""
    # collapse the month-by-month estimates down to one row per
    # origin/destination pair, ranked biggest first
    tot = (corridors.groupby(["origin", "dest"])["est_value"].sum()
                    .sort_values(ascending=False).reset_index())
    tot["share"] = tot["est_value"] / tot["est_value"].sum()  # what % of all corridor volume this pair represents
    names = iso_name_map()
    tot["origin_name"] = tot["origin"].map(names)
    tot["dest_name"] = tot["dest"].map(names)
    return tot


def hhi(totals: pd.DataFrame) -> float:
    """Herfindahl index of corridor concentration (1/n = even, 1 = one dominates)."""
    # standard concentration measure: square each corridor's share and
    # add them up. if volume is spread evenly across n corridors this
    # comes out to 1/n; if a single corridor has everything, it's 1.
    # higher = trade is concentrated in just a few routes.
    return float((totals["share"] ** 2).sum())


def yearly_totals(corridors: pd.DataFrame) -> pd.DataFrame:
    """Total estimated flow per year, with year-on-year % change."""
    c = corridors.copy()
    c["year"] = c["period"].dt.year
    yt = c.groupby("year")["est_value"].sum().to_frame("est_value")
    yt["yoy_pct"] = yt["est_value"].pct_change() * 100  # % change vs. the previous year, blank for the first year
    return yt


# only runs when you execute this file directly, not on import — quick
# example that builds corridors for HS2 "87" (motor vehicles), prints a
# summary, and saves the results for the app to reuse
if __name__ == "__main__":
    imp87 = load_flow("import", hs2="87")
    rex87 = load_flow("reexport", hs2="87")
    corridors, diag = build_corridors(imp87, rex87, lag_months=2)

    totals = corridor_totals(corridors)
    conc = hhi(totals)
    yt = yearly_totals(corridors)

    # save outputs for the app (data/processed is git-ignored; regenerable)
    corridors.to_parquet(PROC / "corridors_hs87.parquet", index=False)
    totals.to_parquet(PROC / "corridor_totals_hs87.parquet", index=False)

    print("Diagnostics:")
    for k, v in diag.items():
        print(f"  {k}: {v:,.4f}" if isinstance(v, float) else f"  {k}: {v}")

    print(f"\nCorridor concentration (HHI): {conc:.4f}   "
          f"({len(totals):,} distinct corridors)")

    print("\nTop 10 corridors:")
    print(totals.head(10)[["origin_name", "dest_name", "est_value", "share"]].to_string(index=False))

    print("\nYearly totals (2026 is partial — through July):")
    print(yt.to_string())

    print(f"\nSaved: corridors_hs87.parquet ({len(corridors):,} rows), "
          f"corridor_totals_hs87.parquet ({len(totals):,} rows)")
