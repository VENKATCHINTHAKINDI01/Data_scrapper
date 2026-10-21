"""Step 6 — extract candidate relationships from the Read-list and the order text.

  python tools/extract_relations.py staging
  python tools/extract_relations.py seed/mock-v1 --compare seed/mock-v1/ground-truth/relations.csv

Output:
  <root>/manifests/relations.jsonl   one candidate edge per line (status: candidate)
  <root>/manifests/missing.txt       cited orders not yet in the corpus -> collect them next
Vocabulary (CLAUDE.md §5.7): SUPERSEDES, AMENDS, CLARIFIES, REPEALS, REFERENCES.
SUPERSEDED_BY is derived later in the graph, not extracted here.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import GO_REF, MEMO_REF, SO_REF, load_scope, normalize_ocr, parse_reference, read_list, write_json  # noqa: E402

ORD = re.compile(r"(\d{1,2})\s*(?:st|nd|rd|th)", re.I)
FILE_REF = re.compile(r"file\s+No\.?\s*([A-Z0-9][A-Z0-9()\-.]*/\d+/\d{4}-[A-Z.]+[A-Z])", re.I)
POINTERS = ("read above", "cited")
# Strict phrasings: the keyword must say what THIS order does, not what the cited document did.
# ("GoI have issued the following clarifications" or "the following amendments have been issued to
#  the Act" describe the reference; they are REFERENCES, not CLARIFIES/AMENDS.)
KEYWORDS = [("SUPERSEDES", r"in\s+supersession\s+of"),
            ("REPEALS", r"hereby\s+(?:cancel|rescind|withdraw)|(?:is|are)\s+hereby\s+(?:cancelled|rescinded|withdrawn)"),
            ("AMENDS", r"hereby\s+(?:issue|make)s?\s+the\s+following\s+amendments?|following\s+amendments?\s+(?:is|are)\s+"
                       r"(?:hereby\s+)?(?:issued|made)|hereby\s+amend|(?:in\s+)?partial\s+modification\s+of|in\s+modification\s+of"),
            ("CLARIFIES", r"following\s+clarifications?\s+(?:is|are)\s+(?:hereby\s+)?issued|hereby\s+clarif")]
# "In the reference 1st read above, orders WERE issued ... in supersession of ..." describes the reference itself
DESCRIBES = re.compile(r"\b(?:were|was|have|has|had)\s+(?:been\s+)?issued\b|\bhave\s+been\s+(?:made|notified)\b", re.I)


ABBR = [("G.O.", "G\u2024O\u2024"), ("Ms.", "Ms\u2024"), ("MS.", "MS\u2024"), ("Rt.", "Rt\u2024"), ("No.", "No\u2024"), ("Dt.", "Dt\u2024"), ("Lr.", "Lr\u2024"), ("Rs.", "Rs\u2024")]


def sentences(text: str):
    t = re.sub(r"\s+", " ", text)
    for a, b in ABBR:                       # keep "G.O. 1st read above" in one sentence
        t = t.replace(a, b)
    return [x for x in re.split(r"(?<=[.;])\s+(?=[A-Z0-9(])", t)]


def ref_line(text: str) -> list[str]:
    """Memos often carry a single 'Ref:' line instead of a Read-list."""
    m = re.search(r"^\s*Ref\s*:\s*(.+)$", text, re.M | re.I)
    return [m.group(1).strip()] if m else []


def relations_for(meta: dict, text: str, scope: dict, files: dict | None = None) -> list[dict]:
    me, dept = meta["canonical_id"], meta.get("department_code")
    text = normalize_ocr(text)
    items = read_list(text) or meta.get("read_list") or ref_line(text)
    items = [i for i in items if len(re.findall(r"[A-Za-z]{3,}", i)) >= 2]
    refs = [parse_reference(i, dept, scope) or {"raw": i, "canonical_id": None} for i in items]
    rel = {i: "REFERENCES" for i in range(len(refs))}
    evidence = {i: f"Read {i + 1}" for i in range(len(refs))}
    inline = []
    for s in sentences(text):
        if DESCRIBES.search(s):
            continue
        for kind, pat in KEYWORDS:
            km = re.search(pat, s, re.I)
            if not km:
                continue
            after = s[km.end():]
            pm = re.search(r"read\s+above|cited", after, re.I)
            if pm and pm.start() < 160:
                # keyword ... the orders issued in the reference Nth read above
                seg = after[:pm.start()][-80:]
                idx = [int(o) - 1 for o in ORD.findall(seg)] or ([0] if len(refs) == 1 else [])
                for i in idx:
                    if 0 <= i < len(refs) and rel[i] == "REFERENCES":
                        rel[i], evidence[i] = kind, s.strip()[:220]
            else:
                # keyword ... names the order directly: "in supersession of ... G.O.Ms.No.196, Finance ..., dt..."
                gm = GO_REF.search(after[:220].replace("\u2024", "."))
                if gm:
                    r = parse_reference(gm.group(0), dept, scope)
                    if r and r["canonical_id"] and r["canonical_id"] != me:
                        inline.append({"from": me, "to": r["canonical_id"], "to_raw": r["raw"], "type": kind,
                                       "evidence": s.strip()[:220], "status": "candidate", "source": "inline"})
            break
    # single-reference memos/amendments: fall back to the document's own subject
    # only for documents whose own type says so (an Amendment G.O., a Clarification memo) with one reference
    dtype = str(meta.get("doc_type") or "")
    subj = str(meta.get("subject") or "")
    if len(refs) == 1 and rel[0] == "REFERENCES" and dtype in ("Amendment", "Clarification"):
        for kind, word in (("CLARIFIES", r"clarification"), ("AMENDS", r"amendment")):
            if re.search(word, dtype, re.I):
                rel[0], evidence[0] = kind, f"subject: {subj.strip()[:120]}"
                break
    out = inline + [{"from": me, "to": r["canonical_id"], "to_raw": r["raw"], "type": rel[i],
            "evidence": evidence[i], "status": "candidate", "source": "read_list"} for i, r in enumerate(refs)]
    # e-file notes and orders without a Read-list: any inline citation is a REFERENCES candidate
    if not items:
        seen = set()
        for m in list(GO_REF.finditer(text)) + list(MEMO_REF.finditer(text)) + list(SO_REF.finditer(text)):
            r = parse_reference(m.group(0), dept, scope)
            if r and r["canonical_id"] and r["canonical_id"] != me and r["canonical_id"] not in seen:
                seen.add(r["canonical_id"])
                out.append({"from": me, "to": r["canonical_id"], "to_raw": r["raw"], "type": "REFERENCES",
                            "evidence": "inline citation", "status": "candidate", "source": "inline"})
        for fno in FILE_REF.findall(text):           # note -> another e-file
            target = (files or {}).get(fno.upper())
            if target and target != me and target not in seen:
                seen.add(target)
                out.append({"from": me, "to": target, "to_raw": f"file No.{fno}", "type": "REFERENCES",
                            "evidence": "file reference", "status": "candidate", "source": "inline"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--compare", help="ground-truth relations.csv (from_canonical, relation, to_canonical_or_raw)")
    a = ap.parse_args()
    root, scope = pathlib.Path(a.root), load_scope()
    ids, edges = set(), []
    metas = sorted((root / "rule-library").rglob("meta.json"))
    for p in metas:
        ids.add(json.loads(p.read_text())["canonical_id"])
    for p in metas:
        m = json.loads(p.read_text())
        ocr = p.parent / (m.get("files", {}).get("ocr") or "ocr.txt")
        edges += relations_for(m, ocr.read_text(errors="ignore") if ocr.exists() else "", scope)
        if m.get("republishes_id"):   # gazette that publishes a G.O. (and the rules it issues)
            edges.append({"from": m["canonical_id"], "to": m["republishes_id"], "to_raw": m.get("republishes"),
                          "type": "REFERENCES", "evidence": "gazette publishes this G.O.", "status": "candidate",
                          "source": "gazette_republishes"})
    # e-file notes cite orders and other files
    efs = sorted((root / "efiles").rglob("file.json"))
    files = {}
    for fj in efs:
        f = json.loads(fj.read_text())
        files[f["file_no"].upper()] = f.get("canonical_id") or f["file_no"]
        ids.add(files[f["file_no"].upper()])
    for fj in efs:
        f = json.loads(fj.read_text())
        text = "\n".join(n.read_text() for n in sorted(fj.parent.glob("Note File*/note-*.md")))
        stub = {"canonical_id": f.get("canonical_id") or f["file_no"], "department_code": f["department_code"], "read_list": []}
        edges += relations_for(stub, text, scope, files)

    out = root / "manifests" / "relations.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in edges))
    missing = sorted({e["to"] or f"UNRESOLVED: {e['to_raw']}" for e in edges if e["to"] not in ids})
    (root / "manifests" / "missing.txt").write_text("\n".join(missing) + ("\n" if missing else ""))
    by = {}
    for e in edges:
        by[e["type"]] = by.get(e["type"], 0) + 1
    print(f"{len(edges)} candidate edges from {len(metas)} documents: {by}")
    print(f"{len(missing)} cited items not in corpus -> manifests/missing.txt")

    if a.compare:
        gt = set()
        with open(a.compare) as f:
            for r in csv.DictReader(f):
                rel = {"CITES": "REFERENCES"}.get(r["relation"], r["relation"])   # mock v1 used CITES for note->order
                if rel in ("SUPERSEDES", "AMENDS", "CLARIFIES", "REPEALS", "REFERENCES") and r.get("to_id"):
                    gt.add((r["from_canonical"], rel, r["to_canonical_or_raw"]))
        nd = lambda x: re.sub(r"-D\d{8}$", "", x or "")    # mock v1 ground truth predates memo date tags
        gt = {(nd(a), b, nd(c)) for a, b, c in gt}
        got = {(nd(e["from"]), e["type"], nd(e["to"])) for e in edges if e["to"]}
        gt_from = {g[0] for g in gt}
        got_scoped = {g for g in got if g[0] in gt_from}
        tp = got_scoped & gt
        p = len(tp) / len(got_scoped) if got_scoped else 0
        r = len(tp) / len(gt) if gt else 0
        print(f"\nvs ground truth: precision {p:.0%}  recall {r:.0%}  ({len(tp)}/{len(gt)} matched)")
        for g in sorted(gt - got):
            print("  missed :", *g)
        for g in sorted(got_scoped - gt):
            print("  extra  :", *g)
        write_json(root / "manifests" / "relations_eval.json",
                   {"precision": p, "recall": r, "missed": sorted(gt - got), "extra": sorted(got_scoped - gt)})


if __name__ == "__main__":
    main()
