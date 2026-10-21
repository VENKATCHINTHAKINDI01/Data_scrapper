"""Step 5 — validate a corpus root before upload.

  python tools/validate.py staging            # real collected data
  python tools/validate.py seed/mock-v1       # synthetic seed

Checks every rule-library meta.json and every e-file file.json. Exit code 1 if anything fails.
Writes <root>/manifests/validation_report.json.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import CANONICAL_RE, META_REQUIRED, sha256, write_json  # noqa: E402

CLASSIFICATIONS = ["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET"]   # CSMOP order


def readable(path: pathlib.Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    head = path.read_bytes()[:8]
    if path.suffix == ".pdf":
        if not head.startswith(b"%PDF"):
            return False
        try:
            from pypdf import PdfReader
            return len(PdfReader(str(path)).pages) > 0
        except ImportError:
            return True
        except Exception:
            return False
    if path.suffix in (".jpg", ".jpeg"):
        return head[:3] == b"\xff\xd8\xff"
    if path.suffix in (".docx", ".xlsx"):
        return head[:2] == b"PK"
    return True


def check_doc(meta_path: pathlib.Path, seen: dict) -> list[str]:
    errs = []
    m = json.loads(meta_path.read_text())
    d = meta_path.parent
    for k in META_REQUIRED:
        if m.get(k) in (None, "", []):
            errs.append(f"missing {k}")
    cid = m.get("canonical_id", "")
    if not CANONICAL_RE.match(cid or ""):
        errs.append(f"canonical_id not in AP-<DEPT>-<TYPE>-<NUMBER>-<YEAR> form: {cid}")
    if d.name != cid:
        errs.append(f"folder name {d.name} != canonical_id")
    if cid in seen["ids"]:
        errs.append(f"duplicate canonical_id (also {seen['ids'][cid]})")
    seen["ids"][cid] = str(d)
    orig = d / (m.get("files", {}).get("original") or "order.pdf")
    if not readable(orig):
        errs.append(f"original unreadable: {orig.name}")
    else:
        h = sha256(orig)
        if m.get("sha256") and m["sha256"] != h:
            errs.append("sha256 mismatch (file changed after registration)")
        if h in seen["hashes"]:
            errs.append(f"same bytes as {seen['hashes'][h]}")
        seen["hashes"][h] = cid
    ocr = d / (m.get("files", {}).get("ocr") or "ocr.txt")
    if not ocr.exists() or len(ocr.read_text(errors="ignore").strip()) < 50:
        errs.append("ocr.txt missing or nearly empty")
    if m.get("classification") not in CLASSIFICATIONS:
        errs.append(f"classification {m.get('classification')} not in CSMOP set")
    url = str(m.get("source_url") or "")
    if m.get("origin") == "public" and url.rstrip("/").count("/") < 3:
        errs.append("source_url is a homepage, not the document")
    if m.get("origin") not in ("public", "synthetic"):
        errs.append("origin must be public or synthetic")
    if m.get("date") and m.get("date")[:4] != d.parent.name:
        errs.append(f"year folder {d.parent.name} != date {m.get('date')}")
    return errs


def check_efile(fj: pathlib.Path) -> list[str]:
    errs = []
    f = json.loads(fj.read_text())
    for k in ["file_no", "computer_no", "subject", "department_code", "section", "classification", "origin"]:
        if not f.get(k):
            errs.append(f"missing {k}")
    if f.get("origin") != "synthetic":
        errs.append("e-files must be origin: synthetic")
    if f.get("classification") not in CLASSIFICATIONS:
        errs.append("bad classification")
    notes = list((fj.parent).glob("Note File*/note-*.md"))
    if not notes:
        errs.append("no notes under Note File*/")
    for n in notes:
        if "SYNTHETIC" not in n.read_text()[:200]:
            errs.append(f"{n.name} lacks the SYNTHETIC banner")
    for name in ("movements.json", "links.json"):
        if not (fj.parent / name).exists():
            errs.append(f"missing {name}")
    return errs


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "staging")
    seen = {"ids": {}, "hashes": {}}
    report = {"root": str(root), "documents": {}, "efiles": {}}
    docs = sorted((root / "rule-library").rglob("meta.json"))
    efiles = sorted((root / "efiles").rglob("file.json"))
    for p in docs:
        e = check_doc(p, seen)
        report["documents"][str(p.parent.relative_to(root))] = e
    for p in efiles:
        e = check_efile(p)
        report["efiles"][str(p.parent.relative_to(root))] = e
    bad = {k: v for part in ("documents", "efiles") for k, v in report[part].items() if v}
    for k, v in bad.items():
        print(f"FAIL {k}\n      - " + "\n      - ".join(v))
    print(f"\nchecked {len(docs)} documents and {len(efiles)} e-files: {len(bad)} with problems")
    write_json(root / "manifests" / "validation_report.json", report)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
