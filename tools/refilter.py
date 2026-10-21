"""Re-apply the current topic filter to orders already in staging.

Orders kept by topic (collected_via == "topic") that the current scope.yaml would now reject are MOVED (never
deleted) to staging/_review/refiltered/<dept>/<id>/ with a reason.txt. Cited orders are never moved.
Run extract_relations.py and validate.py afterwards.

  python tools/refilter.py            # list what would move (dry run)
  python tools/refilter.py --move     # move them
"""
import argparse, json, shutil
from pathlib import Path
from common import load_scope, topic_decision

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "staging" / "rule-library"
OUT = ROOT / "staging" / "_review" / "refiltered"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--move", action="store_true")
    a = ap.parse_args()
    scope = load_scope()
    n_seen = n_out = 0
    for meta in sorted(LIB.rglob("meta.json")):
        m = json.loads(meta.read_text())
        if m.get("collected_via") != "topic":
            continue
        n_seen += 1
        ok, why = topic_decision(m.get("subject") or "", scope)
        if ok:
            continue
        n_out += 1
        cid = m.get("canonical_id")
        print(f"{'MOVE' if a.move else 'would move'}: {cid}  ({why})  {(m.get('subject') or '')[:80]}")
        if a.move:
            dest = OUT / (m.get("department_code") or "UNK") / meta.parent.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(meta.parent), str(dest))
            (dest / "reason.txt").write_text(f"refiltered: {why}\n")
    print(f"\ntopic-kept orders checked: {n_seen} | {'moved' if a.move else 'would move'}: {n_out}")
    if a.move and n_out:
        print("next: python tools/extract_relations.py staging && python tools/validate.py staging")

if __name__ == "__main__":
    main()
