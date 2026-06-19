"""
Step 4 of the pipeline: build the SQL VIEWS that compute the statements.

Responsibility (one job only): create the views that turn raw facts into the
three linked statements, ratios, common-size, and variance. ALL financial logic
lives here, in plain SQL, so it is transparent and verifiable -- open
financials.db in any SQLite tool and you can read exactly how every number is
produced.

View dependency order:
    v_annual_facts    one value per concept per fiscal-year-end (picks latest
                      10-K / FY filing; this is what closes the XBRL gaps)
    v_statement_lines applies concept_map with fallbacks (best available tag)
    v_income_statement / v_balance_sheet / v_cash_flow   the 3 statements
    v_metrics         wide one-row-per-year table of headline magnitudes
    v_balance_check   Assets = Liabilities + Equity, with the difference
    v_ratios          margins, ROE, current ratio, free cash flow
    v_common_size     each line as % of revenue (income) / total assets (balance)
    v_metrics_long    metrics unpivoted to (year, metric, value)
    v_variance        YoY change (absolute and %) per metric
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

# Keep only the most recent N fiscal years everywhere.
YEARS = config.YEARS_HISTORY

VIEWS_SQL = f"""
DROP VIEW IF EXISTS v_quarterly_reconcile;
DROP VIEW IF EXISTS v_quarterly_statement_lines;
DROP VIEW IF EXISTS v_quarterly_facts;
DROP VIEW IF EXISTS v_quarter_spine;
DROP VIEW IF EXISTS v_flow_standalone;
DROP VIEW IF EXISTS v_flow_cumulative;
DROP VIEW IF EXISTS v_fy_starts;
DROP VIEW IF EXISTS v_variance;
DROP VIEW IF EXISTS v_metrics_long;
DROP VIEW IF EXISTS v_common_size;
DROP VIEW IF EXISTS v_ratios;
DROP VIEW IF EXISTS v_cash_reconciliation;
DROP VIEW IF EXISTS v_cash_anchor;
DROP VIEW IF EXISTS v_balance_check;
DROP VIEW IF EXISTS v_metrics;
DROP VIEW IF EXISTS v_cash_flow;
DROP VIEW IF EXISTS v_balance_sheet;
DROP VIEW IF EXISTS v_income_statement;
DROP VIEW IF EXISTS v_statement_lines;
DROP VIEW IF EXISTS v_annual_facts;

-- One clean value per concept per fiscal-year-end.
-- Filters to annual 10-K / FY contexts, keeps the latest-filed value for each
-- period (handles restatements), and keeps only the last {YEARS} fiscal years.
CREATE VIEW v_annual_facts AS
WITH ranked AS (
    SELECT
        concept,
        value,
        CAST(strftime('%Y', period_end) AS INTEGER) AS fiscal_year,
        period_end,
        ROW_NUMBER() OVER (
            PARTITION BY concept, period_end
            ORDER BY filed DESC
        ) AS rn
    FROM facts
    WHERE form = '10-K'
      AND fiscal_period = 'FY'
      AND (duration_days IS NULL OR duration_days >= 350)
)
SELECT concept, fiscal_year, period_end, value
FROM ranked
WHERE rn = 1
  AND fiscal_year > (
        SELECT MAX(CAST(strftime('%Y', period_end) AS INTEGER))
        FROM facts WHERE form = '10-K' AND fiscal_period = 'FY'
      ) - {YEARS};

-- Map raw concepts to standardized statement lines, applying fallbacks:
-- per line per year, take the highest-priority concept that has a value.
CREATE VIEW v_statement_lines AS
WITH mapped AS (
    SELECT
        m.statement,
        m.line_label,
        m.line_order,
        a.fiscal_year,
        m.sign * a.value AS value,
        ROW_NUMBER() OVER (
            PARTITION BY m.statement, m.line_label, a.fiscal_year
            ORDER BY m.priority
        ) AS pick
    FROM concept_map m
    JOIN v_annual_facts a ON a.concept = m.concept
)
SELECT statement, line_label, line_order, fiscal_year, value
FROM mapped
WHERE pick = 1;

-- The three statements (long format: one row per line per year).
CREATE VIEW v_income_statement AS
SELECT line_order, line_label, fiscal_year, value
FROM v_statement_lines WHERE statement = 'income';

CREATE VIEW v_balance_sheet AS
SELECT line_order, line_label, fiscal_year, value
FROM v_statement_lines WHERE statement = 'balance';

CREATE VIEW v_cash_flow AS
SELECT line_order, line_label, fiscal_year, value
FROM v_statement_lines WHERE statement = 'cashflow';

-- Headline magnitudes, one row per fiscal year (wide).
CREATE VIEW v_metrics AS
SELECT
    fiscal_year,
    MAX(CASE WHEN statement='income'   AND line_label='Revenue'                       THEN value END) AS revenue,
    MAX(CASE WHEN statement='income'   AND line_label='Cost of Revenue'               THEN value END) AS cogs,
    MAX(CASE WHEN statement='income'   AND line_label='Gross Profit'                  THEN value END) AS gross_profit,
    MAX(CASE WHEN statement='income'   AND line_label='Operating Income'              THEN value END) AS operating_income,
    MAX(CASE WHEN statement='income'   AND line_label='Net Income'                    THEN value END) AS net_income,
    MAX(CASE WHEN statement='balance'  AND line_label='Total Assets'                  THEN value END) AS total_assets,
    MAX(CASE WHEN statement='balance'  AND line_label='Current Assets'                THEN value END) AS current_assets,
    MAX(CASE WHEN statement='balance'  AND line_label='Cash & Equivalents'            THEN value END) AS cash,
    MAX(CASE WHEN statement='balance'  AND line_label='Total Liabilities'             THEN value END) AS total_liabilities,
    MAX(CASE WHEN statement='balance'  AND line_label='Current Liabilities'           THEN value END) AS current_liabilities,
    MAX(CASE WHEN statement='balance'  AND line_label='Total Equity'                  THEN value END) AS total_equity,
    MAX(CASE WHEN statement='cashflow' AND line_label='Operating Cash Flow'           THEN value END) AS operating_cf,
    MAX(CASE WHEN statement='cashflow' AND line_label='Investing Cash Flow'           THEN value END) AS investing_cf,
    MAX(CASE WHEN statement='cashflow' AND line_label='Financing Cash Flow'           THEN value END) AS financing_cf,
    MAX(CASE WHEN statement='cashflow' AND line_label='Capital Expenditures'          THEN value END) AS capex,
    MAX(CASE WHEN statement='cashflow' AND line_label='Net Income'                    THEN value END) AS net_income_cf,
    MAX(CASE WHEN statement='cashflow' AND line_label='Net Change in Cash (reported)' THEN value END) AS net_change_cash_reported
FROM v_statement_lines
GROUP BY fiscal_year;

-- Balance-sheet identity check: Assets should equal Liabilities + Equity.
CREATE VIEW v_balance_check AS
SELECT
    fiscal_year,
    total_assets,
    total_liabilities,
    total_equity,
    total_liabilities + total_equity AS liabilities_plus_equity,
    total_assets - (total_liabilities + total_equity) AS balance_diff
FROM v_metrics
ORDER BY fiscal_year;

-- Cash anchor: the cash-flow statement's own cash concept (cash + restricted
-- cash) at every fiscal year-end. Not limited to 5 years, so the FY2021
-- "beginning cash" (= FY2020 year-end) is available for the roll-forward.
CREATE VIEW v_cash_anchor AS
WITH ranked AS (
    SELECT
        CAST(strftime('%Y', period_end) AS INTEGER) AS fiscal_year,
        period_end,
        value,
        ROW_NUMBER() OVER (PARTITION BY period_end ORDER BY filed DESC) AS rn
    FROM facts
    WHERE concept = 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'
      AND form = '10-K'
      AND period_start IS NULL          -- instant facts only
)
SELECT fiscal_year, value AS ending_cash FROM ranked WHERE rn = 1;

-- Cash reconciliation: beginning + (CFO + CFI + CFF) should equal ending,
-- and ending (cash-flow basis) ties to the balance-sheet cash line apart from
-- restricted cash (the residual below; ~0 in recent years).
CREATE VIEW v_cash_reconciliation AS
SELECT
    m.fiscal_year,
    prev.ending_cash                                                      AS beginning_cash,
    m.operating_cf,
    m.investing_cf,
    m.financing_cf,
    (m.operating_cf + m.investing_cf + m.financing_cf)                    AS net_change,
    prev.ending_cash + (m.operating_cf + m.investing_cf + m.financing_cf) AS computed_ending_cash,
    cur.ending_cash                                                       AS reported_ending_cash,
    m.cash                                                                AS balance_sheet_cash,
    cur.ending_cash - m.cash                                             AS restricted_cash_residual,
    m.total_assets                                                        AS total_assets
FROM v_metrics m
JOIN      v_cash_anchor cur  ON cur.fiscal_year  = m.fiscal_year
LEFT JOIN v_cash_anchor prev ON prev.fiscal_year = m.fiscal_year - 1
ORDER BY m.fiscal_year;

-- Key ratios.
CREATE VIEW v_ratios AS
SELECT
    fiscal_year,
    gross_profit     * 1.0 / revenue              AS gross_margin,
    operating_income * 1.0 / revenue              AS operating_margin,
    net_income       * 1.0 / revenue              AS net_margin,
    net_income       * 1.0 / total_equity         AS roe,
    current_assets   * 1.0 / current_liabilities  AS current_ratio,
    operating_cf - capex                          AS free_cash_flow
FROM v_metrics
ORDER BY fiscal_year;

-- Common-size: income lines as % of revenue, balance lines as % of total assets.
CREATE VIEW v_common_size AS
SELECT
    s.statement,
    s.line_order,
    s.line_label,
    s.fiscal_year,
    s.value,
    CASE
        WHEN s.statement = 'income'  THEN s.value * 1.0 / m.revenue
        WHEN s.statement = 'balance' THEN s.value * 1.0 / m.total_assets
    END AS pct_of_base
FROM v_statement_lines s
JOIN v_metrics m ON m.fiscal_year = s.fiscal_year
WHERE s.statement IN ('income', 'balance');

-- Metrics unpivoted to (year, metric, value) for variance.
CREATE VIEW v_metrics_long AS
            SELECT fiscal_year, 'Revenue'             AS metric, revenue          AS value FROM v_metrics
  UNION ALL SELECT fiscal_year, 'Gross Profit',              gross_profit              FROM v_metrics
  UNION ALL SELECT fiscal_year, 'Operating Income',          operating_income          FROM v_metrics
  UNION ALL SELECT fiscal_year, 'Net Income',                net_income                FROM v_metrics
  UNION ALL SELECT fiscal_year, 'Total Assets',              total_assets              FROM v_metrics
  UNION ALL SELECT fiscal_year, 'Total Equity',              total_equity              FROM v_metrics
  UNION ALL SELECT fiscal_year, 'Operating Cash Flow',       operating_cf              FROM v_metrics;

-- ===================== QUARTERLY (regular 4-quarter calendar) ===============
-- Apple files income/cash-flow figures year-to-date (Q1=3m, Q2=6m, Q3=9m,
-- FY=12m) and never files a standalone fiscal Q4. We rebuild every standalone
-- quarter -- including Q4 -- by differencing the YTD cumulatives, all aligned by
-- period_start (the fiscal-year start). This is exact accounting arithmetic on
-- reported figures, never an estimate. Balance-sheet items are snapshots and
-- are taken as-is at each quarter-end (the Sep year-end IS Q4).

-- Fiscal-year start dates. Only a fiscal-year start carries a >= 6-month YTD
-- fact (H1, 9-month, or full year). A mere quarter start (e.g. the start of a
-- standalone Q2/Q3) only has a ~3-month fact, so duration >= 170 cleanly keeps
-- fiscal-year starts and excludes quarter starts.
CREATE VIEW v_fy_starts AS
SELECT DISTINCT period_start
FROM facts
WHERE period_start IS NOT NULL
  AND form IN ('10-Q', '10-K')
  AND duration_days >= 170;

-- Cumulative YTD flow values per concept per fiscal year (3m/6m/9m/12m),
-- keeping the latest-filed value for each point (handles restatements).
CREATE VIEW v_flow_cumulative AS
WITH ranked AS (
    SELECT
        concept, period_start, period_end, value,
        ROW_NUMBER() OVER (PARTITION BY concept, period_start, period_end ORDER BY filed DESC) AS rn
    FROM facts
    WHERE form IN ('10-Q', '10-K')
      AND period_start IN (SELECT period_start FROM v_fy_starts)
      AND duration_days BETWEEN 80 AND 380
)
SELECT concept, period_start, period_end, value FROM ranked WHERE rn = 1;

-- Standalone quarter = YTD cumulative minus the previous quarter's cumulative.
-- qnum 1..4 within each fiscal year; fiscal_year derived from the period_start
-- (Apple's fiscal year starts in Sep/Oct of the prior calendar year).
CREATE VIEW v_flow_standalone AS
SELECT
    concept,
    period_end,
    value - COALESCE(
        LAG(value) OVER (PARTITION BY concept, period_start ORDER BY period_end), 0
    ) AS value,
    ROW_NUMBER() OVER (PARTITION BY concept, period_start ORDER BY period_end) AS qnum,
    CAST(strftime('%Y', period_start) AS INTEGER) + 1 AS fiscal_year
FROM v_flow_cumulative;

-- Regular quarter spine: every Q1..Q4 from a reference series (NetIncomeLoss,
-- longest history) for every fiscal year inside the annual window (so complete
-- years like FY2021 keep all four quarters; the current in-progress year is
-- included with whatever quarters are filed). Never slices a year in half.
CREATE VIEW v_quarter_spine AS
SELECT period_end, fiscal_year, qnum,
       'Q' || qnum || ' FY' || substr(CAST(fiscal_year AS TEXT), 3, 2) AS label
FROM v_flow_standalone
WHERE concept = 'NetIncomeLoss'
  AND fiscal_year >= (SELECT MIN(fiscal_year) FROM v_metrics)
ORDER BY period_end;

-- One value per concept per spine quarter: derived standalone flow, OR the
-- quarter-end instant snapshot for balance-sheet items.
CREATE VIEW v_quarterly_facts AS
SELECT s.concept, s.period_end, s.value
FROM v_flow_standalone s
JOIN v_quarter_spine sp ON sp.period_end = s.period_end
UNION ALL
SELECT concept, period_end, value FROM (
    SELECT
        f.concept, f.period_end, f.value,
        ROW_NUMBER() OVER (PARTITION BY f.concept, f.period_end ORDER BY f.filed DESC) AS rn
    FROM facts f
    JOIN v_quarter_spine sp ON sp.period_end = f.period_end
    WHERE f.period_start IS NULL AND f.form IN ('10-Q', '10-K')   -- instant
) WHERE rn = 1;

-- Standardized statement lines, quarterly (same concept_map + fallback logic).
CREATE VIEW v_quarterly_statement_lines AS
WITH mapped AS (
    SELECT
        m.statement, m.line_label, m.line_order, q.period_end,
        m.sign * q.value AS value,
        ROW_NUMBER() OVER (
            PARTITION BY m.statement, m.line_label, q.period_end ORDER BY m.priority
        ) AS pick
    FROM concept_map m
    JOIN v_quarterly_facts q ON q.concept = m.concept
)
SELECT statement, line_label, line_order, period_end, value
FROM mapped WHERE pick = 1;

-- Guard: the four derived standalone quarters must sum to the reported annual.
-- One row per (concept, fiscal_year) with the quarter sum and quarter count.
CREATE VIEW v_quarterly_reconcile AS
SELECT concept, fiscal_year, COUNT(*) AS n_quarters, SUM(value) AS sum_quarters
FROM v_flow_standalone
GROUP BY concept, fiscal_year;

-- Year-over-year variance (absolute and %).
CREATE VIEW v_variance AS
SELECT
    fiscal_year,
    metric,
    value,
    LAG(value) OVER (PARTITION BY metric ORDER BY fiscal_year) AS prior_value,
    value - LAG(value) OVER (PARTITION BY metric ORDER BY fiscal_year) AS delta_abs,
    CASE
        WHEN LAG(value) OVER (PARTITION BY metric ORDER BY fiscal_year) NOT IN (0)
        THEN (value - LAG(value) OVER (PARTITION BY metric ORDER BY fiscal_year)) * 1.0
             / LAG(value) OVER (PARTITION BY metric ORDER BY fiscal_year)
    END AS delta_pct
FROM v_metrics_long;
"""


def build_views(conn: sqlite3.Connection) -> None:
    conn.executescript(VIEWS_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Display helpers (used to show the checkpoint output for Hito 2)
# ---------------------------------------------------------------------------

def _pivot_statement(conn, view, title):
    df = pd.read_sql(f"SELECT * FROM {view}", conn)
    wide = df.pivot_table(
        index=["line_order", "line_label"], columns="fiscal_year",
        values="value", aggfunc="last",
    )
    wide = (wide / 1e9).round(2)  # USD billions
    wide.index = wide.index.droplevel("line_order")
    print(f"\n===== {title}  (USD billions) =====")
    print(wide.to_string())


def main():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        build_views(conn)
        pd.set_option("display.width", 220)
        pd.set_option("display.max_columns", 30)

        _pivot_statement(conn, "v_income_statement", "INCOME STATEMENT")
        _pivot_statement(conn, "v_balance_sheet", "BALANCE SHEET")
        _pivot_statement(conn, "v_cash_flow", "CASH FLOW")

        print("\n===== BALANCE CHECK: Assets = Liabilities + Equity  (USD billions) =====")
        chk = pd.read_sql("SELECT * FROM v_balance_check", conn)
        show = chk.copy()
        for c in ["total_assets", "total_liabilities", "total_equity",
                  "liabilities_plus_equity", "balance_diff"]:
            show[c] = (show[c] / 1e9).round(3)
        print(show.to_string(index=False))

        print("\n===== RATIOS =====")
        rat = pd.read_sql("SELECT * FROM v_ratios", conn)
        fmt = rat.copy()
        for c in ["gross_margin", "operating_margin", "net_margin", "roe"]:
            fmt[c] = (fmt[c] * 100).round(1).astype(str) + "%"
        fmt["current_ratio"] = fmt["current_ratio"].round(2)
        fmt["free_cash_flow"] = (fmt["free_cash_flow"] / 1e9).round(2).astype(str) + "B"
        print(fmt.to_string(index=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
