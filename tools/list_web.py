"""List the PDFs a static source page offers (no downloads). Respects robots.txt; waits max(crawl-delay, 10 s)
between pages. Output: staging/manifests/web_listing_<source>.jsonl plus a summary.

  python tools/list_web.py finance            # AP Finance G.O.s / circulars page
  python tools/list_web.py cag                # PAG (A&E) AP G.O.s page
  python tools/list_web.py aputf --pages 3    # APUTF latest G.O.s, first 3 pages
  python tools/list_web.py all --show 40
"""
import argparse, json, re, time, urllib.robotparser as rp
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
import requests

ROOT = Path(__file__).resolve().parent.parent
UA = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"
SITES = {
    "finance": "https://apfinance.gov.in/Finance_gos.html",
    "cag":     "https://cag.gov.in/ae/andhra-pradesh/en/page-ae-andhra-pradesh-andhra-pradesh-go-s",
    "aputf":   "https://www.aputf.org/gos/latest-gos/",
}
LINK = re.compile(r'<a\b[^>]*href="([^"]+?\.pdf)"[^>]*>(.*?)</a>', re.I | re.S)
INSTR = [("GOMS", r"G\.?\s?O\.?\s?\(?\s?M\.?\s?S\.?\)?"), ("GORT", r"G\.?\s?O\.?\s?\(?\s?R\.?\s?T\.?\)?"),
         ("CIRMEMO", r"cir(?:cular)?\.?\s*memo"), ("MEMO", r"\bmemo"), ("CIRCULAR", r"circular"), ("RULES", r"\brules?\b")]
DATE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d{2})")
YEAR = re.compile(r"\b(20[0-2]\d|19\d\d)\b")

def robots(base):
    p = rp.RobotFileParser()
    try:
        r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=20)
        p.parse(r.text.splitlines() if r.ok else [])
        return p, max(10, int(p.crawl_delay("*") or 0))
    except Exception:
        p.parse([]); return p, 10

def strip(h): return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", h))).strip()

def context(html, start, floor, n=300):   # text before the link, back to the row start or the previous link
    row = max(html.rfind("<tr", 0, start), html.rfind("<li", 0, start), html.rfind("<p", 0, start))
    lo = max(floor, row if row >= 0 else 0, start - n * 6)
    t = strip(html[lo:start])
    return t if len(t) <= n else t[-n:].split(" ", 1)[-1]   # never start mid-word ("hool Education")

def parse(html, page_url):
    out = []; prev = 0
    for m in LINK.finditer(html):
        url = urljoin(page_url, unescape(m.group(1))); text = strip(m.group(2))
        ctx = text if len(text) > 25 else (context(html, m.start(), prev) + " " + text).strip()
        prev = m.end()
        kind = next((k for k, pat in INSTR if re.search(pat, ctx + " " + url, re.I)), None)
        d = DATE.search(ctx) or DATE.search(url)
        year = d.group(3) if d else (YEAR.findall(ctx + " " + url) or [None])[-1]
        out.append({"url": url, "text": ctx if len(ctx) <= 250 else ctx[-250:].split(" ", 1)[-1], "kind_guess": kind,
                    "date_guess": f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None,
                    "year_guess": year})
    return out

def next_page(html, page_url):
    m = re.search(r'<a[^>]+class="[^"]*next[^"]*"[^>]+href="([^"]+)"', html, re.I) or \
        re.search(r'<link[^>]+rel="next"[^>]+href="([^"]+)"', html, re.I)
    return urljoin(page_url, unescape(m.group(1))) if m else None

def run(name, url, pages, show):
    base = re.match(r"https?://[^/]+", url).group(0)
    p, delay = robots(base)
    rows, seen = [], set()
    for i in range(pages):
        if not p.can_fetch(UA, url):
            print(f"[{name}] robots.txt disallows {url} — stopping"); break
        r = requests.get(url, headers={"User-Agent": UA}, timeout=40)
        print(f"[{name}] page {i+1}: HTTP {r.status_code} {url}")
        if not r.ok: break
        for row in parse(r.text, url):
            if row["url"] not in seen:
                seen.add(row["url"]); row["source"] = name; row["page"] = url; rows.append(row)
        url = next_page(r.text, url)
        if not url: break
        time.sleep(delay)
    out = ROOT / "staging" / "manifests" / f"web_listing_{name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    inwin = [x for x in rows if x["year_guess"] and 2018 <= int(x["year_guess"]) <= 2025]
    kinds = {}
    for x in rows: kinds[x["kind_guess"]] = kinds.get(x["kind_guess"], 0) + 1
    years = {}
    for x in rows: years[x["year_guess"]] = years.get(x["year_guess"], 0) + 1
    print(f"[{name}] {len(rows)} PDFs | in 2018–2025: {len(inwin)} | kinds: {kinds}")
    print(f"[{name}] years: {dict(sorted(years.items(), key=lambda k: str(k[0])))}")
    for x in rows[:show]:
        print(f"   {x['year_guess'] or '????'} {x['kind_guess'] or '-':8} {x['text'][:110]}")
    print(f"[{name}] written {out.relative_to(ROOT)}\n")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=list(SITES) + ["all"])
    ap.add_argument("--pages", type=int, default=1, help="follow 'next page' links up to N pages (APUTF)")
    ap.add_argument("--show", type=int, default=25)
    a = ap.parse_args()
    for n in (SITES if a.site == "all" else [a.site]):
        run(n, SITES[n], a.pages, a.show)
