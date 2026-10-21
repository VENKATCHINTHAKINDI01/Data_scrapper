"""Register a PDF you downloaded by hand (APUTF, PAG, AP Finance, APeGAZETTE, GOIR, circulars).

1. Save the PDF into inbox/
2. Run, giving the page URL you downloaded it from:

  python tools/add_manual.py inbox/GO_MS_45.pdf --source aputf \
      --url "https://www.aputf.org/wp-content/uploads/2026/07/GO_MS_45.pdf"

The tool reads the first page to find type, number, date and department. Anything it cannot
read must be given explicitly (it never guesses):

  ... --type GOMS --number 45 --date 02-07-2026 --dept FIN01 --subject "Enhancement of age of superannuation"

The original stays in inbox/; a copy goes to staging/rule-library/<source>/<DEPT>/<YEAR>/<canonical-id>/.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import (GO_REF, LEVEL, STAGING, canonical_id, dept_code_for, doc_folder, iso_date,  # noqa: E402
                    load_scope, now, provenance, read_list, sha256, write_json)

SOURCES = {"aputf": "APUTF", "pag": "PAG (A&E) Andhra Pradesh", "finance": "AP Finance Department",
           "gazette": "APeGAZETTE", "goir": "GOIR (manual)", "circulars": "Departmental website"}


def pdf_text(path: pathlib.Path, pages: int = 3) -> str:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in r.pages[:pages])
    except Exception as e:
        print(f"warning: could not read text ({e}); scanned PDFs need --type/--number/--date/--dept")
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--url", required=True, help="the exact document URL, not the site homepage")
    ap.add_argument("--type", help="GOMS | GORT | CIRMEMO | MEMO | NOTIF | RULE")
    ap.add_argument("--number")
    ap.add_argument("--date", help="dd-mm-yyyy")
    ap.add_argument("--dept", help="scope code, e.g. FIN01")
    ap.add_argument("--subject")
    ap.add_argument("--filecode", help="for memos: the e-File code, e.g. FIN01-COOROMISC")
    ap.add_argument("--fileyear", help="for memos: the year in the e-File number (…/93/2023 -> 2023)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    scope = load_scope()
    src = pathlib.Path(a.pdf)
    text = pdf_text(src)

    hm = GO_REF.search(text)
    typ = (a.type or ("GOMS" if hm and hm.group("kind").lower() == "ms" else "GORT" if hm else "")).upper() or None
    number = a.number or (hm.group("num") if hm else None)
    date = iso_date(a.date) or (iso_date(hm.group("date")) if hm else None)
    dept = a.dept or dept_code_for("\n".join(text.splitlines()[:12]), scope)
    missing = [k for k, v in {"--type": typ, "--number": number, "--date": date, "--dept": dept}.items() if not v]
    if missing:
        print("Could not read:", ", ".join(missing), "\nRe-run with those options. First lines seen:\n",
              "\n".join(text.splitlines()[:12]))
        sys.exit(2)
    if a.url.rstrip("/").count("/") < 3:
        sys.exit("--url looks like a homepage; give the exact document link")

    memo = typ in ("MEMO", "CIRMEMO", "RC")
    if memo and not (a.filecode and a.fileyear):
        sys.exit("memos need --filecode and --fileyear (from the e-File number), e.g. "
                 "--filecode FIN01-COOROMISC --number 93 --fileyear 2023")
    cid = canonical_id(dept, typ, number, a.fileyear if memo else date[:4], filecode=a.filecode,
                       date=date if memo else None)
    subject = a.subject
    if not subject:
        import re
        m = re.search(r"ABSTRACT\s*\n(.+?)\n(?=[^\n]*(?:DEPARTMENT|G\.?O\.?|[\u0C00-\u0C7F]))", text, re.S)
        subject = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    meta = {
        "canonical_id": cid, "doc_type": {"NOTIF": "Notification", "RULE": "Rule"}.get(typ, "Government Order" if typ.startswith("GO") else "Circular"),
        "instrument": {"GOMS": "G.O.(Ms)", "GORT": "G.O.(Rt)"}.get(typ, typ), "number": number, "date": date,
        "date_raw": a.date, "department_code": dept, "department_name": scope["departments"].get(dept, {}).get("name"),
        "section": None, "subject": subject, "hierarchy_level": LEVEL.get(typ), "classification": "UNCLASSIFIED",
        "status": "unknown", "effective_from": date, "effective_to": None, "read_list": read_list(text),
        "language": "en", "origin": "public", "source_name": SOURCES[a.source], "source_url": a.url,
        "archive_identifier": None, "verification_status": "pending",
        "parse_confidence": "manual" if (a.type or a.number) else "high",
        "files": {"original": "order.pdf", "ocr": "ocr.txt"},
    }
    folder = doc_folder(STAGING, a.source, meta)
    print(("DRY " if a.dry_run else "") + f"{cid} -> {folder.relative_to(STAGING.parent)}")
    if a.dry_run:
        return
    if (folder / "meta.json").exists():
        sys.exit("already registered")
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, folder / "order.pdf")
    (folder / "ocr.txt").write_text(text)
    meta.update({"sha256": sha256(folder / "order.pdf"), "ocr_source": "pypdf text layer" if text.strip() else None,
                 "collected_at": now(), "collector": "tools/add_manual.py"})
    write_json(folder / "meta.json", meta)
    provenance(STAGING, meta, "manual download + add_manual.py")
    print("registered. Read-list items found:", len(meta["read_list"]))


if __name__ == "__main__":
    main()
