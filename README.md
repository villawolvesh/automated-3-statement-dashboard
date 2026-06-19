# Automated 3-Statement Financial Dashboard

An interactive dashboard of the three linked financial statements — **Income Statement,
Balance Sheet, and Cash Flow** — for a public company, built directly from official
**SEC EDGAR XBRL** filings. Figures are computed in auditable SQL, validated by an
integrity guard, and the whole thing **refreshes itself weekly** via GitHub Actions.

**▶ Live dashboard:** https://YOUR_USERNAME.github.io/automated-3-statement-dashboard/
<!-- Update YOUR_USERNAME after enabling GitHub Pages (Settings → Pages → Deploy from branch: main /docs). -->

Current company: **Apple Inc. (AAPL)** · parameterizable by ticker/CIK in `config.py`.

---

## What it does

- **Three linked statements** with a spreadsheet-style table: all fiscal years as columns,
  a sticky first column, and per-row click-through to a trend chart.
- **Four views** per statement, each labeled with what it compares against:
  `Values $` · `Growth (YoY %)` · `Growth (QoQ %)` · `% of Revenue / Assets`.
- **Annual & Quarterly** toggle. Apple files year-to-date and no standalone fiscal Q4, so
  standalone quarters are **derived by exact differencing** (`Q4 = FY − 9M`,
  `Q2 = H1 − Q1`, …) and clearly **marked as derived**. In-progress fiscal years are
  flagged *partial / YTD* and never used as a full-year comparison base.
- **Ratios** (gross/operating/net margin, ROE, current ratio, free cash flow), **bridges**
  (income & cash waterfalls with their own period selector), and a **Variance** A-vs-B
  comparator.
- **Two-layer variance notes:** an automatic layer that describes *magnitude only*
  (e.g. "Income tax was 7.6% of revenue in FY2024, well above its ~4.6% average"), and a
  hand-curated layer (`data/notes.json`) that supplies the verified *cause* with a source.

## How the numbers are guaranteed

Everything is computed in **visible SQL views** over the raw XBRL facts (open
`data/financials.db` and re-run them). An **integrity guard** (`src/integrity_check.py`)
fails the build — and blocks publishing — unless all reconcile:

1. Balance sheet identity: `Assets = Liabilities + Equity`
2. Cash roll-forward: `Beginning + CFO + CFI + CFF = Ending`, tied to the balance-sheet cash
3. Net income linkage: Income Statement net income = Cash Flow net income
4. Quarterly reconciliation: `Q1 + Q2 + Q3 + Q4 (derived) = reported annual`

Every headline figure is validated against Apple's official filings.

## Tech stack

`Python` (requests · pandas) → `SQLite` (auditable views) → `Plotly` (self-contained HTML)
→ `GitHub Pages` (hosting) → `GitHub Actions` (weekly cron auto-refresh).

## Run it locally

```bash
pip install -r requirements.txt

# SEC requires a contact email in the User-Agent (kept out of source):
export SEC_USER_AGENT="Your Name your@email.com"     # PowerShell: $env:SEC_USER_AGENT="..."

python src/run_pipeline.py            # fetch EDGAR → SQLite → views → integrity → dashboard
#   add --no-fetch to rebuild from the cached database without hitting EDGAR
```

Open `docs/index.html` in a browser (it is self-contained).

## Auto-update (the differentiator)

`.github/workflows/update.yml` runs every Monday: it re-pulls EDGAR, rebuilds everything,
runs the integrity guard, and commits the regenerated `docs/index.html`. If any
reconciliation fails, the run goes red and **nothing is published**. GitHub Pages serves
the refreshed dashboard automatically.

## Project layout

```
config.py                 ticker/CIK, paths, SEC_USER_AGENT
src/fetch_edgar.py        download companyfacts JSON
src/parse_facts.py        flatten the XBRL JSON into tidy rows
src/concept_map.py        XBRL tags → standardized lines (with fallbacks)
src/load_db.py            land facts into SQLite
src/build_views.py        ALL financial logic as SQL views (annual + quarterly)
src/integrity_check.py    the 4 reconciliation guards
src/revisions.py          restatement log (flags "revised from X to Y")
src/build_dashboard.py    render the interactive HTML
src/run_pipeline.py       one-command end-to-end run
data/notes.json           curated variance notes (editable)
docs/index.html           the published dashboard
docs/LESSONS_LEARNED.md   reusable engineering notes
```

Data: **SEC EDGAR** (public domain). This project is for analysis/education and is not
investment advice.
