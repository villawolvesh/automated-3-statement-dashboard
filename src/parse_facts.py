"""
Step 2 of the pipeline: turn the giant raw EDGAR JSON into a clean, tidy table.

Responsibility (one job only): flatten facts -> us-gaap into one row per
reported data point, then de-duplicate restatements so we keep the most
recently filed value for each (concept, period). The output is a pandas
DataFrame that load_db.py will write into SQLite.

Key columns produced:
    concept        XBRL tag, e.g. "NetIncomeLoss"
    unit           reporting unit, e.g. "USD" or "shares"
    period_start   start date (None for balance-sheet "instant" facts)
    period_end     end date (the snapshot/period-end date)
    value          the reported number
    fiscal_year    e.g. 2024
    fiscal_period  "FY" for annual, "Q1".."Q4" for quarterly
    form           filing type, e.g. "10-K" or "10-Q"
    filed          date the filing was submitted (used to pick latest)
    frame          EDGAR period frame, e.g. "CY2024" (None when not provided)
    accn           accession number (the unique filing id)
    duration_days  period length in days (NaN for instant facts)
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def parse_facts(raw: dict) -> pd.DataFrame:
    """Flatten the us-gaap section of a companyfacts JSON into a tidy table."""
    rows = []
    us_gaap = raw.get("facts", {}).get("us-gaap", {})

    for concept, body in us_gaap.items():
        for unit, datapoints in body.get("units", {}).items():
            for dp in datapoints:
                rows.append(
                    {
                        "concept": concept,
                        "unit": unit,
                        "period_start": dp.get("start"),   # None for instant facts
                        "period_end": dp.get("end"),
                        "value": dp.get("val"),
                        "fiscal_year": dp.get("fy"),
                        "fiscal_period": dp.get("fp"),
                        "form": dp.get("form"),
                        "filed": dp.get("filed"),
                        "frame": dp.get("frame"),
                        "accn": dp.get("accn"),
                    }
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Parse dates and compute period length (helps separate annual vs quarterly).
    df["period_start"] = pd.to_datetime(df["period_start"], errors="coerce")
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce")
    df["duration_days"] = (df["period_end"] - df["period_start"]).dt.days

    return df


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one value per (concept, unit, period_start, period_end).

    The SEC repeats the same fact across many filings, and restatements can
    change a value. We keep the most recently FILED version so the numbers
    reflect the latest official figures.
    """
    if df.empty:
        return df

    df = df.sort_values("filed")
    keys = ["concept", "unit", "period_start", "period_end"]
    deduped = df.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)
    return deduped


def build_clean_facts(raw: dict) -> pd.DataFrame:
    """Convenience wrapper: parse + deduplicate in one call."""
    return deduplicate(parse_facts(raw))


def annual_facts(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to annual (10-K, full fiscal year) figures, last N years.

    For duration facts (income / cash flow) we keep ~full-year periods
    (>= 350 days). Instant facts (balance sheet) have no duration and are
    kept when they come from a 10-K fiscal-year filing.
    """
    if df.empty:
        return df

    is_10k = df["form"] == "10-K"
    is_fy = df["fiscal_period"] == "FY"
    is_full_year = df["duration_days"] >= 350
    is_instant = df["duration_days"].isna()

    annual = df[is_10k & is_fy & (is_full_year | is_instant)].copy()

    # Keep only the most recent N fiscal years.
    recent_years = sorted(annual["fiscal_year"].dropna().unique())[-config.YEARS_HISTORY:]
    annual = annual[annual["fiscal_year"].isin(recent_years)]

    return annual.sort_values(["concept", "period_end"]).reset_index(drop=True)


def main():
    """Demo: show a clean sample of key Apple figures for the last 5 years."""
    import json

    cik = config.COMPANY["cik"]
    raw_path = config.RAW_DIR / f"CIK{cik}_companyfacts.json"
    if not raw_path.exists():
        print("Raw file not found. Run fetch_edgar.py first.")
        return

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    clean = build_clean_facts(raw)
    annual = annual_facts(clean)

    print(f"Total clean facts (all concepts/periods): {len(clean):,}")
    print(f"Annual facts (last {config.YEARS_HISTORY} FY): {len(annual):,}\n")

    # A few headline concepts to eyeball that the data looks right.
    sample_concepts = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "CostOfGoodsAndServicesSold",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "NetCashProvidedByUsedInOperatingActivities",
    ]

    sample = annual[annual["concept"].isin(sample_concepts)].copy()
    sample["year"] = sample["period_end"].dt.year
    sample["value_$B"] = (sample["value"] / 1e9).round(2)

    pivot = sample.pivot_table(
        index="concept", columns="year", values="value_$B", aggfunc="last"
    )
    # Preserve our intended row order.
    pivot = pivot.reindex([c for c in sample_concepts if c in pivot.index])

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print("Sample of clean annual data (USD billions):\n")
    print(pivot.to_string())


if __name__ == "__main__":
    main()
