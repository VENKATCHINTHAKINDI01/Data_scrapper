"""Download G.O.s found by tools/list_web.py (APUTF first) into staging, with the same rules as collect_ia.py:
G.O.(Ms) only, dates from_date..as_of (no 2026), departments in scope, topic filter, skip canonical IDs already
held (any source), robots.txt + crawl delay (>= 10 s), sha256 + provenance. Department comes from the order's
own heading ("SCHOOL EDUCATION (SER.II) DEPARTMENT"), never from the listing title.

Dry run is the default (no downloads):
  python tools/collect_web.py aputf                 # show decisions for every listed PDF
  python tools/collect_web.py aputf --download --limit 2    # test: download 2
  python tools/collect_web.py aputf --download --limit 0    # full run (not in the current test phase)
"""
import argparse, json, re, tempfile, time, urllib.robotparser as rp
from pathlib import Path
import requests
from common import (load_scope, topic_decision, canonical_id, dept_code_for, read_list, normalize_ocr, sha256,
                    now, write_json, append_jsonl, provenance, doc_folder, LEVEL, CANONICAL_RE)

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "staging"
UA = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"
NAMES = {"aputf": "APUTF (AP United Teachers Federation) G.O. archive", "cag": "PAG (A&E) Andhra Pradesh G.O. page",
         "finance": "AP Finance Department website"}
GOMS = re.compile(r"G\.?\s*[O0]\.?\s*\(?\s*M\.?\s*S\.?\s*\)?\s*\.?\s*N[Oo]\.?\s*:?\s*(\d{1,4})", re.I)
GENERIC = re.compile(r"\bG\.?\s*O\.?\s*[_ ]?\s*(?:N[Oo]\.?|N[Oo]\s|[_-])\s*(\d{1,4})\b(?!\s*,\s*\d)", re.I)  # "GO No.239", "GO_106" (not "GO NO.73,75")
GORT = re.compile(r"G\.?\s*[O0]\.?\s*\(?\s*R\.?\s*T\.?\s*\)?\s*\.?\s*N[Oo]", re.I)
DATE = re.compile(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*((?:19|20)\d{2})")
DATED = re.compile(r"\b(?:Dated|Dt|Date)\s*\.?\s*[:.;]?\s*(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*((?:19|20)\d{2})", re.I)
TITLE_DT = re.compile(r"\b(?:dt|dated)\s*[:.]?\s*(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*((?:19|20)\d{2})", re.I)
FNAME = re.compile(r"^((?:19|20)\d{2})([A-Z]{2,6})_(?:\d+_)?(MS|RT)(\d{1,5})(?:_|\.|-|$)")
FNAME2 = re.compile(r"^(\d{2})(\d{2})((?:19|20)\d{2})([A-Z]{2,6})_(MS|RT)(\d{1,5})(?:_|\.|-|$)")   # 31032020FIN_MS26.pdf
FDATE = re.compile(r"(?:DT|DATED)[.\-_ ]*(\d{1,2})[.\-](\d{1,2})[.\-]((?:19|20)\d{2})")            # GO-Ms-No.66-Dt.01.05.2023.pdf
FDEPT = {"FIN": "FIN01", "GAD": "GAD01", "SE": "ESE01"}       # GOIR file-name department prefixes in scope
UPLOAD = re.compile(r"/uploads/((?:19|20)\d{2})/(\d{2})/")
# DEPARTMENT with OCR noise seen in CAG PDFs ("DFPARTMENT", "DEPARTIVIENT")
HEADING = re.compile(r"^[ \t]*([A-Z][A-Z &.,()'/-]{2,90}?)[ \t]*[\(\[I]?[A-Z0-9 .,&/-]*\)?[ \t]*D[ \t]*[EF][ \t]*P[ \t]*A[ \t]*R[ \t]*T[ \t]*(?:M|IVI)[ \t]*[EF][ \t]*N[ \t]*T\b", re.M)
AMEND_REF = re.compile(r"\b(?:amendments?|modification|corrigendum|addendum|errat\w*|further)\s+(?:to|of|in)\s+(?:the\s+)?"
                       r"(G\.?\s*O\.?\s*\(?\s*(?:M|R)\.?\s*[ST]\.?\s*\)?\s*\.?\s*N[Oo]\.?\s*\d+[^,;]{0,40})", re.I)

def held_ids():
    """canonical_id -> subject, for every order already in staging (any source)."""
    out = {}
    for p in (ST / "rule-library").rglob("meta.json"):
        try: out[p.parent.name] = json.loads(p.read_text()).get("subject") or ""
        except Exception: out[p.parent.name] = ""
    return out

def same_subject(a, b):
    """Word overlap of two subjects (titles are often cut off, so a modest bar)."""
    w = lambda x: {t for t in re.findall(r"[a-z]{4,}", (x or "").lower())} - {"government", "orders", "issued", "andhra", "pradesh", "department"}
    A, B = w(a), w(b)
    return bool(A and B) and len(A & B) / min(len(A), len(B)) >= 0.4

def to_review(source, row, content, reason, text):
    """Park a PDF the collector won't guess about; scanned ones are listed for Document AI (pending_ocr.jsonl)."""
    rev = ST / "_review" / "web" / source; rev.mkdir(parents=True, exist_ok=True)
    name = row["url"].rsplit("/", 1)[-1]
    (rev / name).write_bytes(content)
    append_jsonl(rev / "pending_ocr.jsonl" if len(text.strip()) < 200 else rev / "review.jsonl",
                 {"file": name, "url": row["url"], "title": row["text"][:250], "reason": reason,
                  "scanned": len(text.strip()) < 200, "at": now()})

def reviewed_urls(source):
    out = set()
    for f in ("pending_ocr.jsonl", "review.jsonl"):
        p = ST / "_review" / "web" / source / f
        if p.exists():
            out |= {json.loads(l)["url"] for l in p.read_text().splitlines() if l.strip()}
    return out

def pdf_text(path):
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    except Exception:
        return ""

def iso(m): return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None

def title_facts(row):
    t = row["text"] + " " + row["url"].rsplit("/", 1)[-1].replace("-", " ")
    m = GOMS.search(t)
    up = UPLOAD.search(row["url"])
    name = row["url"].rsplit("/", 1)[-1].upper()
    fn = FNAME.match(name)
    f2 = FNAME2.match(name)
    fdate = iso(FDATE.search(name))
    if f2 and not fn:
        return {"ms": f2.group(5) == "MS", "rt": f2.group(5) == "RT", "number": f2.group(6),
                "date": f"{f2.group(3)}-{f2.group(2)}-{f2.group(1)}", "upload_year": up.group(1) if up else None,
                "file_year": f2.group(3), "file_dept": f2.group(4), "title": row["text"]}
    # Only a "dt./dated" date in the title counts; other dates there are usually effective dates
    # ("enhancement due from 01-01-2024"). The real issue date is read from the PDF after download.
    if fn:   # the GOIR file name is more reliable than a cut-off title
        return {"ms": fn.group(3) == "MS", "rt": fn.group(3) == "RT", "number": fn.group(4),
                "date": iso(TITLE_DT.search(row["text"])), "upload_year": up.group(1) if up else None,
                "file_year": fn.group(1), "file_dept": fn.group(2), "title": row["text"]}
    if re.search(r"\bN[Oo]\.?\s*\d{1,4}\s*,\s*\d{1,4}\b", t):     # "GO NO.73,75": several G.O.s in one file
        return {"ms": False, "rt": False, "number": None, "multi": True, "date": None,
                "upload_year": up.group(1) if up else None, "title": row["text"]}
    am = AMEND_REF.search(row["text"])
    if am:   # "Amendment to G.O.Ms.No.61 dated 20.10.2025": 61 is the AMENDED order; own number comes from the PDF
        return {"ms": True, "rt": False, "number": None, "number_from_pdf": True, "amends_ref": am.group(1).strip(),
                "type_unknown": True, "date": None, "upload_year": up.group(1) if up else None, "title": row["text"]}
    rt = bool(GORT.search(t)) and not m
    g = None if (m or rt) else GENERIC.search(t)      # "GO No.N" with no Ms/Rt: type is read from the PDF
    return {"ms": bool(m or g), "rt": rt, "number": m.group(1) if m else (g.group(1) if g else None),
            "type_unknown": bool(g),
            "date": iso(TITLE_DT.search(row["text"])) or fdate or (iso(DATE.search(row["text"])) if g else None),
            "upload_year": up.group(1) if up else None,
            "title": row["text"]}

def header(text):
    """The order's header: everything above 'Read the following' / 'ORDER:' (abstract, department, own G.O. line)."""
    return re.split(r"\bRead\b|\bORDER\s*:", text[:4000], maxsplit=1)[0]

def _headings(text):
    return list(HEADING.finditer(header(text).upper()))

def heading_dept(text, scope):
    """The LAST department heading above 'Read' (the line right before the order's own G.O. line) decides;
    the whole line is matched against department names. (code, heading) if in scope, (None, heading) if it names
    another department (e.g. "LAW (LA&J SC.F) DEPARTMENT"), (None, None) if there is no heading."""
    hs = _headings(text)
    if not hs: return None, None
    m = hs[-1]; h = header(text).upper(); line = m.group(0).strip()
    code = dept_code_for(line, scope)          # heading line: aliases allowed (see common.dept_code_for)
    if not code:   # OCR may split the name over two lines: "SCHOOL" / "EDUCATION (PROG.II) DEPARTMENT"
        prev = h[:m.start()].rstrip("\n").rsplit("\n", 1)[-1].strip()
        if prev and len(prev) <= 30 and re.fullmatch(r"[A-Z &.,'-]+", prev):
            code = dept_code_for(prev + " " + line, scope)
    if code and not scope["departments"].get(code, {}).get("synthetic"):
        return code, line
    return None, line

def own_date(text, own):
    """Issue date printed on the order's own G.O. line ("G.O.Ms.No. 61   Dated: 20-10-2025"): on that line or the next,
    above 'Read', with no other G.O. reference in between. Otherwise None (-> review), never a nearby other date."""
    if not own: return None
    # same line or the next one: text layers often pad "G.O.Ms.No.19 <90 spaces> Dated:16-02-2024"
    nl = text.find("\n", own.end())
    nl2 = text.find("\n", nl + 1) if nl >= 0 else -1
    two_lines = nl2 if nl2 >= 0 else len(text)
    # whichever reaches further: 80 chars (OCR splits "Dated" / ":" / date over short lines) or two lines (padding)
    end = min(max(two_lines, own.end() + 80), own.end() + 300, len(header(text)))
    dm = DATED.search(text, own.end(), end)
    if not dm or re.search(r"G\.?\s*[O0]\.?\s*\(?\s*[MR]", text[own.end():dm.start()]): return None
    return dm

def own_line(text):
    """The order's own G.O. line: below the department heading and above 'Read'/'ORDER', so neither the abstract
    ("Amendment to G.O.Ms.No.61") nor a Read-list G.O. is ever taken as the order's own number."""
    h = header(text)
    hs = _headings(text)
    # search the full text between these offsets (header is a prefix of text) so match positions stay valid
    # for the issue-date search that follows in main()
    start = hs[-1].end() if hs else 0
    ms, rt = GOMS.search(text, start, len(h)), GORT.search(text, start, len(h))
    if ms and (not rt or ms.start() < rt.start()): return "MS", ms
    if rt: return "RT", rt
    return None, None

SINCE = None   # set by --since YEAR: collect older orders on purpose (e.g. the Revised Pay Scales chain)

def decide(f, scope, held, depts):
    lo, as_of = (f"{SINCE}-01-01" if SINCE else str(scope["from_date"])), str(scope["as_of"])
    if f.get("multi"): return False, "several G.O.s in one file"
    if f["rt"]: return False, "G.O.(Rt)"
    if not f["ms"] or not (f["number"] or f.get("number_from_pdf")): return False, "not a G.O.(Ms) / no number in title"
    fd = f.get("file_dept")
    if fd and fd not in FDEPT: return False, f"other department (file name {fd})"
    if f.get("file_year"):
        cid = canonical_id(FDEPT[fd], "GOMS", f["number"], f["file_year"])
        if cid in held: return False, f"already held: {cid}"
    hint = f["date"] or (f.get("file_year") and f["file_year"] + "-06-30") or (f["upload_year"] and f["upload_year"] + "-12-31")
    if f["date"] and f["date"] > as_of: return False, f"after as_of {as_of}"
    if hint and hint < lo: return False, f"before {lo}"    # uploaded before 2018 -> issued before 2018
    title_l = f["title"].lower()
    named = [c for c in depts if any(a.lower() in title_l for a in
             [scope["departments"][c]["name"]] + scope["departments"][c].get("aliases", []))]
    ok, why = topic_decision(f["title"], scope)
    if not ok: return False, f"topic: {why}"
    if f["date"] and f["number"]:
        cands = [canonical_id(c, "GOMS", f["number"], f["date"][:4]) for c in (named or depts)]
        # department named in the title: number+year is enough; otherwise the subjects must match too
        hit = next((c for c in cands if c in held and (named or same_subject(held[c], f["title"]))), None)
        if hit: return False, f"already held: {hit}"
    return True, f"{why}" + (f" (title names {','.join(named)})" if named else " (department from heading)") \
        + ("" if f["date"] else " [date from PDF]") + (" [type from PDF]" if f.get("type_unknown") else "") \
        + (f" [amends {f['amends_ref'][:30]}; own number from PDF]" if f.get("number_from_pdf") else "")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=list(NAMES))
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--limit", type=int, default=2, help="test mode: 2 downloads; --limit 0 = no cap (full run)")
    ap.add_argument("--show", type=int, default=400)
    ap.add_argument("--match", help="only consider listing entries whose title or URL matches this regex (for targeted tests)")
    ap.add_argument("--since", type=int, help="also keep orders from this year on (default scope from_date); "
                    "older ones are labelled collected_via=older-chain")
    a = ap.parse_args()
    global SINCE; SINCE = a.since
    scope = load_scope()
    depts = [c for c, d in scope["departments"].items() if not d.get("synthetic")]
    listing = ST / "manifests" / f"web_listing_{a.source}.jsonl"
    rows = [json.loads(l) for l in listing.read_text().splitlines() if l.strip()]
    held = held_ids()
    robots_cache = {}
    def robots_for(url):   # robots.txt of the host that serves the file (CAG PDFs come from a CloudFront CDN)
        host = re.match(r"https?://[^/]+", url).group(0)
        if host not in robots_cache:
            rpp = rp.RobotFileParser()
            try:
                r = requests.get(host + "/robots.txt", headers={"User-Agent": UA}, timeout=20)
                rpp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rpp.parse([])
            robots_cache[host] = rpp
        return robots_cache[host]
    delay = max(10, int((robots_for(rows[0]["url"]).crawl_delay("*") if rows else 0) or 0))
    reviewed = reviewed_urls(a.source)
    match = re.compile(a.match, re.I) if a.match else None
    stats, done, shown, fetched, errors = {}, 0, 0, 0, 0
    for row in rows:
        if match and not (match.search(row["text"]) or match.search(row["url"])): continue
        f = title_facts(row)
        ok, why = decide(f, scope, held, depts)
        if ok and row["url"] in reviewed: ok, why = False, "already in _review (scanned or unclear)"
        key = "candidate" if ok else why.split(":")[0]
        stats[key] = stats.get(key, 0) + 1
        if shown < a.show and (ok or not why.startswith(("G.O.(Rt)", "not a G.O."))):
            print(f"{'KEEP' if ok else 'skip'}  {f['date'] or '????-??-??'} Ms.{f['number'] or '?':<5} {why[:45]:<45} {f['title'][:70]}")
            shown += 1
        if not (ok and a.download): continue
        if a.limit and fetched >= a.limit:
            print(f"   limit reached: {fetched} downloads (use --limit N, or --limit 0 for no cap)"); break
        if not robots_for(row["url"]).can_fetch(UA, row["url"]):
            print("   robots.txt disallows", row["url"]); continue
        time.sleep(delay)
        fetched += 1
        try:
            resp = requests.get(row["url"], headers={"User-Agent": UA}, timeout=90)
            errors = 0
        except requests.RequestException as e:
            errors += 1
            append_jsonl(ST / "manifests" / "failed.jsonl", {"source": a.source, "url": row["url"],
                         "error": str(e)[:200], "at": now()})
            print(f"   connection error {errors}/3: {type(e).__name__} — logged to failed.jsonl")
            if errors >= 3:
                print("   3 errors in a row: the site may be pushing back. Stopping; try again later."); break
            time.sleep(delay * 6); continue
        if not resp.ok or not resp.content.startswith(b"%PDF"):
            print(f"   download failed: HTTP {resp.status_code} {row['url']}"); continue
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(resp.content); tp = Path(tmp.name)
        text = pdf_text(tp)
        # 1. scanned: nothing to check against -> Document AI later
        if len(text.strip()) < 200:
            print(f"   scanned (no text layer) -> _review: {row['url']}")
            to_review(a.source, row, resp.content, "scanned (no text layer)", text); tp.unlink(); continue
        # 2. order type from the order's own line (OCR-tolerant: "GORtNo12")
        kind, own = own_line(text)
        if kind == "RT":
            print(f"   the PDF is a G.O.(Rt) ({own.group(0)[:20]!r}) — not kept"); tp.unlink(); continue
        # 3. department from the order's own heading
        dept, head = heading_dept(text, scope)
        if not dept and head:
            print(f"   out of scope department ({head[:50]}) — not kept"); tp.unlink(); continue
        if not dept:
            named = [c for c in depts if scope["departments"][c]["name"].lower() in f["title"].lower()]
            dept = named[0] if len(named) == 1 else None
            if not dept:
                print(f"   department heading not found -> _review: {row['url']}")
                to_review(a.source, row, resp.content, "department heading not found", text); tp.unlink(); continue
        if dept not in depts:
            print(f"   out of scope department ({head}) — not kept"); tp.unlink(); continue
        # 4. own number: from the PDF; must agree with the title unless the title names another order
        if own:
            pdf_no = own.group(1) if own.re is GOMS else None
            if f.get("number_from_pdf"):
                f["number"] = pdf_no
            elif pdf_no and int(pdf_no) != int(f["number"]):
                print(f"   number mismatch title Ms.{f['number']} vs PDF Ms.{pdf_no} -> _review")
                to_review(a.source, row, resp.content, f"number mismatch (title {f['number']}, PDF {pdf_no})", text)
                tp.unlink(); continue
        if not f["number"]:
            print(f"   own G.O. number not readable in the PDF -> _review: {row['url']}")
            to_review(a.source, row, resp.content, "own G.O. number not readable", text); tp.unlink(); continue
        # 5. issue date from the own line (never a Read-list date)
        dm = own_date(text, own)      # only the date on the order's own G.O. line
        real = iso(dm)
        if not real:
            print(f"   issue date not readable (OCR noise?) -> _review: {row['url']}")
            to_review(a.source, row, resp.content, "issue date not readable", text); tp.unlink(); continue
        if f["date"] and real != f["date"]:
            from datetime import date as _d
            gap = abs((_d.fromisoformat(real) - _d.fromisoformat(f["date"])).days)
            if gap > 3:   # title/file-name date and PDF disagree: one of them is misread — a person decides
                print(f"   date conflict: listing says {f['date']}, PDF says {real} -> _review")
                to_review(a.source, row, resp.content, f"date conflict (listing {f['date']}, PDF {real})", text)
                tp.unlink(); continue
            print(f"   note: listing date {f['date']} vs PDF 'Dated' {real} — using the PDF")
        f["date"] = real
        lo_ = f"{SINCE}-01-01" if SINCE else str(scope["from_date"])
        if not (lo_ <= real <= str(scope["as_of"])):
            print(f"   issued {real}, outside {lo_}..{scope['as_of']} — not kept"); tp.unlink(); continue
        num_in_text = own
        cid = canonical_id(dept, "GOMS", f["number"], f["date"][:4])
        if cid in held:
            if same_subject(held[cid], f["title"]) or same_subject(held[cid], text[:1500]):
                print(f"   already held: {cid}"); tp.unlink(); continue
            # same number and year, different order (e.g. two Finance G.O.Ms.126 of 2023): never guess a suffix
            print(f"   ID collision: {cid} is already a different order ({held[cid][:60]!r}) -> _review")
            to_review(a.source, row, resp.content, f"ID collision with {cid}: needs a suffix decision", text)
            tp.unlink(); continue
        assert CANONICAL_RE.match(cid), cid
        meta = {"canonical_id": cid, "doc_type": "Government Order", "instrument": "G.O.(Ms)",
                "number": str(int(f["number"])), "date": f["date"], "date_raw": dm.group(0),
                "department_code": dept, "department_name": scope["departments"][dept]["name"],
                "section": None, "category": None, "subject": f["title"],
                "hierarchy_level": LEVEL["GOMS"], "classification": "UNCLASSIFIED", "status": "unknown",
                "effective_from": f["date"], "effective_to": None,
                "read_list": read_list(normalize_ocr(text[:6000])) if text else [],
                "language": "en/te", "origin": "public", "source_name": NAMES[a.source],
                "source_url": row["url"], "official_url": None, "listing_page": row.get("page"),
                "verification_status": "pending",
                "parse_confidence": "high" if (num_in_text and head and dm) else "medium",
                "amends_ref": f.get("amends_ref"),
                "files": {"original": "order.pdf", "ocr": "ocr.txt" if text.strip() else None},
                "ocr_source": "PDF text layer (pypdf)" if text.strip() else None,
                "dept_evidence": head or "title", "collector": "tools/collect_web.py",
                "collected_via": "older-chain" if real < str(scope["from_date"]) else "topic", "collected_at": now()}
        folder = doc_folder(ST, a.source, meta); folder.mkdir(parents=True, exist_ok=True)
        (folder / "order.pdf").write_bytes(resp.content); tp.unlink()
        if text.strip(): (folder / "ocr.txt").write_text(normalize_ocr(text))
        meta["sha256"] = sha256(folder / "order.pdf")
        write_json(folder / "meta.json", meta); provenance(ST, meta, f"web:{a.source}")
        held[cid] = meta["subject"]; done += 1
        print(f"   saved {cid}  ({head or 'dept from title'}; {'text layer' if text.strip() else 'scanned: needs Document AI'})")
    print(f"\nlisted {len(rows)} | decisions: {stats} | PDFs fetched {fetched} | new orders saved {done}")
    if not a.download: print("dry run — add --download --limit 2 to test")

if __name__ == "__main__":
    main()
