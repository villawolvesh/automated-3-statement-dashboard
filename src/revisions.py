"""
Revision log: detect when SEC restates a previously reported figure.

Each run snapshots the displayed annual values to data/revisions.json. On the
next run, any value that differs from the stored snapshot (beyond a tiny
rounding tolerance) is a restatement -- we append a {old, new, date} record and
the dashboard flags that cell ("revised from X to Y on DATE").

The pipeline already keeps the most recently FILED version of every figure
(v_annual_facts picks ROW_NUMBER ... ORDER BY filed DESC), so "new" is always
EDGAR's latest number; this log simply remembers what it used to be.
"""

import json
from pathlib import Path


def current_snapshot(statements):
    """Flatten displayed annual values -> {"statement|line|FYxxxx": value}."""
    snap = {}
    for s, st in statements.items():
        blk = st["annual"]
        for r in blk["rows"]:
            for p in blk["periods"]:
                v = r["values"].get(p["key"])
                if v is not None:
                    snap[f"{s}|{r['line']}|{p['label']}"] = v
    return snap


def update_revisions(snapshot, run_date, path: Path):
    """Compare to the stored snapshot, record changes, persist, return latest map."""
    store = (json.loads(path.read_text(encoding="utf-8"))
             if path.exists() else {"snapshot": {}, "revisions": []})
    prev = store.get("snapshot", {})
    revs = store.get("revisions", [])

    for key, value in snapshot.items():
        if key in prev:
            old = prev[key]
            # EDGAR figures are exact integers; tolerate only float noise.
            if abs(old - value) > max(1000.0, abs(old) * 0.0005):
                revs.append({"key": key, "old": old, "new": value, "date": run_date})

    store["snapshot"] = snapshot
    store["revisions"] = revs
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    latest = {}
    for rec in revs:           # later records win -> most recent revision per cell
        latest[rec["key"]] = rec
    return latest
