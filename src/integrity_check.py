"""
Step 5 of the pipeline: the integrity guard.

Responsibility (one job only): prove the three statements are internally
consistent and actually linked. If any reconciliation breaks, this exits with a
non-zero code so the pipeline (and GitHub Actions) goes RED and refuses to
publish bad numbers.

Reconciliations:
    1. Balance sheet identity   Total Assets = Total Liabilities + Total Equity
    2. Cash reconciliation      (a) Beginning + CFO + CFI + CFF = Ending cash
                                (b) Ending cash ties to the balance-sheet cash
                                    line, apart from restricted cash (residual)
    3. Net income linkage       Net Income (Income Statement) = Net Income that
                                begins the Cash Flow (indirect method)

Tolerance: a difference passes if it is within 0.5% of the reference figure,
with a $1,000 absolute floor. (SEC figures are exact integers and our SQL is
exact, so real differences come out at essentially $0 -- far inside tolerance.)
The restricted-cash residual in check 2(b) is a known reconciling item, not
noise, so it is bounded separately (non-negative and < 2% of total assets).
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from src.build_views import build_views  # noqa: E402

# Tolerance settings.
TOL_PCT = 0.005          # 0.5%
TOL_ABS = 1_000          # $1,000 absolute floor
RESTRICTED_CASH_MAX_PCT = 0.02   # restricted-cash residual must stay < 2% of assets


def _within_tol(diff: float, reference: float) -> bool:
    return abs(diff) <= max(TOL_PCT * abs(reference), TOL_ABS)


def _fmt_b(x):
    """Format a number in USD billions, or '-' if missing."""
    return "-" if pd.isna(x) else f"{x / 1e9:,.3f}"


# ---------------------------------------------------------------------------
# Individual checks. Each returns (passed: bool, lines: list[str]).
# ---------------------------------------------------------------------------

def check_balance_identity(conn):
    df = pd.read_sql("SELECT * FROM v_balance_check", conn)
    lines, passed = [], True
    lines.append("  Year |   Assets | Liab+Equity |     Diff | OK")
    for _, r in df.iterrows():
        ok = _within_tol(r["balance_diff"], r["total_assets"])
        passed &= ok
        lines.append(
            f"  {int(r['fiscal_year'])} | {_fmt_b(r['total_assets']):>8} | "
            f"{_fmt_b(r['liabilities_plus_equity']):>11} | "
            f"{_fmt_b(r['balance_diff']):>8} | {'PASS' if ok else 'FAIL'}"
        )
    return passed, lines


def check_cash_reconciliation(conn):
    df = pd.read_sql("SELECT * FROM v_cash_reconciliation", conn)
    lines, passed = [], True

    # (a) roll-forward: beginning + net change = ending
    lines.append("  (a) Roll-forward: Beginning + CFO + CFI + CFF = Ending")
    lines.append("  Year | Begin |  CFO |  CFI |   CFF | Computed | Reported |  Diff | OK")
    for _, r in df.iterrows():
        if pd.isna(r["beginning_cash"]):
            lines.append(f"  {int(r['fiscal_year'])} |   (no prior-year cash available)")
            continue
        diff = r["computed_ending_cash"] - r["reported_ending_cash"]
        ok = _within_tol(diff, r["reported_ending_cash"])
        passed &= ok
        lines.append(
            f"  {int(r['fiscal_year'])} | {_fmt_b(r['beginning_cash']):>5} | "
            f"{_fmt_b(r['operating_cf']):>4} | {_fmt_b(r['investing_cf']):>4} | "
            f"{_fmt_b(r['financing_cf']):>5} | {_fmt_b(r['computed_ending_cash']):>8} | "
            f"{_fmt_b(r['reported_ending_cash']):>8} | {_fmt_b(diff):>5} | "
            f"{'PASS' if ok else 'FAIL'}"
        )

    # (b) ending cash ties to balance-sheet cash line (residual = restricted cash)
    lines.append("")
    lines.append("  (b) Ending cash vs Balance-sheet cash line (residual = restricted cash)")
    lines.append("  Year | Ending(CF) | Balance Cash | Residual | OK")
    for _, r in df.iterrows():
        resid = r["restricted_cash_residual"]
        # Residual = restricted cash. Must be non-negative (cash-flow total can't
        # be below face-value cash) and a small fraction of total assets.
        bound = RESTRICTED_CASH_MAX_PCT * r["total_assets"]
        ok = (resid >= -TOL_ABS) and (resid <= bound)
        passed &= ok
        note = "exact" if abs(resid) <= TOL_ABS else "restricted cash"
        lines.append(
            f"  {int(r['fiscal_year'])} | {_fmt_b(r['reported_ending_cash']):>10} | "
            f"{_fmt_b(r['balance_sheet_cash']):>12} | {_fmt_b(resid):>8} | "
            f"{'PASS' if ok else 'FAIL'} ({note})"
        )
    return passed, lines


def check_net_income_linkage(conn):
    df = pd.read_sql(
        "SELECT fiscal_year, net_income, net_income_cf FROM v_metrics ORDER BY fiscal_year",
        conn,
    )
    lines, passed = [], True
    lines.append("  Year | NI (Income Stmt) | NI (Cash Flow) |  Diff | OK")
    for _, r in df.iterrows():
        diff = (r["net_income"] or 0) - (r["net_income_cf"] or 0)
        ok = _within_tol(diff, r["net_income"])
        passed &= ok
        lines.append(
            f"  {int(r['fiscal_year'])} | {_fmt_b(r['net_income']):>16} | "
            f"{_fmt_b(r['net_income_cf']):>14} | {_fmt_b(diff):>5} | "
            f"{'PASS' if ok else 'FAIL'}"
        )
    return passed, lines


def check_quarterly_reconciliation(conn):
    """Derived standalone quarters (Q1+Q2+Q3+Q4) must equal the reported annual."""
    concepts = [
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenue"),
        ("NetIncomeLoss", "Net Income"),
        ("NetCashProvidedByUsedInOperatingActivities", "Operating CF"),
    ]
    lines, passed = [], True
    lines.append("  Concept       | FY   | Sum Q1-Q4 |  Annual  |  Diff | OK")
    for con, name in concepts:
        df = pd.read_sql(
            "SELECT rc.fiscal_year AS fy, rc.sum_quarters AS sumq, "
            "(SELECT value FROM v_annual_facts a "
            " WHERE a.concept = rc.concept AND a.fiscal_year = rc.fiscal_year) AS annual "
            "FROM v_quarterly_reconcile rc "
            "WHERE rc.concept = ? AND rc.n_quarters = 4 ORDER BY rc.fiscal_year",
            conn, params=(con,),
        )
        for r in df.itertuples():
            if pd.isna(r.annual):
                continue                      # year outside the 5-year annual window
            diff = r.sumq - r.annual
            ok = _within_tol(diff, r.annual)
            passed &= ok
            lines.append(
                f"  {name:13} | {int(r.fy)} | {_fmt_b(r.sumq):>9} | "
                f"{_fmt_b(r.annual):>8} | {_fmt_b(diff):>5} | {'PASS' if ok else 'FAIL'}"
            )
    return passed, lines


CHECKS = [
    ("1. Balance sheet identity (Assets = Liabilities + Equity)", check_balance_identity),
    ("2. Cash reconciliation (roll-forward + balance tie-out)", check_cash_reconciliation),
    ("3. Net income linkage (Income Statement = Cash Flow)", check_net_income_linkage),
    ("4. Quarterly reconciliation (Q1+Q2+Q3+Q4 = annual)", check_quarterly_reconciliation),
]


def run_checks(conn) -> bool:
    """Run every check, print results, return True only if ALL pass."""
    print("=" * 70)
    print("  INTEGRITY CHECK  (tolerance: 0.5% or $1,000, all figures USD billions)")
    print("=" * 70)

    all_passed = True
    for title, fn in CHECKS:
        passed, lines = fn(conn)
        all_passed &= passed
        status = "PASS" if passed else "*** FAIL ***"
        print(f"\n[{status}] {title}")
        for ln in lines:
            print(ln)

    print("\n" + "=" * 70)
    print(f"  OVERALL: {'ALL CHECKS PASSED' if all_passed else '*** INTEGRITY CHECK FAILED ***'}")
    print("=" * 70)
    return all_passed


def main() -> bool:
    conn = sqlite3.connect(config.DB_PATH)
    try:
        build_views(conn)          # ensure view definitions exist (does not touch data)
        return run_checks(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
