"""Steps 4b/7 — collect G.O.s (or gazette issues) from the Internet Archive mirror `andhra-goir`.

Always start with --probe to see real records, then --dry-run, then a small real run.

  python tools/collect_ia.py --probe 5
  python tools/collect_ia.py --dept FIN01 --from 2024-01-01 --to 2024-12-31 --limit 5 --dry-run
  python tools/collect_ia.py --dept FIN01 --from 2024-01-01 --to 2024-12-31 --limit 5
  python tools/collect_ia.py --kind gazette --from 2025-01-01 --to 2025-03-31 --limit 5

Writes  staging/rule-library/goir/<DEPT>/<YEAR>/<canonical-id>/{order.pdf, ocr.txt, meta.json}
Records whose canonical ID cannot be built go to staging/_review/ (never guessed).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import (GO_REF, LEVEL, STAGING, append_jsonl, canonical_id, dept_code, dept_code_for, doc_folder,
                    order_kinds, topic_decision,  # noqa: E402
                    iso_date, load_scope, now, provenance, read_list, sha256, write_json)

SEARCH = "https://archive.org/advancedsearch.php"
PREFIX = {"go": "in.gov.andhra.goir", "gazette": "in.gazette.andhra_new"}
FIELDS = ["Order Type", "Order Number", "Order No", "Order Date", "Date", "Department", "Section",
          "Category", "Abstract", "Subject", "Amount", "Order Source"]
S = requests.Session()
S.headers["User-Agent"] = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"


def get(url: str, **kw):
    """GET with retries: archive.org sometimes answers 500/502/503 and then serves the file."""
    for attempt in range(4):
        try:
            r = S.get(url, **kw)
            if r.status_code < 500:
                return r
            err = f"HTTP {r.status_code}"
            r.close()
        except requests.RequestException as e:
            err = str(e)
        if attempt < 3:
            wait = (5, 15, 45)[attempt]
            print(f"   retry {attempt + 1}/3 in {wait}s ({err}): {url[-70:]}")
            time.sleep(wait)
    raise requests.HTTPError(f"gave up after 4 tries ({err}): {url}")


def search(query: str, limit: int, fields=("identifier", "title", "date")):
    page = 1
    while True:
        r = get(SEARCH, params={"q": query, "fl[]": list(fields), "rows": 100,
                                  "page": page, "sort[]": "date desc", "output": "json"}, timeout=60)
        r.raise_for_status()
        docs = r.json()["response"]["docs"]
        if not docs:
            return
        yield from docs
        page += 1
        if page * 100 > max(limit * 150, 3000):   # filtering is cheap (search results carry the abstract)
            return


def item_metadata(identifier: str) -> dict:
    r = get(f"https://archive.org/metadata/{identifier}", timeout=60)
    r.raise_for_status()
    return r.json()


def text_of(value) -> str:
    if isinstance(value, list):
        value = " ".join(map(str, value))
    value = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", str(value or ""), flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", value))


def parse_description(desc: str) -> dict:
    out = {}
    # search results give the description on one line, so stop each value at the next label
    nxt = "|".join(re.escape(f) for f in FIELDS)
    for f in FIELDS:
        m = re.search(rf"{re.escape(f)}\s*[:\-]\s*(.+?)(?=\s+(?:{nxt})\s*:|\n|$)", desc, re.I)
        if m:
            out[f.lower().replace(" ", "_")] = m.group(1).strip()[:500]
    return out


def find_cited(path: str, base_q: str, scope: dict, pause: float) -> list[dict]:
    """Look up orders listed in missing.txt (e.g. AP-FIN01-GOMS-98-2024) by department + year,
    matching the order number in the search result's description - no metadata fetch per record."""
    import pathlib
    latest = str(scope.get("archive_latest") or "9999")
    mpath = pathlib.Path(path)
    metas = list(STAGING.glob("rule-library/*/*/*/*/meta.json"))
    if metas and max(m.stat().st_mtime for m in metas) > mpath.stat().st_mtime:
        sys.exit("missing.txt is older than the newest collected order - run "
                 "`python tools/extract_relations.py staging` first, then --cited")
    # depth 1: follow only citations made BY orders collected on topic, not by orders fetched as citations
    via = {}
    for m in metas:
        j = json.loads(m.read_text())
        via[j["canonical_id"]] = j.get("collected_via", "topic")
    allowed = None
    rel = mpath.parent / "relations.jsonl"
    if rel.exists():
        allowed = {e["to"] for e in map(json.loads, rel.read_text().splitlines())
                   if e.get("to") and via.get(e["from"], "topic") != "cited"}
    want: dict[tuple, set] = {}
    skipped_depth = 0
    for line in open(path):
        m = re.fullmatch(r"AP-([A-Z]{2,6}\d{2})-(GOMS|GORT)-(\d+)-(\d{4})", line.strip())
        if not m or m.group(4) > latest[:4]:
            continue
        if allowed is not None and line.strip() not in allowed:
            skipped_depth += 1
            continue
        want.setdefault((m.group(1), m.group(4)), set()).add(line.strip())
    if skipped_depth:
        print(f"not following {skipped_depth} citations made only by cited orders (depth limit 1)")
    found = []
    for (dept, year), ids in sorted(want.items()):
        q = f"{base_q} AND title:({dept}) AND date:[{year}-01-01 TO {year}-12-31]"
        left = set(ids)
        for doc in search(q, 40, fields=("identifier", "title", "date", "description")):
            d = parse_description(text_of(doc.get("description")))
            num = re.sub(r"\D", "", d.get("order_number") or d.get("order_no") or "")
            otype = d.get("order_type") or str(doc.get("title"))
            kind = "GORT" if re.search(r"Routine|\bRt\b", otype, re.I) else "GOMS"
            cid = f"AP-{dept}-{kind}-{int(num)}-{year}" if num else None
            if cid in left:
                left.discard(cid)
                found.append({"identifier": doc["identifier"], "title": doc.get("title"), "_wanted": cid})
                print(f"found cited {cid}: {doc['identifier']}")
            if not left:
                break
        for cid in sorted(left):
            print(f"not in mirror: {cid}  (get it from GOIR/APUTF with add_manual.py)")
        time.sleep(pause)
    return found


def download(identifier: str, name: str, dest) -> None:
    with get(f"https://archive.org/download/{identifier}/{name}", stream=True, timeout=120) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def build_meta(identifier: str, md: dict, files: list, ocr_head: str, scope: dict) -> dict:
    desc = text_of(md.get("description"))
    d = parse_description(desc)
    title = text_of(md.get("title"))
    otype = (d.get("order_type") or title)
    kind = "GORT" if re.search(r"\bR(ou)?t(ine)?\b|Routine", otype, re.I) else (
        "GOMS" if re.search(r"Manuscript|\bMs\b", otype, re.I) else None)
    number = re.sub(r"\D", "", d.get("order_number") or d.get("order_no") or "") or None
    date = iso_date(d.get("order_date") or d.get("date")) or iso_date(str(md.get("date", ""))[:10])
    dept_label = d.get("department") or title
    # 1) code in the Department field, 2) code in the title, 3) name in the Department field,
    # 4) name in the order's own heading (lines before "Read the following"). Never the abstract.
    heading = re.split(r"Read\s+the\s+following", ocr_head or "", flags=re.I)[0]
    heading = "\n".join(heading.splitlines()[:12])
    dept = (dept_code(d.get("department")) or dept_code(title)
            or dept_code_for(d.get("department") or "", scope)
            or dept_code_for(heading, scope))
    # fall back to the order's own header line in the OCR text
    hm = GO_REF.search(ocr_head or "")
    if hm:
        kind = kind or ("GOMS" if hm.group("kind").lower() == "ms" else "GORT")
        number = number or hm.group("num")
        date = date or iso_date(hm.group("date"))
    cid = canonical_id(dept, kind, number, date[:4]) if all([dept, kind, number, date]) else None
    pdf = next((f["name"] for f in files if f["name"].lower().endswith(".pdf")), None)
    return {
        "canonical_id": cid, "doc_type": "Government Order", "instrument": {"GOMS": "G.O.(Ms)", "GORT": "G.O.(Rt)"}.get(kind),
        "number": number, "date": date, "date_raw": d.get("order_date"),
        "department_code": dept,
        "department_name": (scope.get("departments", {}).get(dept, {}).get("name")
                            or re.sub(r"^\s*[A-Za-z]{2,6}\d{2}\s*-?\s*", "", dept_label or "").strip() or None),
        "section": d.get("section"),
        "category": d.get("category"), "subject": d.get("abstract") or d.get("subject") or title,
        "hierarchy_level": LEVEL.get(kind or "", None), "classification": "UNCLASSIFIED",
        "status": "unknown", "effective_from": date, "effective_to": None,
        "read_list": read_list(ocr_head or ""), "language": "en/te",
        "origin": "public", "source_name": "Internet Archive mirror of GOIR",
        "source_url": f"https://archive.org/details/{identifier}",
        "official_url": (d.get("order_source") if str(d.get("order_source") or "").startswith("http") else None),  # mirror says literally "URL"
        "archive_identifier": identifier,
        "verification_status": "pending", "parse_confidence": "high" if d.get("order_number") else "medium",
        "files": {"original": "order.pdf" if pdf else None, "ocr": "ocr.txt"},
        "_pdf_name": pdf, "_title": title,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["go", "gazette"], default="go")
    ap.add_argument("--dept", action="append", help="scope code, e.g. FIN01 (repeatable)")
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--probe", type=int, default=0, help="print N raw records and exit")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-text-filter", action="store_true", help="do not add the department code to the query")
    ap.add_argument("--all-types", action="store_true", help="ignore scope.order_types (keep Ms and Rt)")
    ap.add_argument("--all-topics", action="store_true", help="ignore scope.keep_topics")
    ap.add_argument("--cited", metavar="MISSING_TXT",
                    help="fetch orders that collected orders cite (staging/manifests/missing.txt); "
                         "bypasses the topic and type filters")
    a = ap.parse_args()
    scope = load_scope()
    pause = scope.get("sleep_seconds", {}).get("archive", 1)
    df, dt_ = a.date_from or str(scope["from_date"]), a.date_to or str(scope["to_date"])

    latest = str(scope.get("archive_latest") or "")
    if latest and dt_ > latest:
        print(f"note: the mirror ends at {latest}; nothing after that will be found. "
              f"Get later orders from APUTF/GOIR with tools/add_manual.py")
    q = f"collection:andhra-goir AND identifier:{PREFIX[a.kind]}* AND date:[{df} TO {dt_}]"
    if a.kind == "go" and a.dept and not a.no_text_filter:
        codes = [c for c in a.dept if re.fullmatch(r"[A-Z]{2,6}\d{2}", c)]
        bad = sorted(set(a.dept) - set(codes))
        if bad:
            sys.exit(f"not a GOIR department code: {bad} (fix scope.yaml first)")
        # filter on the code in the title (e.g. "Fin01 - Finance"), not on the department name,
        # which also appears in other departments' abstracts
        q += " AND (" + " OR ".join(f"title:({c})" for c in codes) + ")"
    print("query:", q)

    if a.probe:
        for i, doc in enumerate(search(q, a.probe)):
            if i >= a.probe:
                break
            md = item_metadata(doc["identifier"])
            print("\n---", doc["identifier"])
            print("title      :", text_of(md["metadata"].get("title")))
            print("date       :", md["metadata"].get("date"))
            print("description:", text_of(md["metadata"].get("description"))[:700].strip())
            print("files      :", [f["name"] for f in md.get("files", [])][:12])
            time.sleep(pause)
        return

    want_kinds = None if a.all_types else (order_kinds(scope, a.dept) or None)
    topics = True   # topic decision via common.topic_decision (keep_topics + skip_topics); --all-topics keeps all but skips
    if a.kind == "go" and not a.cited:
        print(f"keeping types: {sorted(want_kinds) if want_kinds else 'all'} · topics: {'scope.keep_topics' if topics else 'all'}")
    docs = search(q, a.limit, fields=("identifier", "title", "date", "description"))
    if a.cited:
        base = f"collection:andhra-goir AND identifier:{PREFIX['go']}*"
        targets = find_cited(a.cited, base, scope, pause)
        docs, want_kinds, topics, a.dept = iter(targets), None, None, None
        a.limit = len(targets)
    kept = seen = skipped = skip_type = skip_topic = 0
    for doc in docs:
        if kept >= a.limit:
            break
        seen += 1
        ident = doc["identifier"]
        # cheap pre-filter on the search title, before fetching metadata
        t0 = str(doc.get("title") or "")
        if a.kind == "go" and want_kinds:
            kind0 = "GORT" if re.search(r"Routine", t0, re.I) else ("GOMS" if re.search(r"Manuscript", t0, re.I) else None)
            if kind0 and kind0 not in want_kinds:
                skip_type += 1
                continue
        if a.kind == "go" and not doc.get("_wanted"):
            # cheap topic pre-filter on the abstract carried by the search result (no metadata fetch)
            abs0 = parse_description(text_of(doc.get("description"))).get("abstract")
            if abs0:
                ok, why = topic_decision(abs0, scope, a.all_topics)
                if not ok:
                    print(f"skip (topic: {why}): {ident}  {abs0[:70].lower()}")
                    skip_topic += 1
                    continue
        try:
            full = item_metadata(ident)
            md, files = full["metadata"], full.get("files", [])
            txt = next((f["name"] for f in files if f["name"].endswith("_djvu.txt")), None)
            ocr_head = ""
            if txt:
                r = get(f"https://archive.org/download/{ident}/{txt}", timeout=60)
                ocr_head = r.text if r.ok else ""
            if a.kind == "gazette":
                meta = {"canonical_id": None, "subject": text_of(md.get("title")), "_pdf_name":
                        next((f["name"] for f in files if f["name"].lower().endswith(".pdf")), None)}
                m = re.search(r"(\d{4}-\d{2}-\d{2}),\s*(\w+),\s*Part\s*([\w-]+),\s*Number\s*(\d+)", meta["subject"], re.I)
                if m:
                    meta.update({"canonical_id": f"AP-GAZ-{m.group(2)[:3].upper()}{m.group(3).upper()}-{int(m.group(4))}-{m.group(1)[:4]}",
                                 "doc_type": "Gazette", "instrument": "Gazette", "number": m.group(4), "date": m.group(1),
                                 "department_code": "GAZ", "hierarchy_level": 3, "classification": "UNCLASSIFIED",
                                 "origin": "public", "source_name": "Internet Archive mirror (AP Gazette)",
                                 "source_url": f"https://archive.org/details/{ident}", "archive_identifier": ident,
                                 "verification_status": "pending", "files": {"original": "order.pdf", "ocr": "ocr.txt"}})
                source = "gazette"
            else:
                meta = build_meta(ident, md, files, ocr_head, scope)
                source = "goir"
                if a.dept and meta["department_code"] not in a.dept:
                    print(f"skip (dept {meta['department_code']}): {ident}")
                    skipped += 1
                    continue
            if a.kind == "go" and meta.get("canonical_id"):
                kind = meta["canonical_id"].split("-")[2]
                if want_kinds and kind not in want_kinds:
                    skip_type += 1
                    continue
                subj = str(meta.get("subject") or "")
                ok, why = topic_decision(subj, scope, a.all_topics) if not doc.get("_wanted") else (True, "cited")
                if not ok:
                    print(f"skip (topic: {why}): {meta['canonical_id']}  {subj[:60].lower()}")
                    skip_topic += 1
                    continue
            pdf_name = meta.pop("_pdf_name", None)
            meta.pop("_title", None)
            if doc.get("_wanted") and meta.get("canonical_id") != doc["_wanted"]:
                print(f"REVIEW: wanted {doc['_wanted']} but record parses as {meta.get('canonical_id')}: {ident}")
                continue
            if not meta.get("canonical_id") or not pdf_name:
                print(f"REVIEW (could not build ID or no PDF): {ident}")
                if not a.dry_run:
                    write_json(STAGING / "_review" / ident / "meta.partial.json", meta)
                continue
            folder = doc_folder(STAGING, source, meta)
            if (folder / "meta.json").exists():
                old_ident = json.loads((folder / "meta.json").read_text()).get("archive_identifier")
                if old_ident and old_ident != ident:
                    # two different orders with the same number and year (seen: FIN01 G.O.Ms.No.126 of 2023)
                    print(f"DUPLICATE ID {meta['canonical_id']}: already {old_ident}, also {ident} -> _review")
                    if not a.dry_run:
                        meta["duplicate_of"] = old_ident
                        write_json(STAGING / "_review" / ident / "meta.partial.json", meta)
                else:
                    print(f"exists: {meta['canonical_id']}")
                continue
            print(f"{'DRY ' if a.dry_run else ''}OK  {meta['canonical_id']:<26} {meta.get('date')}  {ident}\n"
                  f"      {str(meta.get('subject'))[:110]}")
            kept += 1
            if a.dry_run:
                continue
            download(ident, pdf_name, folder / "order.pdf")
            (folder / "ocr.txt").write_text(ocr_head or "")
            meta["sha256"] = sha256(folder / "order.pdf")
            meta["ocr_source"] = "archive.org tesseract (_djvu.txt)" if ocr_head else None
            meta["collected_at"] = now()
            meta["collector"] = "tools/collect_ia.py"
            meta["collected_via"] = "cited" if a.cited else "topic"
            write_json(folder / "meta.json", meta)
            provenance(STAGING, meta, "collect_ia.py")
        except Exception as e:  # keep going; log for retry
            print(f"FAILED {ident}: {e}")
            if not a.dry_run:
                append_jsonl(STAGING / "manifests" / "failed.jsonl", {"identifier": ident, "error": str(e), "at": now()})
        time.sleep(pause)
    print(f"\nseen {seen}, kept {kept}, skipped: department {skipped}, type {skip_type}, topic {skip_topic}"
          f"{' (dry run — nothing written)' if a.dry_run else ''}")


if __name__ == "__main__":
    main()
