"""Can a script (requests, Playwright or Selenium) fetch from each source? Checks robots.txt rules for the exact
pages we would automate, the crawl delay, and whether the page shows PDF links without JavaScript.
Read-only: fetches robots.txt plus one page per source, 10 s apart.

  .venv/bin/python tools/check_robots.py
"""
import re, time, urllib.robotparser as rp
import requests

UA = "c2-24-fellowship-research/0.1"
SOURCES = {
    "GOIR":            ("https://goir.ap.gov.in", ["/", "/Reports.aspx"]),
    "AP e-Gazette":    ("https://apegazette.cgg.gov.in", ["/", "/searchAllGazette"]),
    "AP Finance GOs":  ("https://apfinance.gov.in", ["/Finance_gos.html"]),
    "APUTF G.O.s":     ("https://www.aputf.org", ["/gos/latest-gos/"]),
    "CAG PAG (A&E) AP": ("https://cag.gov.in", ["/ae/andhra-pradesh/en/page-ae-andhra-pradesh-andhra-pradesh-go-s"]),
    "Internet Archive": ("https://archive.org", ["/advancedsearch.php", "/download/"]),
}

for name, (base, paths) in SOURCES.items():
    print(f"\n== {name}  {base}")
    try:
        r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=20)
        print(f"robots.txt: HTTP {r.status_code}")
        p = rp.RobotFileParser(); p.parse(r.text.splitlines() if r.ok else [])
        delay = p.crawl_delay(UA) or p.crawl_delay("*")
        if delay: print(f"crawl-delay: {delay} s")
        allowed = {}
        for path in paths:
            ok = p.can_fetch(UA, base + path) if r.ok else (r.status_code == 404)  # 404 = no rules
            allowed[path] = ok
            print(f"  {path:<55} {'ALLOWED' if ok else 'DISALLOWED'}")
        if r.ok:
            print("  rules:", " | ".join(l.strip() for l in r.text.splitlines() if l.strip() and not l.startswith("#"))[:400])
    except Exception as e:
        print("robots.txt: unreachable:", e); continue
    time.sleep(10)
    if not allowed[paths[-1]]:   # never fetch a page robots.txt disallows (or when robots.txt is unreadable)
        print("  page: not fetched (disallowed)")
        continue
    try:   # does the page show PDFs without JavaScript? (if yes, requests is enough; no browser needed)
        pg = requests.get(base + paths[-1], headers={"User-Agent": UA}, timeout=30)
        pdfs = len(set(re.findall(r'href="([^"]+\.pdf)"', pg.text, re.I)))
        js = bool(re.search(r"__VIEWSTATE|__doPostBack|ng-app|data-reactroot|id=\"root\"", pg.text))
        print(f"  page HTTP {pg.status_code}, {len(pg.text):,} chars, {pdfs} PDF links in plain HTML, "
              f"{'needs JavaScript/postbacks' if js else 'static HTML'}")
    except Exception as e:
        print("  page: unreachable:", e)
    time.sleep(10)
