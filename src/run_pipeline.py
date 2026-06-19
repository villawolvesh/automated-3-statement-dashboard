"""
The single "run everything" entry point.

    python src/run_pipeline.py              # full refresh: re-pull EDGAR -> rebuild
    python src/run_pipeline.py --no-fetch   # rebuild from the cached raw JSON (offline)

Order: fetch -> load SQLite -> build SQL views -> integrity check -> dashboard.
If the integrity check fails, the run stops with a non-zero exit code and does
NOT regenerate the dashboard, so bad numbers never get published. This is the
exact sequence GitHub Actions will run on a schedule.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from src import fetch_edgar, load_db, build_dashboard, integrity_check  # noqa: E402
from src.build_views import build_views  # noqa: E402


def main(fetch: bool = True) -> int:
    print("=" * 60)
    print("  AUTOMATED 3-STATEMENT DASHBOARD — PIPELINE")
    print("=" * 60)

    if fetch:
        print("\n[1/5] Fetch SEC EDGAR company facts")
        fetch_edgar.main()
    else:
        print("\n[1/5] Skipping fetch (--no-fetch); using cached raw JSON")

    print("\n[2/5] Load facts into SQLite")
    load_db.main()

    print("\n[3/5] Build SQL views")
    conn = sqlite3.connect(config.DB_PATH)
    try:
        build_views(conn)
    finally:
        conn.close()

    print("\n[4/5] Integrity check (3-statement reconciliation)")
    if not integrity_check.main():
        print("\n*** ABORT: integrity check failed — dashboard NOT regenerated. ***")
        return 1

    print("\n[5/5] Build dashboard (+ revision log)")
    build_dashboard.main()

    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE — docs/index.html regenerated")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    fetch = "--no-fetch" not in sys.argv
    sys.exit(main(fetch=fetch))
