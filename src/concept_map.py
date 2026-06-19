"""
The concept map: translates messy XBRL tags into clean, standardized statement
lines, WITH FALLBACKS.

Why fallbacks matter: different companies (and even the same company across
years) tag the same economic line with different XBRL concept names. For each
standardized line we list candidate concepts in PRIORITY order (priority 1 =
preferred). The SQL in build_views.py picks, for each year, the highest-priority
concept that actually has a value. This is what fills the gaps.

Each entry: (statement, line_label, line_order, [candidate concepts in priority order])
    statement   "income" | "balance" | "cashflow"
    line_label  human-readable line shown in the dashboard
    line_order  display order within its statement
    candidates  XBRL concepts, best first

`sign` is +1 for every line here (all these concepts are reported in their
natural orientation by US filers); kept as a column for future flexibility.
"""

CONCEPT_MAP = [
    # ----------------------- INCOME STATEMENT -----------------------
    ("income", "Revenue", 1, [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ]),
    ("income", "Cost of Revenue", 2, [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ]),
    ("income", "Gross Profit", 3, [
        "GrossProfit",
    ]),
    ("income", "Operating Expenses", 4, [
        "OperatingExpenses",
        "CostsAndExpenses",
    ]),
    ("income", "Operating Income", 5, [
        "OperatingIncomeLoss",
    ]),
    ("income", "Pretax Income", 6, [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ]),
    ("income", "Income Tax", 7, [
        "IncomeTaxExpenseBenefit",
    ]),
    ("income", "Net Income", 8, [
        "NetIncomeLoss",
        "ProfitLoss",
    ]),

    # ------------------------- BALANCE SHEET ------------------------
    ("balance", "Total Assets", 1, [
        "Assets",
    ]),
    ("balance", "Current Assets", 2, [
        "AssetsCurrent",
    ]),
    ("balance", "Cash & Equivalents", 3, [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ]),
    ("balance", "Total Liabilities", 4, [
        "Liabilities",
    ]),
    ("balance", "Current Liabilities", 5, [
        "LiabilitiesCurrent",
    ]),
    ("balance", "Total Equity", 6, [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ]),

    # -------------------------- CASH FLOW ---------------------------
    ("cashflow", "Net Income", 1, [
        "NetIncomeLoss",
        "ProfitLoss",
    ]),
    ("cashflow", "Operating Cash Flow", 2, [
        "NetCashProvidedByUsedInOperatingActivities",
    ]),
    ("cashflow", "Investing Cash Flow", 3, [
        "NetCashProvidedByUsedInInvestingActivities",
    ]),
    ("cashflow", "Financing Cash Flow", 4, [
        "NetCashProvidedByUsedInFinancingActivities",
    ]),
    ("cashflow", "Capital Expenditures", 5, [
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ]),
    ("cashflow", "Net Change in Cash (reported)", 6, [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ]),
]


def iter_rows():
    """Yield flat (statement, line_label, line_order, concept, priority, sign)
    rows ready to insert into the concept_map table."""
    for statement, line_label, line_order, candidates in CONCEPT_MAP:
        for priority, concept in enumerate(candidates, start=1):
            yield (statement, line_label, line_order, concept, priority, 1)
