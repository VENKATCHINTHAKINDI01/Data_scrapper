"""Inspect a search page's form (read-only, one GET, robots.txt respected): form actions/methods, input names,
hidden fields (tokens / ASP.NET __VIEWSTATE), <select> options (e.g. department and gazette-type lists),
captcha, and AJAX/JSON endpoints referenced in scripts. Decides: plain requests POST vs Playwright.

  python tools/inspect_form.py https://apegazette.cgg.gov.in/searchAllGazette
  python tools/inspect_form.py https://goir.ap.gov.in/Reports.aspx
"""
import re, sys, urllib.robotparser as rp
from html import unescape
import requests

UA = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"
url = sys.argv[1]
base = re.match(r"https?://[^/]+", url).group(0)
p = rp.RobotFileParser()
r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=20)
p.parse(r.text.splitlines() if r.ok else [])
if r.ok and not p.can_fetch(UA, url):
    sys.exit(f"robots.txt disallows {url}; not loading it")
s = requests.Session(); s.headers["User-Agent"] = UA
pg = s.get(url, timeout=40); h = pg.text
print(f"HTTP {pg.status_code}  {len(h):,} chars  cookies: {list(s.cookies.keys())}")
txt = lambda x: re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", x))).strip()
attr = lambda tag, a: (re.search(a + r'\s*=\s*["\']([^"\']*)', tag, re.I) or [None, None])[1]

for i, f in enumerate(re.finditer(r"<form\b([^>]*)>(.*?)</form>", h, re.I | re.S)):
    tag, body = f.group(1), f.group(2)
    print(f"\nFORM {i}: method={attr(tag,'method') or 'GET'} action={attr(tag,'action')} id={attr(tag,'id')}")
    for inp in re.finditer(r"<input\b[^>]*>", body, re.I):
        t = inp.group(0); typ = (attr(t, "type") or "text").lower(); val = attr(t, "value") or ""
        print(f"  input  {typ:<9} name={attr(t,'name')!s:<35} id={attr(t,'id')!s:<25} "
              f"value={(val[:40] + '…') if len(val) > 40 else val}")
    for sel in re.finditer(r"<select\b([^>]*)>(.*?)</select>", body, re.I | re.S):
        opts = re.findall(r"<option\b([^>]*)>(.*?)</option>", sel.group(2), re.I | re.S)
        print(f"  select name={attr(sel.group(1),'name')} id={attr(sel.group(1),'id')} ({len(opts)} options)")
        for o, label in opts[:60]:
            print(f"      {attr(o,'value')!s:<14} {txt(label)[:70]}")
    for b in re.finditer(r"<(?:button|input)\b[^>]*(?:type=[\"']?(?:submit|button)|onclick)[^>]*>", body, re.I):
        print(f"  button {txt(b.group(0))[:30]} onclick={attr(b.group(0),'onclick')}")

print("\nSIGNALS")
for name, pat in [("ASP.NET postback (__VIEWSTATE/__doPostBack)", r"__VIEWSTATE|__doPostBack"),
                  ("CSRF/hidden token", r"csrf|_token|authenticity_token|struts\.token"),
                  ("captcha", r"captcha|recaptcha|hcaptcha"),
                  ("Struts/Spring .do / .htm actions", r'["\'][^"\']+\.(?:do|htm|action)\b'),
                  ("jQuery AJAX", r"\$\.(?:ajax|post|get)\(|fetch\(|XMLHttpRequest")]:
    print(f"  {'YES' if re.search(pat, h, re.I) else 'no ':<3} {name}")
eps = sorted(set(re.findall(r'(?:url\s*:\s*|\.(?:post|get)\(\s*|fetch\(\s*|action\s*=\s*)["\']([^"\']{3,120})["\']', h, re.I)))
print("  endpoints in page/scripts:", eps[:30] or "none found")
for src in re.findall(r'<script[^>]+src=["\']([^"\']+)', h, re.I)[:15]:
    print("  script:", src)
