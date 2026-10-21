"""AP e-Gazette (apegazette.cgg.gov.in) — search, list, and (optionally) download a few gazettes.

How the site works (inspected 18 Oct 2026): GET /searchAllGazette gives a session cookie and a hidden _csrf token;
the search form (id searchGazetteForm) POSTs to searchAllGazettes with departmentId, gazeeteTypeId (1 Extraordinary,
2 Weekly), gazeetePartId (9 = Part IV-B), year, month1, fromdate, todate, gazetteno, abstract1. Results open with
uploadGazette_view?filePath=…  The captcha on the page belongs to the officer login, not to search.

Default is a DRY RUN: one GET + one search POST, results listed, nothing downloaded.
  python tools/collect_gazette.py --options                              # print department / type / part lists
  python tools/collect_gazette.py --dept FINANCE --type 1 --year 2024              # list (dry run)
  python tools/collect_gazette.py --dept FINANCE --type 1 --year 2024 --pick 9     # save result no. 9 only
Notes (tested 18 Oct 2026): only the YEAR filter returns results; date ranges (DDMMYYYY) return nothing.
Download links are signed tokens tied to the search; the stable key is the file path inside the token.
Raw result page is saved to staging/manifests/egazette_last_search.html so the parser can be checked.
"""
import argparse, base64, json, re, time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
from common import load_scope, topic_decision, canonical_id, sha256, now, write_json, append_jsonl, provenance, CANONICAL_RE, LEVEL

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "staging"
BASE = "https://apegazette.cgg.gov.in/"
UA = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"
DELAY = 10
txt = lambda x: re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()

def get_form(s):
    r = s.get(BASE + "searchAllGazette", timeout=40); r.raise_for_status(); h = r.text
    f = re.search(r'<form\b[^>]*id="searchGazetteForm"[^>]*>(.*?)</form>', h, re.I | re.S)
    if not f: raise SystemExit("search form not found — the page changed; re-run tools/inspect_form.py")
    tag = re.search(r'<form\b[^>]*id="searchGazetteForm"[^>]*>', h, re.I).group(0)
    action = (re.search(r'action="([^"]*)"', tag) or [None, "searchAllGazettes"])[1]
    body = f.group(1)
    hidden = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body, re.I))
    hidden.update({k: v for v, k in re.findall(r'<input[^>]*type="hidden"[^>]*value="([^"]*)"[^>]*name="([^"]+)"', body, re.I)})
    selects = {}
    for sel in re.finditer(r'<select\b[^>]*name="([^"]+)"[^>]*>(.*?)</select>', body, re.I | re.S):
        selects[sel.group(1)] = [(v, txt(l)) for v, l in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', sel.group(2), re.I | re.S)]
    dates = [re.sub(r"\s+", " ", t) for t in re.findall(r'<input[^>]*name="(?:fromdate|todate)"[^>]*>', body, re.I)]
    return urljoin(BASE, action), hidden, selects, dates

def pick(options, want):
    if want is None: return ""
    for v, l in options:
        if want == v or want.upper() == l.upper() or l.upper().startswith(want.upper()): return v
    raise SystemExit(f"'{want}' not in options: {[l for _, l in options][:40]} …")

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
LEAD = re.compile(r"(?i)^(?:from|dated?|dt\.?)\s+")   # "G.O.Ms.No.18, FROM FINANCE" -> "FINANCE"
GO_IN = re.compile(r"G\.?O\.?\s*(Ms|Rt)\.?\s*No\.?\s*(\d+)\s*,?\s*([A-Za-z .&]+?)\s*\(", re.I)

def file_key(token):
    """Signed download token -> stable file path inside it (/Uploads/APGAZETTE/gazettes/<id>.pdf)."""
    try:
        payload = token.split(".")[1]; payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("sub") or token
    except Exception:
        return token

def pub_date(cell):
    m = re.search(r"(\d{1,2})-([a-z]{3})-((?:19|20)\d{2})", cell or "", re.I)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{2})[-/.](\d{2})[-/.]((?:19|20)\d{2})", cell or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None

def part_code(cell):   # "Extraordinary / PART IV-B" -> "EIVB", "Weekly / Part I" -> "WI"
    kind = "E" if "extra" in (cell or "").lower() else "W" if "week" in (cell or "").lower() else "X"
    m = re.search(r"part\s*([IVX]+(?:\s*-?\s*[A-Z])?)", cell or "", re.I)
    return kind + (re.sub(r"[^A-Z]", "", m.group(1).upper()) if m else "")

def gazette_kind(part, abstract, act):
    """What the gazette carries decides its level (CLAUDE.md hierarchy): Act text (Part IV-B / --act) = 2,
    statutory rules notified = 3, everything else (commencement notices, republished G.O.s, notifications) = 4."""
    a = (abstract or "").lower()
    if act or "IV" in part_code(part): return "ACT", LEVEL["ACT"]
    if re.search(r"\brules?\b[^.]{0,80}\b(notified|amendment|issued)|amendment[s]? to the [^.]{0,120}\brules\b", a) \
            and "commencement" not in a:
        return "RULE", LEVEL["RULE"]
    return "NOTIFICATION", LEVEL["GOMS"]

def pdf_text(path):
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    except Exception:
        return ""

def parse_results(h):
    """Columns (18 Oct 2026): S.No | Type/Part | Department | Abstract | Date of Publication | Gazette No |
    Issue No | Notification No | Download(openDocument('<token>'))"""
    body = h.split("<tbody", 1)[-1] if "<tbody" in h else h
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.I | re.S):
        cells = [txt(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.I | re.S)]
        tok = re.search(r"openDocument\(\s*'([^']+)'", tr)
        if not (tok and len(cells) >= 8): continue
        go = GO_IN.search(cells[3])
        rows.append({"sno": cells[0], "part": cells[1], "dept": cells[2], "abstract": cells[3],
                     "date": pub_date(cells[4]), "gazette_no": re.sub(r"\D", "", cells[5]) or None,
                     "issue_no": cells[6], "notification_no": cells[7], "token": tok.group(1),
                     "file": file_key(tok.group(1)),
                     "republishes": (f"G.O.{go.group(1).title()}.No.{go.group(2)}, {LEAD.sub('', go.group(3).strip())}"
                                     if go else None)})
    return rows

def republished_id(rep, year, scope):
    """'G.O.Ms.No.18, FINANCE' + gazette year -> AP-FIN01-GOMS-18-2024 (only when the department is in scope)."""
    from common import dept_code_for
    m = re.match(r"G\.O\.(Ms|Rt)\.No\.(\d+), (.+)", rep or "")
    dc = dept_code_for(m.group(3), scope) if m else None
    return canonical_id(dc, "GO" + m.group(1).upper(), m.group(2), year) if (dc and year) else None

def held_index():
    """gazette file keys already saved, and G.O. canonical IDs already held (to mark republished G.O.s)."""
    files, ids = set(), set()
    for p in (ST / "rule-library").rglob("meta.json"):
        try:
            m = json.loads(p.read_text()); ids.add(m.get("canonical_id"))
            if m.get("gazette_file"): files.add(m["gazette_file"])
        except Exception: pass
    return files, ids

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--options", action="store_true", help="print the department / type / part lists and exit")
    ap.add_argument("--dept", help="department name or id, e.g. FINANCE, 'GENERAL ADMINISTRATION', 27")
    ap.add_argument("--type", default="1", help="gazette type id/name (1 Extraordinary, 2 Weekly)")
    ap.add_argument("--part", help="gazette part id/name, e.g. 9 (Part IV-B)")
    ap.add_argument("--year"); ap.add_argument("--month")
    ap.add_argument("--from", dest="dfrom"); ap.add_argument("--to", dest="dto")
    ap.add_argument("--number", help="gazette number"); ap.add_argument("--text", help="search text (abstract)")
    ap.add_argument("--pick", help="result numbers to save, e.g. 9 or 9,12 (test phase: 1-2). Without it: dry run")
    ap.add_argument("--act", help="if the saved gazette publishes an Act, its Act number (recorded, not guessed)")
    a = ap.parse_args()
    s = requests.Session(); s.headers["User-Agent"] = UA
    action, hidden, selects, dates = get_form(s)
    if a.options:
        print("hidden fields:", list(hidden)); print("date inputs:", dates)
        for name, opts in selects.items():
            print(f"\n{name} ({len(opts)})")
            for v, l in opts: print(f"   {v:<6} {l}")
        return
    data = dict(hidden)
    data.update({"departmentId": pick(selects.get("departmentId", []), a.dept),
                 "gazeeteTypeId": pick(selects.get("gazeeteTypeId", []), a.type),
                 "gazeetePartId": pick(selects.get("gazeetePartId", []), a.part),
                 "year": a.year or "", "month1": a.month or "", "fromdate": a.dfrom or "", "todate": a.dto or "",
                 "gazetteno": a.number or "", "abstract1": a.text or ""})
    if not data["departmentId"]: raise SystemExit("--dept is required (the site refuses a search without a department)")
    print("search:", {k: v for k, v in data.items() if k != "_csrf" and v})
    time.sleep(DELAY)
    try:
        r = s.post(action, data=data, timeout=60, headers={"Referer": BASE + "searchAllGazette"})
    except requests.RequestException as e:
        append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "egazette", "url": action, "error": str(e)[:200], "at": now()})
        raise SystemExit(f"search failed: {e} (logged to failed.jsonl)")
    out = ST / "manifests" / "egazette_last_search.html"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text)
    rows = parse_results(r.text)
    print(f"HTTP {r.status_code} · {len(rows)} results · raw page: {out.relative_to(ROOT)}")
    if not rows:
        print("no results parsed — check the raw page (search may need a different date format; date inputs:", dates, ")")
        return
    files, ids = held_index()
    scope = load_scope()
    for i, row in enumerate(rows, 1):
        flags = []
        if row["file"] in files: flags.append("held")
        ok, why = topic_decision(row["abstract"], scope)
        flags.append(("topic: " + why) if ok else "skip-topic")
        if row["republishes"]:
            gid = republished_id(row["republishes"], (row["date"] or "")[:4], scope)
            flags.append(("republishes " + row["republishes"]) + (" — G.O. already held" if gid in ids else ""))
        print(f"{i:>3}. {row['date'] or '????-??-??'} {part_code(row['part']):<5} No.{row['gazette_no'] or '?':<5} "
              f"{row['abstract'][:95]}  [{'; '.join(flags)}]")
    if not a.pick:
        print("\ndry run — add --pick N (the result number) to save one; --act N if it publishes an Act"); return
    picks = [int(x) for x in a.pick.split(",") if x.strip()]
    saved = 0
    for n in picks[:2]:   # test phase: at most 2 per run
        if not 1 <= n <= len(rows): print(f"no result {n}"); continue
        row = rows[n - 1]
        if row["file"] in files: print(f"{n}: already held ({row['file']})"); continue
        if not (row["gazette_no"] and row["date"]):
            print(f"{n}: gazette number/date unreadable — not saved"); continue
        url = BASE + "uploadGazette_view?filePath=" + quote(row["token"], safe="")
        time.sleep(DELAY)
        try:
            pdf = s.get(url, timeout=90, headers={"Referer": action})
        except requests.RequestException as e:
            append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "egazette", "url": row["file"], "error": str(e)[:200], "at": now()})
            print("download failed (logged):", e); break
        if not pdf.content.startswith(b"%PDF"):
            print(f"{n}: not a PDF (HTTP {pdf.status_code}, {pdf.headers.get('content-type')}) — token may have expired; not saved"); continue
        year = row["date"][:4]; pc = part_code(row["part"])
        cid = canonical_id("GAZ", "GAZETTE", row["gazette_no"], year, filecode=pc)
        assert CANONICAL_RE.match(cid), cid
        meta = {"canonical_id": cid, "doc_type": "Gazette", "instrument": f"A.P. Gazette {row['part']}",
                "number": row["gazette_no"], "date": row["date"], "date_raw": None,
                "department_code": "GAZ", "department_name": "A.P. GAZETTE", "publishing_department": row["dept"],
                "subject": row["abstract"], "issue_no": row["issue_no"], "notification_no": row["notification_no"],
                "republishes": row["republishes"],
                "republishes_id": republished_id(row["republishes"], year, scope), "act_number": a.act,
                "gazette_kind": gazette_kind(row["part"], row["abstract"], a.act)[0],
                "hierarchy_level": gazette_kind(row["part"], row["abstract"], a.act)[1],
                "classification": "UNCLASSIFIED", "status": "unknown", "effective_from": row["date"], "effective_to": None,
                "read_list": [], "language": "en/te", "origin": "public", "source_name": "AP e-Gazette",
                # The site serves files only through a signed token from a search; the stable reference is the
                # file path inside it, so source_url = site + that path (cite with gazette no./part/date).
                "source_url": BASE.rstrip("/") + row["file"], "source_url_direct": False,
                "gazette_file": row["file"], "official_url": None,
                "verification_status": "pending", "parse_confidence": "medium",
                "files": {"original": "order.pdf", "ocr": None},
                "collector": "tools/collect_gazette.py", "collected_via": "manual-target", "collected_at": now()}
        folder = ST / "rule-library" / "gazette" / "GAZ" / year / cid
        if folder.exists(): print(f"{n}: {cid} exists — not overwritten"); continue
        folder.mkdir(parents=True)
        (folder / "order.pdf").write_bytes(pdf.content)
        meta["sha256"] = sha256(folder / "order.pdf")
        text = pdf_text(folder / "order.pdf")
        body = re.sub(r"(?i)part\s+i+\s+extraordinary|registered no\.[^\n]*|notifications by government[-x ]*", "", text).strip()
        if len(body) > 300:
            (folder / "ocr.txt").write_text(text); meta["files"]["ocr"] = "ocr.txt"; meta["ocr_source"] = "PDF text layer (pypdf)"
        else:
            meta["needs_ocr"] = True   # body is a scanned image (seen in Gazette No.137 of 2024) -> Document AI
        write_json(folder / "meta.json", meta); provenance(ST, meta, "web:egazette")
        files.add(row["file"]); saved += 1
        print(f"{n}: saved {cid} ({len(pdf.content):,} bytes; {meta['gazette_kind']}, level {meta['hierarchy_level']}; "
              f"{'text layer' if meta['files']['ocr'] else 'scanned body: needs Document AI'})"
              f"{'  republishes ' + row['republishes'] if row['republishes'] else ''}")
    print(f"saved {saved}")

if __name__ == "__main__":
    main()
