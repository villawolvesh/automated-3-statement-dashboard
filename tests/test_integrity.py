"""
Automated test wrapper around the integrity guard.

Runs the same three reconciliations as src/integrity_check.py and fails (raises
AssertionError / exits non-zero) if any of them break. Works two ways:

    python tests/test_integrity.py     -> exits 0 (pass) or 1 (fail)
    pytest tests/                      -> collected as test_statements_reconcile
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from src.build_views import build_views  # noqa: E402
from src.integrity_check import run_checks  # noqa: E402


def test_statements_reconcile():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        build_views(conn)
        assert run_checks(conn), "Integrity check failed: the three statements do not reconcile."
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        test_statements_reconcile()
        print("\ntest_integrity: PASSED")
        sys.exit(0)
    except AssertionError as exc:
        print(f"\ntest_integrity: FAILED -> {exc}")
        sys.exit(1)
