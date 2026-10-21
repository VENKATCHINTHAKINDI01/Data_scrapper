"""Reconcile each G.O.'s issue date: the date printed on the order's own G.O. line vs the date the source recorded.

Rule (agreed 18 Oct 2026):
  - `date` (the document date used for sorting and the canonical ID) becomes the PRINTED date only when it is
    corroborated: it equals the archive date, or a second independent source agrees (e.g. an APUTF file name
    "...-Dt.02.09.2021"), or a person verified it. Otherwise `date` keeps the archive date and the record is
    flagged `date_mismatch: true`, `date_verification_status: needs_review`.
  - Both dates and the evidence are always kept: printed_date, archive_date, date_source, date_mismatch,
    date_verification_status, date_evidence {method, page, text}.
  - Unreadable printed date -> status "printed_unreadable"; nothing is guessed.
  - The issue date is NOT the effective date. `effective_from` stays as recorded but is labelled
    `effective_from_source: "assumed_issue_date"` until an effective date is extracted or verified.

  python tools/reconcile_dates.py            # report only
  python tools/reconcile_dates.py --write    # write the fields (+ staging/manifests/date_review.csv)
  python tools/reconcile_dates.py --verify AP-GAD01-GOMS-95-2021 --as printed   # a person's decision
"""
import argparse, csv, json, re
from pathlib import Path
import collect_web as CW

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "staging"

def corroborations(cid, number, printed):
    """Second sources for the printed date: web listings whose file name or title carries the same number + date."""
    out = []
    if not printed: return out
    y, mth, d = printed.split("-")
    pats = [f"{int(d):02d}.{mth}.{y}", f"{int(d):02d}-{mth}-{y}", f"{int(d)}.{int(mth)}.{y}", f"{d}{mth}{y}"]
    for lf in (ST / "manifests").glob("web_listing_*.jsonl"):
        for line in lf.read_text().splitlines():
            if not line.strip(): continue
            r = json.loads(line); blob = (r.get("url", "") + " " + r.get("text", "")).replace("_", " ")
            if re.search(r"(?i)\bN[Oo][.\s_-]*0*" + str(int(number)) + r"\b", blob) and any(p in blob for p in pats):
                out.append({"source": lf.stem.replace("web_listing_", ""), "url": r.get("url")})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", help="canonical ID a person has checked against the order")
    ap.add_argument("--as", dest="as_", choices=["printed", "archive"], help="which date the person confirmed")
    a = ap.parse_args()
    if a.verify:
        mp = next((ST / "rule-library").rglob(f"{a.verify}/meta.json"))
        m = json.loads(mp.read_text())
        chosen = m.get("printed_date") if a.as_ == "printed" else m.get("archive_date")
        if not chosen or chosen[:4] != str(m["date"])[:4]:
            raise SystemExit("refused: no such date recorded, or the year would change (canonical ID) — handle by hand")
        m.update({"date": chosen, "date_source": f"verified_{a.as_}", "date_verification_status": "verified"})
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2)); print("verified", a.verify, chosen); return
    rows, stats = [], {}
    for mp in sorted((ST / "rule-library").rglob("meta.json")):
        m = json.loads(mp.read_text())
        if m.get("date_source", "").startswith("verified"):
            stats["already verified"] = stats.get("already verified", 0) + 1; continue
        archive = m.get("archive_date") or str(m.get("date") or "") or None
        ocr = mp.parent / ((m.get("files") or {}).get("ocr") or "ocr.txt")
        text = ocr.read_text(errors="ignore") if ocr.exists() else ""
        printed = ev = None
        if text and m.get("instrument") in ("G.O.(Ms)", "G.O.(Rt)"):
            kind, own = CW.own_line(text)
            if own and (kind == "MS") == (m["instrument"] == "G.O.(Ms)") and own.re is CW.GOMS and \
                    int(own.group(1)) == int(m.get("number") or -1):
                dm = CW.own_date(text, own); printed = CW.iso(dm)
                if dm: ev = {"method": m.get("ocr_source") or "text layer", "page": 1,
                             "text": re.sub(r"\s+", " ", text[own.start():dm.end()])[:120]}
        upd = {"printed_date": printed, "archive_date": archive, "date_evidence": ev}
        if not printed:
            upd.update(date_source="archive_metadata", date_mismatch=None, date_verification_status="printed_unreadable")
            key = "printed date unreadable (archive date kept)"
        elif printed == archive:
            upd.update(date=printed, date_source="document_printed_date", date_mismatch=False,
                       date_verification_status="auto_agree")
            key = "printed = archive"
        else:
            corr = corroborations(m["canonical_id"], m["number"], printed)
            if corr and printed[:4] == archive[:4]:
                upd.update(date=printed, date_source="document_printed_date", date_mismatch=True,
                           date_verification_status="corroborated", date_corroboration=corr)
                key = "mismatch, printed corroborated by a 2nd source -> printed used"
            else:
                upd.update(date_source="archive_metadata", date_mismatch=True, date_verification_status="needs_review")
                key = "mismatch -> needs review (archive date kept)"
            rows.append({"canonical_id": m["canonical_id"], "archive_date": archive, "printed_date": printed,
                         "status": upd["date_verification_status"], "evidence": (ev or {}).get("text", ""),
                         "corroboration": "; ".join(c["source"] for c in corr) if corr else ""})
        if m.get("effective_from") and m.get("effective_from_source") in (None, "assumed_issue_date"):
            # an ASSUMED effective date follows the document date; an extracted/verified one is never touched
            upd["effective_from_source"] = "assumed_issue_date"
            upd["effective_from"] = upd.get("date", m.get("date"))
        stats[key] = stats.get(key, 0) + 1
        if a.write:
            m.update(upd); mp.write_text(json.dumps(m, ensure_ascii=False, indent=2))
    for k, v in sorted(stats.items(), key=lambda x: -x[1]): print(f"{v:>5}  {k}")
    for r in rows: print(f"   {r['canonical_id']:<26} archive {r['archive_date']}  printed {r['printed_date']}  {r['status']}"
                         f"{'  (' + r['corroboration'] + ')' if r['corroboration'] else ''}")
    if a.write:
        out = ST / "manifests" / "date_review.csv"
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["canonical_id"]); w.writeheader(); w.writerows(rows)
        print(f"written; mismatches listed in {out.relative_to(ROOT)}")
    else:
        print("report only — add --write to record the fields")

if __name__ == "__main__":
    main()
