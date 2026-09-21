r"""
clean.py — harmonise the raw Bahrain trade files into tidy panels.
Stage: d2a (schema) + d2b (dates) + d2c (country + HS keys).
"""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROC_DIR = ROOT / "data" / "processed"

# Column names differ across source files because data.gov.bh renamed/re-issued
# datasets over the years (english import/export-prefixed names) and some
# datasets are exported with Arabic column headers transliterated into Latin
# letters (the "qym_..."/"wzn_..."/"kmy_..." keys below, e.g. qym = qeema/value,
# wzn = wazn/weight, kmy = kammiya/quantity, lwrdt = al-waredat/imports,
# lsdrt = al-sadirat/exports). This dict maps every variant seen so far onto
# one canonical column name so load_one() can treat all raw files the same way.
RENAME = {
    "commodity_no": "hs8", "commodity": "commodity",
    "country_name": "country_name", "country": "country_name",
    "un_code": "un_code", "year": "year", "month": "month",
    "import_value_bd": "value_bd",   "export_value_bd": "value_bd",
    "import_value_usa": "value_usd",  "export_value_usa": "value_usd",
    "import_weight_kg": "weight_kg",  "export_weight_kg": "weight_kg",
    "import_quantity": "quantity",    "export_quantity": "quantity",
    "um": "um",
    "qym_lwrdt_dynr_bhryny": "value_bd",  "qym_lsdrt_dynr_bhryny": "value_bd",
    "qym_lwrdt_dwlr_mryky": "value_usd",  "qym_lsdrt_dwlr_mryky": "value_usd",
    "wzn_lwrdt_kjm": "weight_kg",         "wzn_lsdrt_kjm": "weight_kg",
    "kmy_lwrdt": "quantity",              "kmy_lsdrt": "quantity",
    "whd_lqys": "um",
}

# Canonical column order/selection for every cleaned panel — load_one() keeps
# only these columns (whichever of them exist for a given flow) so
# import / reexport / national_export all end up with the same shape.
FINAL = ["flow", "period", "year", "month_num",
         "hs8", "hs6", "hs2", "commodity",
         "country_iso2", "country_name",
         "value_bd", "value_usd", "weight_kg", "quantity", "um"]

# Some raw files spell the month out (English name) instead of giving a number.
MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
          "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}


def to_year(v):
    # Pulls a 4-digit 20xx year out of whatever the raw value looks like
    # (plain int, "2023.0", "FY2023", etc.) instead of trying to parse it strictly.
    m = re.search(r"(20\d{2})", str(v))
    return int(m.group(1)) if m else pd.NA


def to_month(v):
    # Handles both "3" / "03" style values and spelled-out month names.
    # Try a plain 1-12 number first...
    s = str(v).strip().lower()
    m = re.search(r"\b(1[0-2]|0?[1-9])\b", s)
    if m:
        return int(m.group(1))
    # ...otherwise fall back to matching an English month name (see MONTHS).
    for name, num in MONTHS.items():
        if name in s:
            return num
    return pd.NA


def clean_hs(v):
    """Digits only, zero-padded to 8 (keeps leading zeros).

    Raw HS codes sometimes come through as floats (e.g. 1234.0) or with
    stray punctuation/spaces, which would break leading-zero HS codes and
    the hs6/hs2 prefix slicing done in load_one() — this normalises them
    to a plain 8-digit string first.
    """
    s = re.sub(r"\D", "", str(v))
    return s.zfill(8) if s else pd.NA


def load_one(path: Path) -> pd.DataFrame:
    # d2a: schema — normalise one raw parquet file (whatever year/source it's
    # from) onto the common column names/order defined above.
    df = pd.read_parquet(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns=RENAME)
    # ingest.py names files "<flow>__<dataset_id>.parquet", so the flow
    # (import/reexport/national_export) is recovered from the filename prefix.
    df["flow"] = path.name.split("__")[0]

    # A few older datasets don't have a "year" column at all — the year is
    # only encoded in the dataset id / filename (e.g. "...-2023"), so fall
    # back to scraping it from the file stem.
    if "year" not in df.columns:
        m = re.search(r"(20\d{2})", path.stem)
        df["year"] = int(m.group(1)) if m else pd.NA

    # d2b: dates
    df["year"] = df["year"].map(to_year).astype("Int64")
    df["month_num"] = df["month"].map(to_month).astype("Int64")
    # Build a proper monthly Timestamp (always day=1) so periods sort/compare
    # cleanly and rows with an unparseable year/month become NaT (dropped later).
    df["period"] = pd.to_datetime(
        {"year": df["year"], "month": df["month_num"], "day": 1}, errors="coerce")

    # d2c: HS code + country keys
    df["hs8"] = df["hs8"].map(clean_hs).astype("string")
    df["hs6"] = df["hs8"].str[:6]  # coarser HS levels, used to match corridors
    df["hs2"] = df["hs8"].str[:2]  # across import vs re-export/export tables
    df["country_iso2"] = df["un_code"].astype("string").str.strip().str.upper()
    df["country_name"] = df["country_name"].astype("string").str.strip().str.title()

    # Not every flow/year has every FINAL column (e.g. some files lack "um"),
    # so only keep the ones that actually exist rather than erroring out.
    return df[[c for c in FINAL if c in df.columns]]


def build_panel(flow: str) -> pd.DataFrame:
    """Run load_one on every file of one flow and stack them into one table."""
    # Filenames are "<flow>__<dataset_id>.parquet" (see ingest.py), so this
    # glob picks up every year/vintage of raw file for this flow.
    files = sorted(RAW_DIR.glob(f"{flow}__*.parquet"))
    frames = [load_one(f) for f in files]
    return pd.concat(frames, ignore_index=True)


def main():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    panels = {}
    for flow in ["import", "reexport", "national_export"]:
        df = build_panel(flow)
        before = len(df)

        # d2d: light sanity cleaning
        df = df.dropna(subset=["period", "hs8", "country_iso2"])   # unusable without keys
        df = df.drop_duplicates()                                  # exact dupes

        out = PROC_DIR / f"{flow}.parquet"
        df.to_parquet(out, index=False)
        panels[flow] = df

        # Printed diagnostics on every run so bad refreshes/new source files
        # are obvious at a glance (row-count drop, date range, negative/null values).
        print(f"\n[{flow}]  {before:,} -> {len(df):,} rows  saved to {out.name}")
        print(f"   period : {df['period'].min().date()} -> {df['period'].max().date()}")
        print(f"   unique : {df['hs8'].nunique():,} HS8   {df['country_iso2'].nunique()} countries")
        print(f"   checks : neg USD={int((df['value_usd'] < 0).sum())}   "
              f"null value_usd={int(df['value_usd'].isna().sum())}")

    # does the data support corridors? imports and re-exports must share commodities.
    # A "corridor" is Bahrain importing a commodity and later re-exporting the
    # same commodity elsewhere — that's only analysable for HS6 codes that show
    # up in BOTH the import and re-export panels, so this is a quick feasibility
    # check on the cleaned data (not yet the actual corridor matching logic).
    shared = set(panels["import"]["hs6"]) & set(panels["reexport"]["hs6"])
    print(f"\nShared HS6 between imports & re-exports: {len(shared):,}  "
          f"(these are your candidate corridor commodities)")


if __name__ == "__main__":
    main()