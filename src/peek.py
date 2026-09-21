r"""peek.py — quick look at each raw file: row count + column names."""
# Throwaway inspection script, not part of the pipeline (ingest.py -> clean.py).
# Run this after a fresh ingest to see what columns each downloaded file
# actually has — that's how the RENAME variants in clean.py were discovered,
# since data.gov.bh doesn't keep column names consistent across years/flows.
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

# Every raw file, regardless of flow — filenames are "<flow>__<dataset_id>.parquet"
# (see ingest.py) but this just globs everything to eyeball them all at once.
for f in sorted(RAW_DIR.glob("*.parquet")):
    df = pd.read_parquet(f)
    print(f"\n{f.name}")
    print(f"  rows: {len(df):,}   cols: {len(df.columns)}")
    print(f"  columns: {list(df.columns)}")