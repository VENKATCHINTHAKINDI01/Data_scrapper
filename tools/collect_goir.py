"""GOIR (goir.ap.gov.in) — search, list, and download a few G.O.s / memos.

Site facts (checked 18 Oct 2026): robots.txt "Allow: /"; terms = disclaimer only ("should not be construed as a
statement of law") — no clause against automated access. Search page Reports.aspx is an ASP.NET postback form
(__VIEWSTATE), no captcha. Department option labels start with FIN01 / GAD01 / ESE01 (values FIN / GAD / SE),
order type …DDLGoType (1=MS, 2=RT), category …DdlGo_cat; dates dd-MM-yyyy. Downloads: dgo.ashx?gid=<id>&fileType=E|T.
Results list 'Not issued' numbers (reserved, never used) — skipped.

Test phase: dry run by default (1 GET + 1 search POST, results listed, raw page saved); at most 2 downloads.
  python tools/collect_goir.py --options                         # list every form field and dropdown
  python tools/collect_goir.py --dept FIN01 --type MS --from 01-03-2024 --to 05-03-2024   # dd-MM-yyyy
  python tools/collect_goir.py ... --pick 3                      # save result no. 3
  python tools/collect_goir.py ... --set NAME=VALUE              # set any field by its exact name (see --options)
Raw pages: staging/manifests/goir_form.html, goir_last_search.html (to check the parser).
"""
import argparse, json, re, time, urllib.robotparser as rp
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
import requests
from common import (load_scope, topic_decision, canonical_id, dept_code_for, read_list, normalize_ocr, sha256, now,
                    write_json, append_jsonl, provenance, doc_folder, LEVEL, CANONICAL_RE)
import collect_web as CW   # own_line / own_date / heading_dept / pdf_text — the same header checks as other sources

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "staging"
BASE = "https://goir.ap.gov.in/"
PAGE = BASE + "Reports.aspx"
UA = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"
DELAY = 10
DISCLAIMER = ("GOIR terms: content should not be construed as a statement of law or used for any legal purposes "
              "(General Administration Department, Government of Andhra Pradesh)")
txt = lambda x: re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
attr = lambda tag, a: (re.search(r"\b" + a + r'\s*=\s*["\']([^"\']*)', tag, re.I) or [None, None])[1]

def read_form(html):
    """All fields of the main form: hidden/text inputs, selects (with options), submit buttons."""
    f = re.search(r"<form\b[^>]*>(.*?)</form>", html, re.I | re.S)
    body = f.group(1) if f else html
    fields, selects, texts, buttons = {}, {}, [], []
    for t in re.findall(r"<input\b[^>]*>", body, re.I):
        name, typ = attr(t, "name"), (attr(t, "type") or "text").lower()
        if not name: continue
        if typ == "hidden": fields[name] = unescape(attr(t, "value") or "")
        elif typ in ("text", "date"): texts.append(name); fields.setdefault(name, unescape(attr(t, "value") or ""))
        elif typ in ("submit", "button", "image"): buttons.append((name, unescape(attr(t, "value") or "")))
    for sel in re.finditer(r"<select\b([^>]*)>(.*?)</select>", body, re.I | re.S):
        name = attr(sel.group(1), "name")
        opts = [(unescape(attr(o, "value") or ""), txt(l)) for o, l in
                re.findall(r"<option\b([^>]*)>(.*?)</option>", sel.group(2), re.I | re.S)]
        chosen = re.search(r"<option\b[^>]*selected[^>]*value=\"([^\"]*)\"", sel.group(2), re.I)
        selects[name] = opts; fields[name] = unescape(chosen.group(1)) if chosen else (opts[0][0] if opts else "")
    return fields, selects, texts, buttons

def find_select(selects, test):
    return next((n for n, opts in selects.items() if any(test(v, l) for v, l in opts)), None)

def parse_results(html):
    """Result rows = table rows with a link (PDF, download handler or postback). Cells kept as text."""
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.I | re.S):
        cells = [txt(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.I | re.S)]
        link = re.search(r'href="(?!javascript:)([^"]+\.pdf[^"]*)"', tr, re.I) or \
               re.search(r'href="(?!javascript:)([^"#]+(?:Download|View|GO|aspx\?)[^"]*)"', tr, re.I)
        post = re.search(r"__doPostBack\(\s*&#39;([^&]+)&#39;\s*,\s*&#39;([^&]*)&#39;|__doPostBack\('([^']+)','([^']*)'\)", tr)
        # Reports.aspx results: href='javascript:downloadFile("518259", "E");' -> dgo.ashx?gid=518259&fileType=E
        dl = re.search(r'downloadFile\(\s*"(\d+)"\s*,\s*"E"\s*\)', tr)
        if dl and not link:
            link = re.match(r"(.*)", f"dgo.ashx?gid={dl.group(1)}&fileType=E")
        if len(cells) >= 3 and (link or post):
            row = {"cells": cells, "href": unescape(link.group(1)) if link else None,
                   "postback": ([g for g in post.groups() if g is not None][:2] if post else None)}
            # Reports.aspx columns: S.No | G.O No ("MS-18") | Date (16/02/2024) | Category | Abstract | Organization
            # ("FIN01 - FINANCE") | Section | Amount | English G.O | Telugu G.O
            no = re.match(r"(MS|RT)\s*-\s*(\d{1,5})", cells[1].upper()) if len(cells) > 1 else None
            dt = re.match(r"(\d{2})/(\d{2})/((?:19|20)\d{2})", cells[2]) if len(cells) > 2 else None
            org = re.match(r"([A-Z]{2,6}\d{2})", cells[5]) if len(cells) > 5 else None
            tel = re.search(r'downloadFile\(\s*"(\d+)"\s*,\s*"T"\s*\)', tr)
            row.update({"type": no.group(1) if no else None, "number": no.group(2) if no else None,
                        "date": f"{dt.group(3)}-{dt.group(2)}-{dt.group(1)}" if dt else None,
                        "category": cells[3] if len(cells) > 3 else None,
                        "abstract": cells[4] if len(cells) > 4 else " | ".join(cells),
                        "org": org.group(1) if org else None, "section": cells[6] if len(cells) > 6 else None,
                        "telugu_href": f"dgo.ashx?gid={tel.group(1)}&fileType=T" if tel else None,
                        "not_issued": len(cells) > 4 and cells[4].strip().lower() == "not issued"})
            rows.append(row)
    return rows

def row_cid(row, scope):
    """Canonical ID from the result row itself (type, number, year, department) — used to skip held orders
    BEFORE downloading. The saved ID is still rebuilt from the PDF's own header."""
    if not (row.get("type") and row.get("number") and row.get("date") and row.get("org")): return None
    dc = row["org"] if row["org"] in scope.get("departments", {}) else dept_code_for(row["org"], scope)
    return canonical_id(dc, "GO" + row["type"], row["number"], row["date"][:4]) if dc else None

def held_ids():
    out = {}
    for p in (ST / "rule-library").rglob("meta.json"):
        try: out[p.parent.name] = json.loads(p.read_text()).get("subject") or ""
        except Exception: pass
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--options", action="store_true")
    ap.add_argument("--dept", help="GOIR department value, e.g. FIN01, GAD01, SE")
    ap.add_argument("--type", default="MS", help="MS or RT (G.O. type dropdown); memos may use another option")
    ap.add_argument("--from", dest="dfrom"); ap.add_argument("--to", dest="dto")
    ap.add_argument("--number"); ap.add_argument("--text")
    ap.add_argument("--set", action="append", default=[], help="NAME=VALUE for any field (exact name from --options)")
    ap.add_argument("--pick", help="result numbers to save, e.g. 3 or 3,5 (test phase: max 2). Without it: dry run")
    a = ap.parse_args()
    robots = rp.RobotFileParser()
    r = requests.get(BASE + "robots.txt", headers={"User-Agent": UA}, timeout=20)
    robots.parse(r.text.splitlines() if r.ok else [])
    if not robots.can_fetch(UA, PAGE): raise SystemExit("robots.txt disallows Reports.aspx — stopping")
    s = requests.Session(); s.headers["User-Agent"] = UA
    page = s.get(PAGE, timeout=40); page.raise_for_status()
    (ST / "manifests").mkdir(parents=True, exist_ok=True)
    (ST / "manifests" / "goir_form.html").write_text(page.text)
    fields, selects, texts, buttons = read_form(page.text)
    if a.options:
        print("hidden:", [k for k in fields if k.startswith("__")])
        print("text inputs:", texts); print("buttons:", buttons)
        for n, opts in selects.items():
            print(f"\nselect {n} ({len(opts)})")
            for v, l in opts[:60]: print(f"   {v:<10} {l[:70]}")
        return
    dsel = find_select(selects, lambda v, l: v in ("FIN01", "GAD01") or l.startswith(("FIN01", "GAD01")))
    tsel = next((n for n in selects if n.endswith("DDLGoType")), None) or \
        find_select(selects, lambda v, l: l.upper() in ("MS", "RT"))
    if a.dept:
        if not dsel: raise SystemExit("department dropdown not found — run --options and use --set")
        val = next((v for v, l in selects[dsel] if v == a.dept or l.upper().startswith(a.dept.upper())), None)
        if val is None: raise SystemExit(f"{a.dept} not in department options: {[l for _, l in selects[dsel]][:50]}")
        fields[dsel] = val
    if tsel and a.type:
        fields[tsel] = next((v for v, l in selects[tsel] if v.upper() == a.type.upper() or l.upper() == a.type.upper()), fields[tsel])
    low = {t.lower(): t for t in texts}
    def put(keys, value):
        if value is None: return
        name = next((low[k] for k in low if any(x in k for x in keys)), None)
        if name: fields[name] = value
        else: print(f"   note: no text field for {keys} — use --set")
    put(("from", "fdate", "frm"), a.dfrom); put(("to", "tdate"), a.dto)
    put(("gono", "go_no", "number", "txtno"), a.number); put(("search", "text", "subject", "abstract"), a.text)
    for kv in a.set:
        k, v = kv.split("=", 1); fields[k] = v
    btn = next((b for b in buttons if re.search(r"search|submit|go|show|get", (b[0] + b[1]), re.I)), buttons[0] if buttons else None)
    if btn: fields[btn[0]] = btn[1]
    print("search:", {k: v for k, v in fields.items() if not k.startswith("__") and v})
    time.sleep(DELAY)
    try:
        res = s.post(PAGE, data=fields, timeout=60, headers={"Referer": PAGE})
    except requests.RequestException as e:
        append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "goir", "url": PAGE, "error": str(e)[:200], "at": now()})
        raise SystemExit(f"search failed (logged): {e}")
    (ST / "manifests" / "goir_last_search.html").write_text(res.text)
    rows = parse_results(res.text)
    print(f"HTTP {res.status_code} · {len(rows)} result rows · raw page: staging/manifests/goir_last_search.html")
    if not rows:
        msg = re.search(r"(?i)(no (?:records?|data)[^<]{0,60})", res.text)
        print("no rows parsed" + (f" — page says: {msg.group(1)}" if msg else " — send me the raw page")); return
    scope, held = load_scope(), held_ids()
    for i, row in enumerate(rows, 1):
        flags = []
        if row.get("not_issued"): flags.append("NOT ISSUED (number reserved, never used) — skipped")
        else:
            cid = row_cid(row, scope)
            if cid and cid in held: flags.append(f"held: {cid}")
            ok, why = topic_decision(row.get("abstract") or "", scope)
            flags.append(("topic: " + why) if ok else "skip-topic")
        print(f"{i:>3}. {row.get('type') or '?'}-{row.get('number') or '?':<5} {row.get('date') or '????-??-??'} "
              f"{row.get('org') or '?':<6} {(row.get('abstract') or '')[:95]}  [{'; '.join(flags)}]")
    if not a.pick:
        print("\ndry run — add --pick N to save one (test phase: max 2)"); return
    fields2, _, _, _ = read_form(res.text)   # fresh __VIEWSTATE for postbacks from the results page
    saved = 0
    for n in [int(x) for x in a.pick.split(",") if x.strip()][:2]:
        if not 1 <= n <= len(rows): print(f"no result {n}"); continue
        row = rows[n - 1]
        if row.get("not_issued"): print(f"{n}: 'Not issued' — nothing to download"); continue
        pre = row_cid(row, scope)
        if pre and pre in held and (CW.same_subject(held[pre], row.get("abstract") or "") or not row.get("abstract")):
            print(f"{n}: already held: {pre} (checked from the result row — not downloaded)"); continue
        time.sleep(DELAY)
        try:
            if row["href"]:
                pdf = s.get(urljoin(PAGE, row["href"]), timeout=90, headers={"Referer": PAGE})
            else:
                d = dict(fields2); d["__EVENTTARGET"], d["__EVENTARGUMENT"] = row["postback"][0], row["postback"][1]
                pdf = s.post(PAGE, data=d, timeout=90, headers={"Referer": PAGE})
        except requests.RequestException as e:
            append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "goir", "url": str(row["href"] or row["postback"]),
                         "error": str(e)[:200], "at": now()}); print("download failed (logged):", e); break
        if not pdf.content.startswith(b"%PDF"):
            print(f"{n}: not a PDF (HTTP {pdf.status_code}, {pdf.headers.get('content-type')}) — the link may open a viewer page; "
                  "saved as goir_last_open.html"); (ST / "manifests" / "goir_last_open.html").write_bytes(pdf.content); continue
        tmp = ST / "manifests" / "goir_tmp.pdf"; tmp.write_bytes(pdf.content)
        text = CW.pdf_text(tmp)
        if len(text.strip()) < 200:
            print(f"{n}: scanned PDF — kept in _review/goir for Document AI")
            rev = ST / "_review" / "goir"; rev.mkdir(parents=True, exist_ok=True)
            (rev / f"result-{n}-{int(time.time())}.pdf").write_bytes(pdf.content)
            append_jsonl(rev / "pending_ocr.jsonl", {"row": row["cells"], "at": now()}); tmp.unlink(); continue
        kind, own = CW.own_line(text); dept, head = CW.heading_dept(text, scope); dm = CW.own_date(text, own)
        if not (own and dept and dm):
            print(f"{n}: own line / department / date not readable (own={bool(own)}, dept={dept}, date={bool(dm)}) -> _review")
            rev = ST / "_review" / "goir"; rev.mkdir(parents=True, exist_ok=True)
            (rev / f"result-{n}-{int(time.time())}.pdf").write_bytes(pdf.content); tmp.unlink(); continue
        typ = "GOMS" if kind == "MS" else "GORT"
        number = own.group(1) if own.re is CW.GOMS else re.search(r"(\d{1,5})", text[own.end():own.end() + 12]).group(1)
        date = CW.iso(dm); cid = canonical_id(dept, typ, number, date[:4])
        assert CANONICAL_RE.match(cid), cid
        if cid in held:
            same = CW.same_subject(held[cid], " | ".join(row["cells"])) or CW.same_subject(held[cid], text[:1500])
            print(f"{n}: {'already held' if same else 'ID COLLISION (different order) -> _review'}: {cid}")
            if not same:
                rev = ST / "_review" / "goir"; rev.mkdir(parents=True, exist_ok=True)
                (rev / f"{cid}-collision.pdf").write_bytes(pdf.content)
            tmp.unlink(); continue
        meta = {"canonical_id": cid, "doc_type": "Government Order", "instrument": "G.O.(Ms)" if typ == "GOMS" else "G.O.(Rt)",
                "number": str(int(number)), "date": date, "date_raw": dm.group(0),
                "printed_date": date, "archive_date": None, "date_source": "document_printed_date",
                "date_mismatch": False, "date_verification_status": "auto_extracted",
                "date_evidence": {"method": "PDF text layer (pypdf)", "page": 1, "text": re.sub(r"\s+", " ", text[own.start():dm.end()])[:120]},
                "department_code": dept, "department_name": scope["departments"][dept]["name"], "dept_evidence": head,
                "subject": (row.get("abstract") or " | ".join(row["cells"]))[:500], "hierarchy_level": LEVEL[typ],
                "section": row.get("section"), "category": row.get("category"),
                "telugu_url": urljoin(PAGE, row["telugu_href"]) if row.get("telugu_href") else None,
                "classification": "UNCLASSIFIED", "status": "unknown", "effective_from": date,
                "effective_from_source": "assumed_issue_date", "effective_to": None,
                "read_list": read_list(normalize_ocr(text[:6000])), "language": "en/te", "origin": "public",
                "source_name": "GOIR (goir.ap.gov.in)", "source_url": PAGE, "source_disclaimer": DISCLAIMER,
                "official_url": urljoin(PAGE, row["href"]) if row["href"] else None,
                "verification_status": "pending", "parse_confidence": "high",
                "files": {"original": "order.pdf", "ocr": "ocr.txt"}, "ocr_source": "PDF text layer (pypdf)",
                "collector": "tools/collect_goir.py", "collected_via": "manual-target", "collected_at": now()}
        folder = doc_folder(ST, "goir-direct", meta); folder.mkdir(parents=True, exist_ok=True)
        tmp.replace(folder / "order.pdf"); (folder / "ocr.txt").write_text(normalize_ocr(text))
        meta["sha256"] = sha256(folder / "order.pdf"); write_json(folder / "meta.json", meta); provenance(ST, meta, "web:goir")
        held[cid] = meta["subject"]; saved += 1
        print(f"{n}: saved {cid} ({head}; {date})")
    print(f"saved {saved}")

if __name__ == "__main__":
    main()
