r"""
ingest.py — download Bahrain foreign-trade datasets into data/raw/.
Run:  python src\ingest.py            # skips files already downloaded
      python src\ingest.py --refresh  # re-download everything
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

# Each dataset_id is the slug data.gov.bh uses in its catalog URL for one
# year/vintage of a given trade flow (import / re-export / national export).
# There's one entry per file actually published on the portal — the naming is
# inconsistent (numeric prefixes, "1-2025" vs "2026", long descriptive slugs
# for older years) because the government renamed/restructured the datasets
# over time; these are just copied straight from data.gov.bh's own URLs.
# When a new year gets published on the portal, add its slug to the right list.
DATASETS = {
    "import": [
        "05-import-2021", "04-import-2022",
        "01-import-non-oil-classified-by-commodity-and-country-for-2023",
        "import-2024", "import-1-2025", "import-2026",
    ],
    "reexport": [
        "kingdom-of-bahrain-re-export-non-oil-classified-by-commodity-and-country",
        "re-export-2023", "re-export-1-2024", "re-export-1-2025", "re-export-2026",
    ],
    "national_export": [
        "02-national-export-2019-2022", "exports-national-origin-2023",
        "national-export-1-2024", "national-export-1-2025", "exports-national-origin-2026",
    ],
}

BASE = "https://www.data.gov.bh/api/explore/v2.1/catalog/datasets"
HEADERS = {"User-Agent": "bahrain-corridors/0.1 (portfolio project)"}


def download_one(dataset_id: str, group: str, refresh: bool):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    # Files are named "<flow>__<dataset_id>.parquet" — clean.py relies on this
    # exact naming to recover the flow from the filename and to glob all files
    # belonging to one flow (see build_panel() in clean.py).
    out = RAW_DIR / f"{group}__{dataset_id}.parquet"
    if out.exists() and not refresh:
        print(f"  cached   {out.name}")
        return True
    # data.gov.bh's Opendatasoft "explore" API can export any dataset directly
    # as parquet via this /exports/parquet endpoint — no auth needed.
    url = f"{BASE}/{dataset_id}/exports/parquet"
    for attempt in range(1, 4):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
                r.raise_for_status()
                # Stream to a .part file and only rename to the final .parquet
                # once fully written, so a crash/interrupt mid-download never
                # leaves a corrupt file that looks "cached" on the next run.
                tmp = out.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                tmp.replace(out)
            print(f"  saved    {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
            return True
        except Exception as e:
            # Portal is occasionally flaky/rate-limited — retry a few times
            # with backoff before giving up on this one dataset.
            print(f"  attempt {attempt} failed for {dataset_id}: {e}")
            time.sleep(2 * attempt)
    print(f"  GAVE UP  {dataset_id}")
    return False


def main():
    refresh = "--refresh" in sys.argv
    print(f"Saving into {RAW_DIR}  (refresh={refresh})\n")
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