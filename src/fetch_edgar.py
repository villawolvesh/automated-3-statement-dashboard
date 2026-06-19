"""
Step 1 of the pipeline: download the raw company facts from SEC EDGAR.

Responsibility (one job only): hit the EDGAR companyfacts endpoint for the
configured company and save the raw JSON to data/raw/. We keep the raw file
untouched so the whole pipeline is auditable and re-runnable offline.
"""

import json
import sys
import time
from pathlib import Path

import requests

# Allow running this file directly (python src/fetch_edgar.py) by adding the
# project root to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def fetch_company_facts(cik: str, user_agent: str, retries: int = 3) -> dict:
    """Download the companyfacts JSON for one CIK and return it as a dict.

    Retries a few times because the SEC occasionally rate-limits bursts.
    """
    url = config.EDGAR_COMPANYFACTS_URL.format(cik=cik)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            print(f"  Attempt {attempt}/{retries} failed: {exc}")
            time.sleep(2 * attempt)  # simple backoff, be polite to the SEC

    raise RuntimeError(f"Could not fetch EDGAR data after {retries} tries: {last_error}")


def save_raw(facts: dict, cik: str) -> Path:
    """Persist the raw JSON to data/raw/ for auditing and offline re-runs."""
    out_path = config.RAW_DIR / f"CIK{cik}_companyfacts.json"
    out_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    return out_path


def main() -> dict:
    cik = config.COMPANY["cik"]
    print(f"Fetching SEC EDGAR company facts for CIK {cik} ...")
    facts = fetch_company_facts(cik, config.USER_AGENT)

    out_path = save_raw(facts, cik)
    n_concepts = len(facts.get("facts", {}).get("us-gaap", {}))
    print(f"  Entity      : {facts.get('entityName')}")
    print(f"  us-gaap tags: {n_concepts}")
    print(f"  Saved raw   : {out_path}")
    return facts


if __name__ == "__main__":
    main()
