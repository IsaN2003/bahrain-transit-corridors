r"""peek.py — quick look at each raw file: row count + column names."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

for f in sorted(RAW_DIR.glob("*.parquet")):
    df = pd.read_parquet(f)
    print(f"\n{f.name}")
    print(f"  rows: {len(df):,}   cols: {len(df.columns)}")
    print(f"  columns: {list(df.columns)}")