"""
ingest.py — download Bahrain foreign-trade datasets (Imports, Re-Exports,
National-Origin Exports) from data.gov.bh into data/raw/.

Run:  python src\ingest.py            # skips files already downloaded
      python src\ingest.py --refresh  # re-download everything
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import requests

RAW_DIR = Path("data/raw")

# The datasets we need, grouped by trade flow.
DATASETS = {
    "import": [
        "05-import-2021",
        "04-import-2022",
        "01-import-non-oil-classified-by-commodity-and-country-for-2023",
        "import-2024",
        "import-1-2025",
        "import-2026",
    ],
    "reexport": [
        "kingdom-of-bahrain-re-export-non-oil-classified-by-commodity-and-country",  # 2020-2022
        "re-export-2023",
        "re-export-1-2024",
        "re-export-1-2025",
        "re-export-2026",
    ],
    "national_export": [   # cross-check only (not used to build corridors)
        "02-national-export-2019-2022",
        "exports-national-origin-2023",
        "national-export-1-2024",
        "national-export-1-2025",
        "exports-national-origin-2026",
    ],
}

BASE = "https://www.data.gov.bh/api/explore/v2.1/catalog/datasets"
HEADERS = {"User-Agent": "bahrain-corridors/0.1 (portfolio project)"}


def download_one(dataset_id: str, group: str, refresh: bool):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"{group}__{dataset_id}.parquet"
    if out.exists() and not refresh:
        print(f"  cached   {out.name}")
        return True

    url = f"{BASE}/{dataset_id}/exports/parquet"
    for attempt in range(1, 4):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
                r.raise_for_status()
                tmp = out.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                tmp.replace(out)                       # atomic: only rename on success
            print(f"  saved    {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
            return True
        except Exception as e:
            print(f"  attempt {attempt} failed for {dataset_id}: {e}")
            time.sleep(2 * attempt)
    print(f"  GAVE UP  {dataset_id}")
    return False


def main():
    refresh = "--refresh" in sys.argv
    print(f"Saving into {RAW_DIR.resolve()}  (refresh={refresh})\n")
    ok = 0
    total = sum(len(v) for v in DATASETS.values())
    for group, ids in DATASETS.items():
        print(f"[{group}]")
        for ds in ids:
            ok += download_one(ds, group, refresh)
        print()
    print(f"Done. {ok}/{total} files ready.")


if __name__ == "__main__":
    main()