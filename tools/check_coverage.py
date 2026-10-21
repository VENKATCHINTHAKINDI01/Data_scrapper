"""Coverage check — does the collected data cover what C2-24 needs? No downloads.

  python tools/check_coverage.py              # staging (real) + seed (synthetic)
Writes notes/coverage.md.

Each line answers one need from the plan ("What C2-24 needs" + the seven conflict types) with
PASS / PARTIAL / GAP, the evidence found, and where the missing part has to come from.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import ROOT, normalize_ocr, read_list  # noqa: E402


def load(root: pathlib.Path):
    docs = {}
    for m in root.glob("rule-library/**/meta.json"):
        j = json.loads(m.read_text())
        ocr = m.parent / (j.get("files", {}).get("ocr") or "ocr.txt")
        j["_ocr"] = ocr.read_text(errors="ignore") if ocr.exists() else ""
        docs[j["canonical_id"]] = j
    rel = root / "manifests" / "relations.jsonl"
    edges = [json.loads(l) for l in rel.read_text().splitlines()] if rel.exists() else []
    return docs, edges


def typ(cid: str) -> str:
    return cid.split("-")[2]


def main():
    st, sd = ROOT / "staging", ROOT / "seed" / "mock-v1"
    docs, edges = load(st)
    ids = set(docs)
    rows = []

    def row(need, status, evidence, source):
        rows.append((need, status, evidence, source))

    ms = [d for d in docs if typ(d) == "GOMS"]
    rt = [d for d in docs if typ(d) == "GORT"]
    row("G.O.(Ms) rule library", "PASS" if len(ms) >= 20 else "PARTIAL", f"{len(ms)} orders",
        "Internet Archive mirror (automatic)")
    row("G.O.(Rt) orders", "PASS" if rt else "GAP", f"{len(rt)} (only fetched when cited)", "Internet Archive (--cited)")

    with_read = [d for d, j in docs.items() if re.search(r"read\s+the\s+following", j["_ocr"], re.I)]
    parsed = [d for d in with_read if read_list(normalize_ocr(docs[d]["_ocr"]))]
    pct = len(parsed) / len(with_read) if with_read else 0
    row("Read-list parsed from OCR", "PASS" if pct >= .9 else "PARTIAL",
        f"{len(parsed)}/{len(with_read)} orders that have a Read-list ({pct:.0%})", "tools (extract_relations)")

    resolved = [e for e in edges if e.get("to")]
    inside = [e for e in resolved if e["to"] in ids]
    unresolved = [e for e in edges if not e.get("to")]
    row("Citations resolved to orders we hold", "PASS" if inside and len(inside) / max(len(resolved), 1) >= .6 else "PARTIAL",
        f"{len(inside)}/{len(resolved)} resolvable citations point inside the corpus; {len(unresolved)} unresolvable "
        f"(other depts / GoI memos / Acts)", "--cited (depth 1) + hand downloads")

    sup = [e for e in edges if e["type"] == "SUPERSEDES" and e.get("to") in ids]
    row("Supersession chains (conflict A)", "PASS" if len(sup) >= 3 else ("PARTIAL" if sup else "GAP"),
        f"{len(sup)} SUPERSEDES links with both orders held: " + ", ".join(f"{e['from'][3:]}→{e['to'][3:]}" for e in sup[:4]),
        "Internet Archive; synthetic e-files add more")
    am = [e for e in edges if e["type"] == "AMENDS" and e.get("to") in ids]
    row("Amendments", "PASS" if am else "PARTIAL", f"{len(am)} AMENDS links with both orders held", "Internet Archive")

    rate = sorted((j["date"], d) for d, j in docs.items()
                  if re.search(r"dearness|\bDA\b|\bDR\b", str(j.get("subject")), re.I))
    row("Rate series over time (conflict F)", "PASS" if len(rate) >= 3 else ("PARTIAL" if rate else "GAP"),
        f"{len(rate)} DA/DR orders: " + ", ".join(d[3:] for _, d in rate[:5]),
        "Internet Archive (dearness topic) + PAG (A&E) AP page by hand")

    high = [d for d, j in docs.items() if (j.get("hierarchy_level") or 9) <= 3]
    row("Rules / Acts / Gazette above G.O.s (conflict G)", "PASS" if high else "GAP", f"{len(high)} documents",
        "Internet Archive `--kind gazette` (2 to test) + APeGAZETTE by hand")

    memos = [d for d in docs if typ(d) in ("CIRMEMO", "MEMO", "RC")]
    row("Circulars / memos (conflict C)", "PASS" if memos else "GAP", f"{len(memos)} memos",
        "Not in the mirror — AP Finance site, APUTF memos page, GOIR by hand")

    depts = sorted({j["department_code"] for j in docs.values()})
    row("More than one department", "PASS" if len(depts) >= 2 else "GAP", ", ".join(
        f"{x}: {sum(1 for j in docs.values() if j['department_code'] == x)}" for x in depts),
        "run tools/run_batches.sh for FIN01, GAD01, ESE01")

    y26 = [d for d, j in docs.items() if str(j.get("date", "")) >= "2026"]
    row("2026 orders (latest rules)", "PASS" if y26 else "GAP", f"{len(y26)}; mirror ends 2025-12-12",
        "APUTF Latest GOs + GOIR by hand")

    good = [d for d, j in docs.items() if len(j["_ocr"]) >= 500]
    row("OCR text present", "PASS" if len(good) == len(docs) else "PARTIAL", f"{len(good)}/{len(docs)} with ≥500 chars",
        "archive.org _djvu.txt")

    meta_ok = [d for d, j in docs.items() if j.get("section") and j.get("subject") and j.get("date")]
    row("Metadata (date, section, subject)", "PASS" if len(meta_ok) == len(docs) else "PARTIAL",
        f"{len(meta_ok)}/{len(docs)}", "archive description")

    review = sorted(p.name for p in (st / "_review").iterdir() if p.is_dir()) if (st / "_review").exists() else []
    row("Records needing review", "PASS" if not review else "PARTIAL", f"{len(review)}: " + ", ".join(review[:4]),
        "GOIR by hand (no PDF in mirror / duplicate numbers)")

    # e-Office layer: never public — synthetic seed
    roots = (st, sd)
    g = lambda pat: [p for r in roots for p in r.glob(pat)]
    ef = g("efiles/**/file.json")
    notes = g("efiles/**/Note File*/note-*.md")
    rec = [p for p in g("efiles/**/Correspondence/*") if p.name != "README.md"]
    dfa = g("efiles/**/Drafts/DFA-*.md")
    lnk = [p for p in g("efiles/**/links.json") if json.loads(p.read_text())]
    mov = [p for p in g("efiles/**/movements.json") if json.loads(p.read_text())]
    gtp = st / "ground-truth" / "efiles_conflicts.json"
    gts = json.loads(gtp.read_text()) if gtp.exists() else []
    row("e-Office files + notes (synthetic)", "PASS" if ef and notes else "GAP", f"{len(ef)} files, {len(notes)} notes (seed + generated)",
        "Not public — synthetic (seed now, Step 8 generator)")
    row("Receipts / drafts / links (synthetic)", "PASS" if rec and dfa else "GAP",
        f"{len(rec)} receipts, {len(dfa)} drafts, {len(lnk)} files with links", "Not public — Step 8 generator")
    kinds = sorted({x["type"] for x in gts})
    row("Planted conflicts on real orders (synthetic e-files)", "PASS" if len(kinds) >= 3 else ("PARTIAL" if gts else "GAP"),
        f"{len(gts)} planted, types {', '.join(kinds)}; B/C/E/G still only in mock seed", "generate_efiles.py")
    row("Movements (synthetic)", "PASS" if mov else "GAP", f"{len(mov)} files with movements", "Not public — synthetic")
    offs = [r / "directory" / "officers.json" for r in roots if (r / "directory" / "officers.json").exists()]
    row("Officers, sections, access scopes (synthetic)", "PASS" if offs else "GAP",
        " + ".join(f"{len(json.loads(o.read_text()))} ({o.parent.parent.name})" for o in offs), "Not public — synthetic")

    w = max(len(r[0]) for r in rows)
    for need, status, ev, src in rows:
        print(f"{status:<8} {need:<{w}}  {ev[:90]}")
    md = ["# Coverage check", "", f"Real documents in staging: {len(docs)}  ·  links: {len(edges)}", "",
          "| Need | Status | Evidence | Where the rest comes from |", "|---|---|---|---|"]
    md += [f"| {a} | {b} | {c.replace('|', '/')} | {d} |" for a, b, c, d in rows]
    (ROOT / "notes" / "coverage.md").write_text("\n".join(md) + "\n")
    print("\nwritten notes/coverage.md")


if __name__ == "__main__":
    main()
