"""
Step 6 of the pipeline: render the interactive dashboard (docs/index.html).

Responsibility (one job only): read the SQL views, package the numbers + a few
plain-English insights into the HTML template, and write ONE self-contained
index.html (Plotly via CDN, inline JS) that opens with a double-click.

All financial logic stays in SQL; this module only shapes data for display and
writes narrative sentences derived strictly from the computed figures.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from src.build_views import build_views  # noqa: E402
from src import revisions as revmod  # noqa: E402

TEMPLATE_DIR = config.ROOT / "templates"


# ---------------------------------------------------------------------------
# Helpers to turn views into JSON-friendly Python structures
# ---------------------------------------------------------------------------

def _clean(v):
    """numpy/pandas value -> JSON-safe Python scalar (NaN -> None)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return None
    return float(v)


# Per-statement configuration for the spreadsheet tables.
STMT_VIEW = {"income": "v_income_statement", "balance": "v_balance_sheet",
             "cashflow": "v_cash_flow"}
BASE_METRIC = {"income": "revenue", "cashflow": "revenue", "balance": "total_assets"}
BASE_LABEL = {"income": "% of Revenue", "cashflow": "% of Revenue",
              "balance": "% of Assets"}


def annual_statement(conn, statement, years, metrics):
    """Annual block: {periods, base_series, rows} for one statement."""
    df = pd.read_sql(
        f"SELECT line_order, line_label, fiscal_year, value FROM {STMT_VIEW[statement]}", conn
    )
    rows = []
    for (order, label), g in df.groupby(["line_order", "line_label"]):
        vals = {str(int(r.fiscal_year)): _clean(r.value) for r in g.itertuples()}
        rows.append({"order": int(order), "line": label, "values": vals})
    rows.sort(key=lambda r: r["order"])

    # prev = same period last year (YoY); prevSeq = immediately prior period (QoQ).
    # For annual both are the prior fiscal year.
    periods = []
    for y in years:
        prev = str(y - 1) if (y - 1) in years else None
        periods.append({"key": str(y), "label": f"FY{y}", "prev": prev, "prevSeq": prev})
    bm = BASE_METRIC[statement]
    base_series = {str(y): metrics[y][bm] for y in years}
    return {"periods": periods, "base_series": base_series, "rows": rows}


def quarterly_context(conn):
    """Shared quarterly scaffolding: ordered periods + a period_end->key map.

    Each period carries its fiscal year (fy) and quarter number (q) so the front
    end can offer a year filter and flag which cells are derived (Q4 for income,
    Q2-Q4 for cash flow; balance snapshots are never derived).
    """
    spine = pd.read_sql(
        "SELECT period_end, fiscal_year, qnum, label FROM v_quarter_spine ORDER BY period_end",
        conn,
    )
    pe2key, periods = {}, []
    keyset = {f"{int(r.fiscal_year)}Q{int(r.qnum)}" for r in spine.itertuples()}
    for r in spine.itertuples():
        fy, qn = int(r.fiscal_year), int(r.qnum)
        key = f"{fy}Q{qn}"              # e.g. 2026Q2
        prev = f"{fy - 1}Q{qn}"         # same quarter, prior year
        pe2key[r.period_end] = key
        periods.append({"key": key, "label": r.label, "fy": fy, "q": qn,
                        "prev": (prev if prev in keyset else None)})
    # prevSeq = the immediately preceding quarter in time order (for QoQ growth).
    for i, p in enumerate(periods):
        p["prevSeq"] = periods[i - 1]["key"] if i > 0 else None
    return periods, pe2key


def quarterly_statement(conn, statement, periods, pe2key):
    """Quarterly block. Lines/quarters with no standalone filing stay null."""
    dfl = pd.read_sql(
        "SELECT line_order, line_label, period_end, value "
        f"FROM v_quarterly_statement_lines WHERE statement = '{statement}'", conn
    )
    cell = {}
    for r in dfl.itertuples():
        key = pe2key.get(r.period_end)
        if key:
            cell.setdefault((r.line_order, r.line_label), {})[key] = _clean(r.value)

    # Use the full annual line set so the table shows every line (null where n/a).
    lines = pd.read_sql(
        f"SELECT DISTINCT line_order, line_label FROM {STMT_VIEW[statement]} ORDER BY line_order",
        conn,
    )
    rows = []
    for r in lines.itertuples():
        got = cell.get((int(r.line_order), r.line_label), {})
        vals = {p["key"]: got.get(p["key"]) for p in periods}
        rows.append({"order": int(r.line_order), "line": r.line_label, "values": vals})
    return {"periods": periods, "rows": rows}


def line_series(rows, line):
    """Pull one line's {periodKey: value} from a block's rows."""
    for r in rows:
        if r["line"] == line:
            return dict(r["values"])
    return {}


def wide_dict(conn, view, cols):
    df = pd.read_sql(f"SELECT * FROM {view}", conn)
    out = {}
    for r in df.itertuples():
        out[int(r.fiscal_year)] = {c: _clean(getattr(r, c)) for c in cols}
    return out


# ---------------------------------------------------------------------------
# Narrative insights (derived strictly from the computed numbers)
# ---------------------------------------------------------------------------

def _money_b(v):
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v) / 1e9:,.1f}B"


# Verified public context (not derivable from the filings' headline numbers):
# Apple's Q4-FY2024 results included a one-time income-tax charge from the EU
# State Aid (Ireland) ruling. Used only to contextualize the FY2024 dip.
EU_TAX_CHARGE = 10.2e9
EU_TAX_YEAR = 2024


def build_insights(metrics, ratios, years):
    yrs = sorted(years)
    last, prev, first = yrs[-1], yrs[-2], yrs[0]
    m, r = metrics, ratios

    rev_growth = (m[last]["revenue"] - m[prev]["revenue"]) / m[prev]["revenue"]
    bps = (r[last]["net_margin"] - r[prev]["net_margin"]) * 10000
    income = (
        f"FY{last} revenue of {_money_b(m[last]['revenue'])} grew "
        f"{rev_growth * 100:.1f}% YoY, while net margin "
        f"{'expanded' if bps >= 0 else 'compressed'} {abs(bps):.0f} bps to "
        f"{r[last]['net_margin'] * 100:.1f}%."
    )

    liab_pct = m[last]["total_liabilities"] / m[last]["total_assets"] * 100
    eq_dir = "rose" if m[last]["total_equity"] >= m[prev]["total_equity"] else "fell"
    balance = (
        f"FY{last} total assets of {_money_b(m[last]['total_assets'])} were "
        f"{liab_pct:.0f}% funded by liabilities; shareholders' equity {eq_dir} to "
        f"{_money_b(m[last]['total_equity'])}."
    )

    cfo, capex = m[last]["operating_cf"], m[last]["capex"]
    cashflow = (
        f"FY{last} operating cash flow of {_money_b(cfo)} funded "
        f"{_money_b(capex)} of capex, leaving {_money_b(cfo - capex)} of free cash flow."
    )

    ratios_txt = (
        f"Gross margin reached {r[last]['gross_margin'] * 100:.1f}% in FY{last}, up from "
        f"{r[first]['gross_margin'] * 100:.1f}% in FY{first}; ROE of "
        f"{r[last]['roe'] * 100:.0f}% reflects a small equity base relative to "
        f"{_money_b(m[last]['net_income'])} of net income."
    )

    out = {"income": income, "balance": balance, "cashflow": cashflow, "ratios": ratios_txt}

    # --- Analyst notes (contextual; numbers from the views except the EU charge) ---

    # Income: explain the FY2024 net-income dip and the "return to trend" in FY2025.
    if EU_TAX_YEAR in m:
        ty = EU_TAX_YEAR
        reported_margin = r[ty]["net_margin"] * 100
        norm_margin = (m[ty]["net_income"] + EU_TAX_CHARGE) / m[ty]["revenue"] * 100
        out["income_note"] = (
            f'<span class="tag">Note</span>FY{ty} net income fell to '
            f"{_money_b(m[ty]['net_income'])} despite higher revenue, due to a one-time "
            f"~${EU_TAX_CHARGE / 1e9:.1f}B income-tax charge from the EU State Aid "
            f"(Ireland) ruling. Normalized, FY{ty} net margin was ~{norm_margin:.1f}% "
            f"(vs {reported_margin:.1f}% reported), so part of the FY{last} margin "
            f"expansion is a return to trend."
        )

    # Ratios: clarify the >150% ROE is real, driven by buyback-shrunk equity.
    out["ratios_note"] = (
        f'<span class="tag">Note</span>ROE above 150% is not an error: sustained share '
        f"buybacks have shrunk shareholders' equity to {_money_b(m[last]['total_equity'])}, "
        f"so {_money_b(m[last]['net_income'])} of net income sits on a small equity base."
    )

    # Cash flow: only when investing CF is positive, explain why.
    if m[last]["investing_cf"] is not None and m[last]["investing_cf"] > 0:
        out["cashflow_note"] = (
            f'<span class="tag">Note</span>FY{last} investing cash flow was positive '
            f"({_money_b(m[last]['investing_cf'])}) — not an error. It reflects net "
            f"maturities and sales of Apple's marketable-securities portfolio exceeding "
            f"new purchases and capex."
        )

    return out


# ---------------------------------------------------------------------------
# Variance notes: automatic (magnitude only) + curated (verified causes)
# ---------------------------------------------------------------------------

CASH_CONCEPT = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"


def load_curated():
    """Read data/notes.json -> {'statement|line|period': {explanation, source_url}}."""
    path = config.DATA_DIR / "notes.json"
    if not path.exists():
        return {}
    blob = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for n in blob.get("notes", []):
        key = f"{n['statement']}|{n['line']}|{n['period']}"
        out[key] = {"explanation": n["explanation"], "source_url": n.get("source_url", "")}
    return out


def _qual(dev, thr):
    return ("well above" if dev > 2 * thr else "above") if dev > 0 \
        else ("well below" if dev < -2 * thr else "below")


def _notable_block(blk, s, base_word, dev_thr, skip, same_quarter):
    """Notable items for one block (annual or quarterly). DESCRIPTIVE ONLY.

    Rule A: common-size % deviates from a baseline average. For quarterly the
    baseline is the SAME quarter in other years (avoids seasonality); for annual
    it is the other years. Rule B: a large YoY move (vs same period last year).
    """
    base, periods = blk["base_series"], blk["periods"]
    items, seen = [], set()

    for row in blk["rows"]:
        if row["line"] == skip:
            continue
        pct = {p["key"]: row["values"][p["key"]] / base[p["key"]]
               for p in periods if row["values"].get(p["key"]) is not None and base.get(p["key"])}
        if len(pct) < 3:
            continue
        qof = {p["key"]: p["q"] for p in periods} if same_quarter else None
        for p in periods:
            k = p["key"]
            if k not in pct:
                continue
            if same_quarter:
                peers = [pct[o] for o in pct if o != k and qof[o] == p["q"]]
            else:
                peers = [pct[o] for o in pct if o != k]
            if len(peers) < 1:
                continue
            avg = sum(peers) / len(peers)
            dev = pct[k] - avg
            if abs(dev) > dev_thr:
                avg_word = "same-quarter" if same_quarter else f"{len(peers)}-year"
                items.append({
                    "statement": s, "line": row["line"], "periodKey": k, "period": p["label"],
                    "severity": abs(dev),
                    "text": (f"{row['line']} was {pct[k]*100:.1f}% of {base_word} in "
                             f"{p['label']}, {_qual(dev, dev_thr)} its ~{avg*100:.1f}% {avg_word} average."),
                })
                seen.add((row["line"], k))

    for row in blk["rows"]:
        if row["line"] == skip:
            continue
        for p in periods:
            if not p.get("prev"):
                continue
            v, vp = row["values"].get(p["key"]), row["values"].get(p["prev"])
            if v is None or vp in (None, 0):
                continue
            g = (v - vp) / abs(vp)
            if abs(g) > 0.30 and (row["line"], p["key"]) not in seen:
                items.append({
                    "statement": s, "line": row["line"], "periodKey": p["key"],
                    "period": p["label"], "severity": abs(g) / 10,
                    "text": (f"{row['line']} {'rose' if g >= 0 else 'fell'} "
                             f"{abs(g)*100:.0f}% YoY in {p['label']}."),
                })
                seen.add((row["line"], p["key"]))

    items.sort(key=lambda it: it["severity"], reverse=True)
    return items


def compute_notable(statements, years):
    """Per statement: {annual:[...], quarterly:[...]} of descriptive notable items."""
    base_word = {"income": "revenue", "cashflow": "revenue", "balance": "assets"}
    dev_thr = {"income": 0.015, "cashflow": 0.015, "balance": 0.020}
    skip_line = {"income": "Revenue", "cashflow": None, "balance": "Total Assets"}
    out = {}
    for s in ("income", "balance", "cashflow"):
        annual = _notable_block(statements[s]["annual"], s, base_word[s],
                                dev_thr[s], skip_line[s], same_quarter=False)[:5]
        quarterly = _notable_block(statements[s]["quarterly"], s, base_word[s],
                                   dev_thr[s], skip_line[s], same_quarter=True)[:10]
        out[s] = {"annual": annual, "quarterly": quarterly}
    return out


def compute_bridges(conn, statements, metrics, cash_recon, q_periods, pe2key):
    """Per-period data for the single-period waterfalls (income & cash bridges)."""
    # ---- income bridge: annual (from metrics) + quarterly (from q lines) ----
    inc_annual = {}
    for y in metrics:
        m = metrics[y]
        inc_annual[str(y)] = {
            "rev": m["revenue"], "cogs": m["cogs"], "gp": m["gross_profit"],
            "opex": m["gross_profit"] - m["operating_income"],
            "oi": m["operating_income"], "ni": m["net_income"],
        }
    q_rows = {r["line"]: r["values"] for r in statements["income"]["quarterly"]["rows"]}
    inc_q = {}
    for p in q_periods:
        k = p["key"]
        rev, cogs, gp = q_rows["Revenue"][k], q_rows["Cost of Revenue"][k], q_rows["Gross Profit"][k]
        oi, ni = q_rows["Operating Income"][k], q_rows["Net Income"][k]
        if None in (rev, cogs, gp, oi, ni):
            continue
        inc_q[k] = {"rev": rev, "cogs": cogs, "gp": gp, "opex": gp - oi, "oi": oi, "ni": ni}

    # ---- cash bridge: annual (from cash_recon) + quarterly (standalone qtrs) ----
    cash_annual = {}
    for y, c in cash_recon.items():
        cash_annual[str(y)] = {
            "beg": c["beginning_cash"], "cfo": c["operating_cf"], "cfi": c["investing_cf"],
            "cff": c["financing_cf"], "end": c["reported_ending_cash"],
        }
    # quarter-end cash anchor (instant), latest-filed per date
    ends = pd.read_sql(
        "SELECT period_end, value, filed FROM facts "
        f"WHERE concept = '{CASH_CONCEPT}' AND period_start IS NULL", conn
    )
    ends = ends.sort_values("filed").drop_duplicates("period_end", keep="last")
    end_cash = {r.period_end: float(r.value) for r in ends.itertuples()}
    key2pe = {k: pe for pe, k in pe2key.items()}
    cf_rows = {r["line"]: r["values"] for r in statements["cashflow"]["quarterly"]["rows"]}
    cash_q = {}
    for p in q_periods:
        k = p["key"]
        cfo, cfi, cff = cf_rows["Operating Cash Flow"][k], cf_rows["Investing Cash Flow"][k], cf_rows["Financing Cash Flow"][k]
        end = end_cash.get(key2pe.get(k))
        if None in (cfo, cfi, cff) or end is None:
            continue                              # standalone quarter not filed -> skip
        cash_q[k] = {"beg": end - (cfo + cfi + cff), "cfo": cfo, "cfi": cfi, "cff": cff, "end": end}

    return {
        "income": {"annual": inc_annual, "quarterly": inc_q},
        "cash": {"annual": cash_annual, "quarterly": cash_q},
    }


# ---------------------------------------------------------------------------
# Assemble + render
# ---------------------------------------------------------------------------

def build_data(conn):
    metric_cols = [
        "revenue", "cogs", "gross_profit", "operating_income", "net_income",
        "total_assets", "current_assets", "cash", "total_liabilities",
        "current_liabilities", "total_equity", "operating_cf", "investing_cf",
        "financing_cf", "capex",
    ]
    ratio_cols = ["gross_margin", "operating_margin", "net_margin", "roe",
                  "current_ratio", "free_cash_flow"]
    recon_cols = ["beginning_cash", "operating_cf", "investing_cf", "financing_cf",
                  "computed_ending_cash", "reported_ending_cash"]

    metrics = wide_dict(conn, "v_metrics", metric_cols)
    ratios = wide_dict(conn, "v_ratios", ratio_cols)
    cash_recon = wide_dict(conn, "v_cash_reconciliation", recon_cols)
    years = sorted(metrics.keys())

    # --- Build the spreadsheet statements (annual + quarterly) ---
    q_periods, pe2key = quarterly_context(conn)
    statements = {}
    quarterly_blocks = {
        s: quarterly_statement(conn, s, q_periods, pe2key)
        for s in ("income", "balance", "cashflow")
    }
    # Base series for common-size: revenue (income/cashflow) and assets (balance).
    q_revenue = line_series(quarterly_blocks["income"]["rows"], "Revenue")
    q_assets = line_series(quarterly_blocks["balance"]["rows"], "Total Assets")
    q_base = {"income": q_revenue, "cashflow": q_revenue, "balance": q_assets}

    for s in ("income", "balance", "cashflow"):
        annual = annual_statement(conn, s, years, metrics)
        quarterly = quarterly_blocks[s]
        quarterly["base_series"] = q_base[s]
        statements[s] = {
            "base_label": BASE_LABEL[s],
            "annual": annual,
            "quarterly": quarterly,
        }

    # --- Ratios table (annual): label / key / format / values per year ---
    ratio_defs = [
        ("Gross Margin", "gross_margin", "pct"),
        ("Operating Margin", "operating_margin", "pct"),
        ("Net Margin", "net_margin", "pct"),
        ("Return on Equity", "roe", "pct"),
        ("Current Ratio", "current_ratio", "x"),
        ("Free Cash Flow", "free_cash_flow", "money"),
    ]
    ratios_table = {
        "periods": [{"key": str(y), "label": f"FY{y}",
                     "prev": (str(y - 1) if (y - 1) in years else None)} for y in years],
        "rows": [
            {"label": lbl, "key": key, "fmt": fmt,
             "values": {str(y): ratios[y][key] for y in years}}
            for lbl, key, fmt in ratio_defs
        ],
    }

    notable = compute_notable(statements, years)
    curated = load_curated()
    bridges = compute_bridges(conn, statements, metrics, cash_recon, q_periods, pe2key)

    # Revision log: snapshot displayed values, detect restatements vs last run.
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot = revmod.current_snapshot(statements)
    revisions = revmod.update_revisions(snapshot, run_date, config.DATA_DIR / "revisions.json")

    data = {
        "meta": {
            "ticker": config.COMPANY["ticker"],
            "entity": config.COMPANY["entity_name"],
        },
        "years": years,
        "metrics": metrics,
        "ratios": ratios,
        "cash_recon": cash_recon,
        "statements": statements,
        "ratios_table": ratios_table,
        "quarter_years": sorted({p["fy"] for p in q_periods}, reverse=True),
        # Fiscal years with fewer than 4 filed quarters (in progress / YTD).
        "quarter_partial": sorted(
            {fy for fy in {p["fy"] for p in q_periods}
             if sum(1 for p in q_periods if p["fy"] == fy) < 4},
            reverse=True),
        "bridges": bridges,
        "notable": notable,
        "curated": curated,
        "revisions": revisions,
    }
    insights = build_insights(metrics, ratios, years)
    return data, insights, years


def render(data, insights, years):
    template = (TEMPLATE_DIR / "dashboard_template.html").read_text(encoding="utf-8")
    js = (TEMPLATE_DIR / "dashboard.js").read_text(encoding="utf-8")

    entity = config.COMPANY["entity_name"]
    ticker = config.COMPANY["ticker"]
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"{entity} ({ticker}) — Automated 3-Statement Dashboard"
    subtitle = (
        f"Data: SEC EDGAR XBRL (companyfacts) · FY{years[0]}–FY{years[-1]} · "
        f"auto-updated weekly · Last updated {updated}"
    )

    html = (
        template
        .replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__TICKER__", ticker)
        .replace("__REPO_URL__", config.REPO_URL)
        .replace("__DATA__", json.dumps(data))
        .replace("__INSIGHTS__", json.dumps(insights))
        .replace("__DASHBOARD_JS__", js)
    )
    config.HTML_OUT.write_text(html, encoding="utf-8")
    return config.HTML_OUT


def main():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        build_views(conn)
        data, insights, years = build_data(conn)
    finally:
        conn.close()

    out = render(data, insights, years)
    size_kb = out.stat().st_size / 1024
    print(f"Dashboard written: {out}  ({size_kb:.0f} KB)")
    print(f"  Open it with a double-click, or run:  start {out}")


if __name__ == "__main__":
    main()
