"""
Data-lookup tools the AI chat assistant can call.

The chat model can't read our parquet files itself, so instead it asks for
data through query_corridors(): it picks the filters (year / origin / dest)
and how to summarise the result, we run the pandas query here, and hand back
a small JSON-friendly dict it can read and talk about.
"""

from pathlib import Path
import pandas as pd
import json


# project root = two levels up from this file (src/ai_tools.py -> repo root)
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"  # where the cleaned / derived parquet files live

# which columns to group by for each "group_by" option
# e.g. "corridor" means one row per origin -> destination pair,
# "origin" rolls everything up to the sending country, and so on
GROUP_COLS = {
    "corridor": ["origin_name", "dest_name"],
    "origin": ["origin_name"],
    "destination": ["dest_name"],
    "year": ["year"],
}

def name_map():
    """iso2 -> country name, from the shipped corridor_totals file (no heavy panels)."""
    ct = pd.read_parquet(PROC / "corridor_totals_hs87.parquet")
    o = ct[["origin", "origin_name"]].rename(columns={"origin": "code", "origin_name": "name"})
    d = ct[["dest", "dest_name"]].rename(columns={"dest": "code", "dest_name": "name"})
    m = pd.concat([o, d]).dropna().drop_duplicates("code")
    return dict(zip(m["code"], m["name"]))

def load_named_corridors():
    """Full monthly corridor data with country names attached (for the AI tool)."""
    # one row per (month, origin, dest) with the estimated trade value in USD
    df = pd.read_parquet(PROC / "corridors_hs87.parquet")
    df["year"] = df["period"].dt.year  # pull the year out so we can filter/group by it

    # the corridor table only has 2-letter ISO codes (e.g. "SA"); swap in
    # readable names so the model can match things like "Saudi" in a question
    names = name_map()
    df["origin_name"] = df["origin"].map(names)
    df["dest_name"] = df["dest"].map(names)
    return df


def query_corridors(df, year=None, origin=None, dest=None,
                    group_by="corridor", top_n=10):
    """
    Parameterized lookup over the corridor estimates.
    - year:    filter to one year (int), or None for all years
    - origin:  filter to an origin country (partial name ok), or None
    - dest:    filter to a destination country (partial name ok), or None
    - group_by: 'corridor' | 'origin' | 'destination' | 'year'
    - top_n:   how many rows to return (ignored for group_by='year')
    Returns a JSON-serializable dict.
    """
    # --- 1. apply whichever filters were given (None / empty = no filter) ---
    q = df
    if year is not None:
        q = q[q["year"] == int(year)]  # int() in case the model sends "2022" as a string
    if origin:
        # case-insensitive substring match, so "saudi" finds "Saudi Arabia";
        # na=False treats rows with a missing name as "no match" instead of erroring
        q = q[q["origin_name"].str.contains(origin, case=False, na=False)]
    if dest:
        q = q[q["dest_name"].str.contains(dest, case=False, na=False)]

    # nothing left after filtering -> tell the model explicitly rather than
    # returning an empty table it might misread
    if q.empty:
        return {"rows": [], "note": "No data matched those filters."}

    # grand total of everything that matched the filters, in USD millions
    total_m = round(q["est_value"].sum() / 1e6, 2)

    # --- 2. aggregate ---
    if group_by == "year":
        # time series: keep every year, in chronological order (no top_n cut)
        agg = (q.groupby("year")["est_value"].sum()
                 .reset_index().sort_values("year"))
    else:
        # ranking: sum per group, biggest first, keep the top_n
        # (an unknown group_by value quietly falls back to "corridor")
        cols = GROUP_COLS.get(group_by, GROUP_COLS["corridor"])
        agg = (q.groupby(cols)["est_value"].sum()
                 .sort_values(ascending=False).head(top_n).reset_index())

    # --- 3. format for the model ---
    # report values in USD millions (shorter numbers, easier to read aloud)
    # and drop the raw USD column so there's only one value per row
    agg["value_usd_m"] = (agg["est_value"] / 1e6).round(2)
    rows = agg.drop(columns="est_value").to_dict(orient="records")

    # echo the filters back so the model can see exactly what was queried
    result = {"filters": {"year": year, "origin": origin, "dest": dest,
                          "group_by": group_by},
              "total_usd_m": round(float(total_m), 2), "rows": rows}
    # normalize any numpy types (np.float64, np.int64) to plain Python for JSON
    # (json.dumps can't handle them directly, so .item() converts each one;
    # the round-trip through a string gives back a clean plain-Python dict)
    return json.loads(json.dumps(result, default=lambda o: o.item()))
