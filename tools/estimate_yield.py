"""How many orders would the filters keep? Counts per department and year from search results only (no downloads).

  python tools/estimate_yield.py                      # FIN01 GAD01 ESE01, 2018-2025
  python tools/estimate_yield.py --dept ESE01 --years 2024 --show 15   # with sample abstracts

Columns: all records; G.O.(Ms) / (Rt); how many of each pass keep_topics + skip_topics; how many were excluded
as individual cases. Use it to decide per-department order_types and the realistic corpus size.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import load_scope, topic_decision  # noqa: E402
from collect_ia import PREFIX, parse_description, search, text_of  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", action="append")
    ap.add_argument("--years", nargs="*", type=int, default=list(range(2025, 2017, -1)))
    ap.add_argument("--show", type=int, default=0, help="print N kept and N excluded abstracts per dept-year")
    a = ap.parse_args()
    scope = load_scope()
    depts = a.dept or ["FIN01", "GAD01", "ESE01"]
    print(f"{'dept':<6} {'year':<5} {'all':>5} {'Ms':>5} {'Rt':>5} {'Ms kept':>8} {'Rt kept':>8} {'excluded':>9}")
    tot = {}
    for d in depts:
        for y in a.years:
            q = (f"collection:andhra-goir AND identifier:{PREFIX['go']}* AND title:({d}) "
                 f"AND date:[{y}-01-01 TO {y}-12-31]")
            n = ms = rt = kms = krt = exc = 0
            samples_k, samples_x = [], []
            for doc in search(q, 10_000, fields=("identifier", "title", "description")):
                n += 1
                desc = parse_description(text_of(doc.get("description")))
                kind = "RT" if "routine" in (desc.get("order_type") or str(doc.get("title"))).lower() else "MS"
                ms += kind == "MS"; rt += kind == "RT"
                ok, why = topic_decision(desc.get("abstract") or "", scope)
                if ok:
                    if kind == "MS":
                        kms += 1
                    else:
                        krt += 1
                    samples_k.append(f"  + {kind} {why:<18} {(desc.get('abstract') or '')[:110]}")
                elif why.startswith("excluded"):
                    exc += 1
                    samples_x.append(f"  - {kind} {why:<18} {(desc.get('abstract') or '')[:110]}")
            print(f"{d:<6} {y:<5} {n:>5} {ms:>5} {rt:>5} {kms:>8} {krt:>8} {exc:>9}")
            t = tot.setdefault(d, [0, 0])
            t[0] += kms; t[1] += krt
            if a.show:
                print("\n".join(samples_k[:a.show] + samples_x[:a.show]))
            time.sleep(1)
    print("\nkept over all years:", {d: {"Ms": v[0], "Rt": v[1]} for d, v in tot.items()},
          "| total Ms", sum(v[0] for v in tot.values()), "| Ms+Rt", sum(sum(v) for v in tot.values()))


if __name__ == "__main__":
    main()
