"""
Step 3 of the pipeline: land the clean facts into a local SQLite database.

Responsibility (one job only): create the SQLite file and populate the three
BASE tables that everything downstream is computed from:

    company       one row identifying the entity
    facts         every reported us-gaap data point (the source of truth)
    concept_map   XBRL tag -> standardized statement line, with fallbacks

We deliberately store ALL facts (not a filtered subset) so the SQL views — not
hidden Python — do the selection and calculation. That makes the numbers fully
auditable: anyone can open financials.db and re-run the queries.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from src.parse_facts import parse_facts  # noqa: E402
from src.concept_map import iter_rows as concept_map_rows  # noqa: E402


def create_schema(conn: sqlite3.Connection) -> None:
    """(Re)create the base tables from scratch so reruns are deterministic."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS company;
        DROP TABLE IF EXISTS facts;
        DROP TABLE IF EXISTS concept_map;

        CREATE TABLE company (
            cik          TEXT PRIMARY KEY,
            ticker       TEXT,
            entity_name  TEXT
        );

        CREATE TABLE facts (
            concept        TEXT,
            unit           TEXT,
            period_start   TEXT,   -- NULL for balance-sheet "instant" facts
            period_end     TEXT,
            value          REAL,
            fiscal_year    INTEGER,
            fiscal_period  TEXT,   -- 'FY' annual, 'Q1'..'Q4' quarterly
            form           TEXT,   -- '10-K', '10-Q', ...
            filed          TEXT,   -- filing date; used to pick latest restatement
            frame          TEXT,
            accn           TEXT,
            duration_days  REAL    -- NULL for instant facts
        );
        CREATE INDEX idx_facts_concept ON facts(concept);
        CREATE INDEX idx_facts_period  ON facts(period_end);

        CREATE TABLE concept_map (
            statement   TEXT,   -- 'income' | 'balance' | 'cashflow'
            line_label  TEXT,   -- human-readable line
            line_order  INTEGER,
            concept     TEXT,   -- XBRL tag
            priority    INTEGER,-- 1 = preferred, 2 = fallback, ...
            sign        INTEGER
        );
        """
    )


def load_company(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO company (cik, ticker, entity_name) VALUES (?, ?, ?)",
        (config.COMPANY["cik"], config.COMPANY["ticker"], config.COMPANY["entity_name"]),
    )


def load_facts(conn: sqlite3.Connection, raw: dict) -> int:
    """Flatten the raw JSON and bulk-insert every us-gaap fact."""
    df = parse_facts(raw)

    # Store dates as ISO strings (SQLite has no native date type).
    for col in ("period_start", "period_end", "filed"):
        df[col] = df[col].dt.strftime("%Y-%m-%d")

    df = df[
        [
            "concept", "unit", "period_start", "period_end", "value",
            "fiscal_year", "fiscal_period", "form", "filed", "frame",
            "accn", "duration_days",
        ]
    ]
    df.to_sql("facts", conn, if_exists="append", index=False)
    return len(df)


def load_concept_map(conn: sqlite3.Connection) -> int:
    rows = list(concept_map_rows())
    conn.executemany(
        "INSERT INTO concept_map "
        "(statement, line_label, line_order, concept, priority, sign) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def main() -> None:
    cik = config.COMPANY["cik"]
    raw_path = config.RAW_DIR / f"CIK{cik}_companyfacts.json"
    if not raw_path.exists():
        print("Raw file not found. Run fetch_edgar.py first.")
        return

    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    print(f"Building SQLite database at {config.DB_PATH} ...")
    conn = sqlite3.connect(config.DB_PATH)
    try:
        create_schema(conn)
        load_company(conn)
        n_facts = load_facts(conn, raw)
        n_map = load_concept_map(conn)
        conn.commit()
    finally:
        conn.close()

    print(f"  company     : 1 row")
    print(f"  facts       : {n_facts:,} rows")
    print(f"  concept_map : {n_map} rows")
    print("  Done.")


if __name__ == "__main__":
    main()
