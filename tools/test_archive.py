"""Step 4a — discovery test. Prints a few G.O. and gazette records from the Internet Archive mirror.
No downloads. Run:  python tools/test_archive.py
"""
import requests

URL = "https://archive.org/advancedsearch.php"
QUERIES = {
    "G.O.s (identifier prefix in.gov.andhra.goir)": "collection:andhra-goir AND identifier:in.gov.andhra.goir*",
    "Gazette (identifier prefix in.gazette.andhra_new)": "collection:andhra-goir AND identifier:in.gazette.andhra_new*",
}

for label, q in QUERIES.items():
    r = requests.get(URL, params={"q": q, "fl[]": ["identifier", "title", "date"], "rows": 5,
                                  "sort[]": "date desc", "output": "json"}, timeout=30)
    r.raise_for_status()
    resp = r.json()["response"]
    print(f"\n== {label}: {resp['numFound']} found ==")
    for d in resp["docs"]:
        print(f"{d['identifier']} | {d.get('date', '')[:10]} | {d.get('title')}")

print("\nSend the output above if the G.O. block is empty or shows gazette items.")
