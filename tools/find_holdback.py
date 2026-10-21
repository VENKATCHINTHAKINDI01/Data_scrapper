"""Pick orders to hold back for the live demo ("a new G.O. arrives -> the system flags open files citing the old one").

  python tools/find_holdback.py                 # list candidates (late-2025 orders that supersede/amend an order we hold)
  python tools/find_holdback.py --move AP-FIN01-GOMS-NN-2025   # move one to staging/holdback/ and record it in scope.yaml

A good candidate: dated in the last months before the as-of date, SUPERSEDES or AMENDS an order we hold, and that
older order is cited by at least one synthetic e-file (so the demo has open files to flag).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import ROOT, STAGING, load_scope  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-07-01", help="only orders dated on/after this")
    ap.add_argument("--move", help="canonical ID to hold back")
    a = ap.parse_args()
    metas = {}
    for m in (STAGING / "rule-library").rglob("meta.json"):
        j = json.loads(m.read_text()); j["_dir"] = m.parent; metas[j["canonical_id"]] = j
    rel = STAGING / "manifests" / "relations.jsonl"
    edges = [json.loads(l) for l in rel.read_text().splitlines()] if rel.exists() else []
    cited_by_efiles = {}
    for fj in (STAGING / "efiles").rglob("file.json"):
        f = json.loads(fj.read_text())
        for c in f.get("cites", []):
            cited_by_efiles.setdefault(c, []).append(f["file_no"])

    if a.move:
        if a.move not in metas:
            sys.exit(f"{a.move} not in staging/rule-library")
        src = metas[a.move]["_dir"]
        dst = STAGING / "holdback" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        sp = ROOT / "scope.yaml"
        txt = sp.read_text()
        import re
        cur = re.search(r"demo_holdback: \[(.*?)\]", txt).group(1)
        items = [x.strip() for x in cur.split(",") if x.strip()] + [a.move]
        txt = re.sub(r"demo_holdback: \[.*?\]", "demo_holdback: [" + ", ".join(dict.fromkeys(items)) + "]", txt)
        sp.write_text(txt)
        print(f"moved {a.move} -> {dst.relative_to(ROOT)}; recorded in scope.yaml demo_holdback.\n"
              f"Re-run: python tools/extract_relations.py staging")
        return

    rows = []
    for e in edges:
        if e["type"] not in ("SUPERSEDES", "AMENDS") or e["from"] not in metas or e.get("to") not in metas:
            continue
        new = metas[e["from"]]
        if str(new.get("date", "")) < a.since:
            continue
        rows.append((new["date"], e["from"], e["type"], e["to"], len(cited_by_efiles.get(e["to"], [])),
                     str(new.get("subject"))[:90]))
    if not rows:
        print(f"No orders dated on/after {a.since} that supersede/amend an order we hold yet.\n"
              f"Collect 2025 first (bash tools/run_batches.sh), then run this again; or use --since 2025-01-01.")
        return
    print(f"{'date':<11} {'new order':<24} {'type':<10} {'older order':<24} e-files citing older | subject")
    for r in sorted(rows, key=lambda x: (-x[4], x[0]), reverse=False):
        print(f"{r[0]:<11} {r[1][3:]:<24} {r[2]:<10} {r[3][3:]:<24} {r[4]:<20} | {r[5]}")
    print("\nPrefer a row with e-files citing the older order (or we generate 2–3 e-files that cite it).")


if __name__ == "__main__":
    main()
