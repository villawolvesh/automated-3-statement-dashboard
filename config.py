"""
Central configuration for the Automated 3-Statement Financial Dashboard.

Everything that changes between companies or environments lives here, so the
rest of the codebase never hard-codes a ticker, a path, or a contact email.
To analyze a different company, change COMPANY below (one line).
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Company under analysis
# ---------------------------------------------------------------------------
# CIK must be the 10-digit, zero-padded form used by the SEC EDGAR API.
COMPANY = {
    "ticker": "AAPL",
    "cik": "0000320193",      # Apple Inc.
    "entity_name": "Apple Inc.",
}

# ---------------------------------------------------------------------------
# SEC EDGAR API
# ---------------------------------------------------------------------------
# The SEC requires a descriptive User-Agent with a contact email. No API key.
# To avoid hard-coding a personal email in a public repo, it is read from the
# SEC_USER_AGENT environment variable. Set it locally before running the
# pipeline, and as a GitHub Actions secret for the scheduled refresh:
#   PowerShell:  $env:SEC_USER_AGENT = "Your Name your@email.com"
#   bash:        export SEC_USER_AGENT="Your Name your@email.com"
# Read the raw value (empty string if the variable is missing OR set but blank --
# e.g. an unset GitHub Actions secret injects ""). fetch_edgar validates it before
# any request and fails loudly, so we never send an empty User-Agent (-> 403).
USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()

# companyfacts endpoint: all reported XBRL facts for one company, in one JSON.
EDGAR_COMPANYFACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)

# How many fiscal years of history to keep in the dashboard.
YEARS_HISTORY = 5

# Public repository URL (used for the "source code" link in the dashboard/README).
# Updated to the real URL during the GitHub publishing step.
REPO_URL = "https://github.com/villawolvesh/automated-3-statement-dashboard"

# ---------------------------------------------------------------------------
# Project paths (resolved relative to this file, so it works anywhere)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "financials.db"
DOCS_DIR = ROOT / "docs"
HTML_OUT = DOCS_DIR / "index.html"

# Make sure the folders exist when any module imports config.
for _d in (RAW_DIR, DOCS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
