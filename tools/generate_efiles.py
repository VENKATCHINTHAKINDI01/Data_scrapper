"""Step 8 — generate SYNTHETIC e-Office files that cite REAL G.O.s held in staging/rule-library.

  python tools/generate_efiles.py            # writes staging/efiles, staging/directory, staging/ground-truth
  python tools/generate_efiles.py --check    # plan only: verify every cited order is held, write nothing

Every file follows the e-Office Digital File layout (file.json, Correspondence/, Note File1/, GO/, Drafts/,
Documents/, movements.json, links.json) and carries the SYNTHETIC banner. Each scenario plants at most one
conflict whose answer is provable from real orders we hold (supersession / later order / notified-bank list).
Conflict types needing rules we do not hold yet (B contradiction, E authority, G hierarchy) stay in the
mock seed until the hand downloads arrive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import STAGING, file_slug, load_scope, normalize_ocr, parse_reference, write_json  # noqa: E402

BANNER = "<!-- SYNTHETIC — not a real government file. Cites real public G.O.s. (C2-24 generator v1) -->\n"
SECTIONS = {  # folder code: (department heading used in citations, e-File head, label)
    "HR.I": ("Finance (HR.I-Plg. & Policy) Department", "FIN01-HRPLG0(TRF)", "HR.I – Planning & Policy (Transfers)"),
    "PC-TA": ("Finance (PC-TA) Department", "FIN01-PCTA0(ALW)", "Pay Commission – Allowances"),
    "HR.III": ("Finance (HR.III-Pension, GPF) Department", "FIN01-HRPEN0(DR)", "HR.III – Pension & GPF"),
    "IF": ("Finance (IF) Department", "FIN01-IF0(BNK)", "Institutional Finance"),
}
# Officers (synthetic). post rank: 1 ASO, 2 SO, 3 AS, 4 DS, 5 JS/Addl.Secy, 6 Secretary
OFFICERS = [
    ("F01", "K. Srilatha", "Assistant Section Officer", 1, "HR.I", "Section"),
    ("F02", "B. Ravi Kumar", "Section Officer", 2, "HR.I", "Section Hierarchy"),
    ("F03", "M. Anitha", "Assistant Section Officer", 1, "PC-TA", "Section"),
    ("F04", "P. Venkateswarlu", "Section Officer", 2, "PC-TA", "Section Hierarchy"),
    ("F05", "S. Kalyani", "Section Officer", 2, "HR.III", "Section Hierarchy"),
    ("F06", "D. Prasad Rao", "Section Officer", 2, "IF", "Section Hierarchy"),
    ("F07", "G. Lakshmi Narayana", "Deputy Secretary", 4, "ALL", "Department"),
    ("F08", "R. Sudha Rani, I.A.S", "Secretary to Government", 6, "ALL", "Global"),
]
NAMES = ["Ch. Suresh Babu", "T. Padmavathi", "V. Rama Krishna", "N. Haritha", "K. Nageswara Rao", "P. Swathi",
         "A. Venkata Ramana", "J. Lalitha Kumari", "S. Mohan Rao", "Y. Bhavani", "L. Kiran Kumar", "R. Sailaja"]
POSTS = ["Senior Assistant", "Junior Assistant", "Typist", "Superintendent", "Assistant Section Officer"]
OFFICES = ["Office of the Director of Treasuries and Accounts, Vijayawada", "District Treasury, Guntur",
           "District Treasury, Parvathipuram Manyam", "Pay & Accounts Office, Vijayawada", "District Treasury, Kakinada",
           "Sub-Treasury Office, Mangalagiri"]


# --------------------------------------------------------------------------- scenarios
# cite: orders the noting relies on (canonical IDs). conflict: what the checker must find (or None = clean control).
SCENARIOS = [
    # ---- Transfers (HR.I). Real: relaxation windows and "Husband and Wife cases" clause; ban from 18-06-2022.
    dict(key="TRF-A-2022", section="HR.I", date="2022-06-14", kind="transfer", ground="spouse",
         subject="Request for transfer on spouse grounds", cite=["AP-FIN01-GOMS-45-2019"],
         evidence=[("AP-FIN01-GOMS-45-2019", r"Husband and Wife cases \(only one of the spouses shall be shifted",
                    "2019 guidelines allow transfer in husband-and-wife cases"),
                   ("AP-FIN01-GOMS-116-2022", r"supersession of the orders issued in the references 9th & 10th read above",
                    "116/2022 supersedes the 2019 orders (9th & 10th read: G.O.Ms.45 and 59 of 2019)")],
         conflict=dict(type="A", cited="AP-FIN01-GOMS-45-2019", governing="AP-FIN01-GOMS-116-2022",
                       reason="Note applies the 2019 guidelines (G.O.Ms.No.45); they were superseded by G.O.Ms.No.116 "
                              "of 07-06-2022 before the note was written.")),
    dict(key="TRF-CLEAN-2022", section="HR.I", date="2022-06-17", kind="transfer", ground="spouse",
         subject="Request for transfer on spouse grounds", cite=["AP-FIN01-GOMS-116-2022", "AP-FIN01-GOMS-122-2022"],
         evidence=[("AP-FIN01-GOMS-116-2022", r"Husband and Wife cases \(only one of the spouses shall be shifted",
                    "2022 guidelines allow transfer in husband-and-wife cases"),
                   ("AP-FIN01-GOMS-116-2022", r"ban on transfers shall come into force with effect from 18 June 2022",
                    "note dated before the ban resumes")],
         conflict=None),
    dict(key="TRF-A-2018", section="HR.I", date="2019-06-28", kind="transfer", ground="spouse",
         subject="Request for transfer on spouse grounds", cite=["AP-FIN01-GOMS-57-2018"],
         evidence=[("AP-FIN01-GOMS-57-2018", r"Husband and Wife cases \(only one of the spouses shall be shifted",
                    "2018 guidelines allow transfer in husband-and-wife cases"),
                   ("AP-FIN01-GOMS-45-2019", r"supersession of orders issued in the reference eighth read above",
                    "45/2019 supersedes the 2018 orders (8th read: G.O.Ms.57 of 2018)"),
                   ("AP-FIN01-GOMS-45-2019", r"relaxed for the period from 25. June, 2019 to 5. July, 2019",
                    "note dated inside the 2019 relaxation window")],
         conflict=dict(type="A", cited="AP-FIN01-GOMS-57-2018", governing="AP-FIN01-GOMS-45-2019",
                       reason="Note applies the 2018 guidelines; superseded by G.O.Ms.No.45 of 24-06-2019.")),
    # ---- HRA (PC-TA). Real: 1/2022 para 8 HRA superseded by 27/2022; 69/2023 raises 12%->16% in new district HQs
    #      incl. Parvathipuram; 118/2023 raises 12%->16% only in Mangalagiri-Tadepalli Municipal Corporation area.
    dict(key="HRA-A-2022", section="PC-TA", date="2022-04-12", kind="hra_old", office=1,
         subject="Fixation of House Rent Allowance under Revised Pay Scales 2022", cite=["AP-FIN01-GOMS-1-2022"],
         evidence=[("AP-FIN01-GOMS-1-2022", r"sanction the House Rent Allowance \(HRA\) to the employees of Government of "
                    r"Andhra Pradesh on par with the employees of Central Government", "para 8 of 1/2022 fixes HRA"),
                   ("AP-FIN01-GOMS-27-2022", r"in supersession of the orders relating to House Rent Allowance \(HRA\) at "
                    r"para 8 of G.O.Ms.No.1", "27/2022 supersedes para 8 of 1/2022")],
         conflict=dict(type="A", cited="AP-FIN01-GOMS-1-2022", governing="AP-FIN01-GOMS-27-2022",
                       reason="HRA taken from para 8 of G.O.Ms.No.1 of 2022, which G.O.Ms.No.27 of 20-02-2022 "
                              "superseded for HRA.")),
    dict(key="HRA-F-2023", section="PC-TA", date="2023-07-12", kind="hra12", office=2, place="Parvathipuram",
         subject="Fixation of House Rent Allowance at the place of posting", cite=["AP-FIN01-GOMS-27-2022"],
         evidence=[("AP-FIN01-GOMS-27-2022", r"12% of Basic Pay", "27/2022 has a 12% HRA class"),
                   ("AP-FIN01-GOMS-69-2023", r"enhance the House Rent Allowance \(HRA\) from the existing 12% to 16% in "
                    r"respect of the District headquarters of Parvathipuram", "69/2023 raises Parvathipuram to 16%")],
         conflict=dict(type="F", cited="AP-FIN01-GOMS-27-2022", governing="AP-FIN01-GOMS-69-2023",
                       reason="On 12-07-2023 the note allows 12% HRA at Parvathipuram; G.O.Ms.No.69 of 09-05-2023 had "
                              "already raised HRA there from 12% to 16%.")),
    dict(key="HRA-CLEAN-2023", section="PC-TA", date="2023-12-11", kind="hra16", office=5, place="Mangalagiri",
         subject="Claim for HRA at the enhanced rate", cite=["AP-FIN01-GOMS-118-2023"],
         evidence=[("AP-FIN01-GOMS-118-2023", r"enhance the House Rent Allowance \(HRA\) from the existing 12% to 16% in "
                    r"respect of all State Government Employees working in Mangalagiri", "118/2023 covers Mangalagiri")],
         conflict=None),
    # ---- Dearness Relief (HR.III). Real: 67/2023 DR 20.02% -> 22.75% wef 01.01.2022; 115/2023 22.75% -> 26.39% wef 01.07.2022.
    dict(key="DR-F-2023", section="HR.III", date="2023-11-20", kind="dr_old",
         subject="Arrears of Dearness Relief to a family pensioner", cite=["AP-FIN01-GOMS-67-2023"],
         evidence=[("AP-FIN01-GOMS-67-2023", r"from 20.02% of the Basic Pay to 22.75% of the Basic Pay with effect from 01.01.2022",
                    "67/2023 rate"),
                   ("AP-FIN01-GOMS-115-2023", r"from 22.75% of the Bas\w+ Pay to 26.39% of the Bas\w+ Pay with effect from 01.07.2022",
                    "115/2023 later rate")],
         conflict=dict(type="F", cited="AP-FIN01-GOMS-67-2023", governing="AP-FIN01-GOMS-115-2023",
                       reason="On 20-11-2023 arrears are worked out only at 22.75% (G.O.Ms.No.67); G.O.Ms.No.115 of "
                              "22-10-2023 had raised DR to 26.39% from 01-07-2022.")),
    dict(key="DR-CLEAN-2023", section="HR.III", date="2023-11-27", kind="dr_new",
         subject="Arrears of Dearness Relief to a pensioner", cite=["AP-FIN01-GOMS-67-2023", "AP-FIN01-GOMS-115-2023"],
         evidence=[("AP-FIN01-GOMS-67-2023", r"from 20.02% of the Basic Pay to 22.75% of the Basic Pay with effect from 01.01.2022",
                    "67/2023 rate"),
                   ("AP-FIN01-GOMS-115-2023", r"from 22.75% of the Bas\w+ Pay to 26.39% of the Bas\w+ Pay with effect from 01.07.2022",
                    "115/2023 rate")],
         conflict=None),
    # ---- Bank deposits (IF). Real: list in para 5 of G.O.Ms.124/2009; City Union Sl.49 (126/2019), Bandhan Sl.50
    #      (75/2021, 17-09-2021), DBS Sl.51 (110/2023, 10-10-2023).
    dict(key="BANK-F-2021", section="IF", date="2021-04-08", kind="bank", bank="Bandhan Bank Ltd",
         subject="Proposal of a State undertaking to keep surplus funds in fixed deposit", cite=["AP-FIN01-GOMS-126-2019"],
         evidence=[("AP-FIN01-GOMS-126-2019", r"include the City Union Bank at Serial No 49 in para 5", "list up to Sl.49 in 2019"),
                   ("AP-FIN01-GOMS-75-2021", r"include the Bandhan Bank Ltd at Serial No 50 in para 5",
                    "Bandhan added only on 17-09-2021")],
         conflict=dict(type="F", cited="AP-FIN01-GOMS-126-2019", governing="AP-FIN01-GOMS-75-2021",
                       reason="Bandhan Bank Ltd was not in the notified list on 08-04-2021; it was added at Sl.No.50 of "
                              "para 5 only by G.O.Ms.No.75 of 17-09-2021.")),
    dict(key="BANK-CLEAN-2022", section="IF", date="2022-02-15", kind="bank", bank="Bandhan Bank Ltd",
         subject="Proposal of a State undertaking to keep surplus funds in fixed deposit", cite=["AP-FIN01-GOMS-75-2021"],
         evidence=[("AP-FIN01-GOMS-75-2021", r"include the Bandhan Bank Ltd at Serial No 50 in para 5", "Bandhan notified")],
         conflict=None),
    dict(key="BANK-F-2023", section="IF", date="2023-06-19", kind="bank", bank="DBS Bank India Ltd",
         subject="Proposal of a State undertaking to keep surplus funds in fixed deposit", cite=["AP-FIN01-GOMS-75-2021"],
         evidence=[("AP-FIN01-GOMS-75-2021", r"include the Bandhan Bank Ltd at Serial No 50 in para 5", "list up to Sl.50 in 2021"),
                   ("AP-FIN01-GOMS-110-2023", r"include the DBS Bank India Ltd. at Serial No 51 in para 5",
                    "DBS added only on 10-10-2023")],
         conflict=dict(type="F", cited="AP-FIN01-GOMS-75-2021", governing="AP-FIN01-GOMS-110-2023",
                       reason="DBS Bank India Ltd was not in the notified list on 19-06-2023; it was added at Sl.No.51 of "
                              "para 5 only by G.O.Ms.No.110 of 10-10-2023.")),
    dict(key="BANK-D-2024", section="IF", date="2024-02-12", kind="bank_precedent", bank="DBS Bank India Ltd",
         subject="Proposal of a State undertaking to keep surplus funds in fixed deposit", cite=["AP-FIN01-GOMS-110-2023"],
         precedent="BANK-F-2023",
         evidence=[("AP-FIN01-GOMS-110-2023", r"include the DBS Bank India Ltd. at Serial No 51 in para 5", "DBS now notified")],
         conflict=dict(type="D", cited="BANK-F-2023", governing="AP-FIN01-GOMS-110-2023",
                       reason="An earlier file (2023) on a deposit with the same bank exists; the note says no earlier "
                              "file is available and does not record that the bank was notified only on 10-10-2023.")),
]


# --------------------------------------------------------------------------- helpers
def order_text(cid: str) -> str:
    p = next((STAGING / "rule-library").rglob(f"{cid}/ocr.txt"))
    return re.sub(r"\s+", " ", p.read_text(errors="ignore"))


def find_evidence(cid: str, pattern: str) -> str | None:
    """Quote from the real order's OCR text (raw, then OCR-normalised). None = claim not supported."""
    raw = order_text(cid)
    for t in (raw, re.sub(r"\s+", " ", normalize_ocr(raw))):
        m = re.search(pattern, t, re.I)
        if m:
            return t[max(0, m.start() - 60):m.end() + 60].strip()
    return None


def held_orders() -> dict:
    return {json.loads(m.read_text())["canonical_id"]: json.loads(m.read_text())
            for m in (STAGING / "rule-library").rglob("meta.json")}


def cite_text(cid: str, held: dict, section_hint: str) -> str:
    m = held[cid]
    ins = "Ms" if "-GOMS-" in cid else "Rt"
    head = SECTIONS.get(section_hint, SECTIONS["HR.I"])[0]
    # use the department heading of the cited order's own section where we know it
    for code, (dhead, _, _) in SECTIONS.items():
        sec = str(m.get("section") or "").upper().replace("-", "").replace(".", "")
        key = {"HR.I": "HR1PLG", "PC-TA": "PCTA", "HR.III": "PENSION", "IF": "INSTITUTIONAL"}[code]
        if key in sec or (code == "IF" and "IF" in sec.split(",")):
            head = dhead
            break
    d = dt.date.fromisoformat(m["date"]).strftime("%d-%m-%Y")
    return f"G.O.{ins}.No.{int(m['number'])}, {head}, Dt.{d}"


def ts(day: str, hour: int, minute: int) -> str:
    d = dt.date.fromisoformat(day)
    return f"{d.strftime('%d/%m/%Y')} {((hour - 1) % 12) + 1:02d}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def rupees(n: int) -> str:
    """Indian grouping: 250000000 -> 25,00,00,000"""
    x = str(n)
    head, tail = x[:-3], x[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:]); head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail]) if parts else tail


HUSBAND_WIFE = ("“Husband and Wife cases (only one of the spouses shall be shifted following the prescribed "
                "procedure)”")


def body(sc: dict, who: dict, cites: list[str], prec_file: str | None) -> list[str]:
    """Dealing hand's note. Every statement about an order is a quote or figure verified in that order's text
    (see SCENARIOS[...]["evidence"]); everything else is about the synthetic case."""
    c0 = cites[0]
    k = sc["kind"]
    if k == "transfer":
        return [f"It is submitted that {who['name']}, {who['post']}, {who['office']}, has requested transfer to the station "
                f"where the spouse, also a State Government employee, is working (PUC, p.1).",
                f"The guidelines issued in {c0} (copy placed in References) provide for {HUSBAND_WIFE}.",
                "As verified from the service particulars, the spouse is working at the station requested for and one "
                "clear vacancy exists there. The individual has not availed the spouse facility earlier.",
                "Approval Requested:\n   a) To accede to the request of the individual.\n   b) To approve the draft orders "
                "placed in the draft section.",
                "Submitted for kind perusal and approval."]
    if k == "hra_old":
        return [f"It is submitted that {who['name']}, {who['post']}, {who['office']}, has requested fixation of House Rent "
                f"Allowance under the Revised Pay Scales 2022 (PUC, p.1).",
                f"Para 8 of {c0} (copy placed in References) sanctions HRA on par with the employees of the Central "
                f"Government, at the rates indicated against the cities, towns and other places.",
                "Hence, it is proposed that HRA may be fixed at the rate indicated in para 8 ibid for the place of working. "
                "Draft proceedings are placed in the draft section.",
                "Submitted for kind perusal and approval."]
    if k == "hra12":
        return [f"It is submitted that {who['name']}, {who['post']}, {who['office']}, has requested fixation of House Rent "
                f"Allowance at the place of posting, {sc['place']} (PUC, p.1).",
                f"As per the classification in {c0} (copy placed in References), the place falls in the class for which "
                f"HRA is 12% of Basic Pay.",
                "Hence, it is proposed that HRA may be fixed at 12% of Basic Pay. Draft proceedings are placed in the "
                "draft section.",
                "Submitted for kind perusal and approval."]
    if k == "hra16":
        return [f"It is submitted that {who['name']}, {who['post']}, {who['office']}, working in the {sc['place']}–"
                f"Tadepalli Municipal Corporation area, has requested HRA at the enhanced rate (PUC, p.1).",
                f"As per {c0} (copy placed in References), HRA has been enhanced from the existing 12% to 16% in respect of "
                f"all State Government employees working in the Mangalagiri–Tadepalli Municipal Corporation area. "
                f"The claim is in order.",
                "Submitted for kind perusal and approval."]
    if k in ("dr_old", "dr_new"):
        basic = 30000 + (len(who["name"]) * 1371) % 20000
        if k == "dr_old":
            rate_txt = f"from 20.02% to 22.75% of the Basic Pay with effect from 01.01.2022, as ordered in {c0}"
            arrears = round(basic * (22.75 - 20.02) / 100) * 12
        else:
            rate_txt = (f"from 20.02% to 22.75% with effect from 01.01.2022 as ordered in {c0}, and from 22.75% to 26.39% "
                        f"with effect from 01.07.2022 as ordered in {cites[1]}")
            arrears = round(basic * (22.75 - 20.02) / 100) * 6 + round(basic * (26.39 - 20.02) / 100) * 6
        return [f"It is submitted that Smt./Sri {who['name']}, family pensioner (Basic Pension Rs. {rupees(basic)}/-), has "
                f"requested payment of arrears of Dearness Relief (PUC, p.1).",
                f"Dearness Relief has been revised {rate_txt} (copies placed in References).",
                f"The arrears for the calendar year 2022 have been worked out accordingly at Rs. {rupees(arrears)}/- and the "
                f"statement is placed in Documents.",
                "Submitted for kind perusal and approval."]
    if k in ("bank", "bank_precedent"):
        lines = [f"It is submitted that the Managing Director of a State undertaking has proposed to keep surplus funds "
                 f"of Rs. 25,00,00,000/- (Rupees Twenty Five crore only) in fixed deposit with {sc['bank']}, which has "
                 f"offered a higher rate of interest (PUC, p.1).",
                 f"Deposits of Government funds and funds of State undertakings are regulated by G.O.Ms.No.124, Finance (IF) "
                 f"Department, Dt.23-04-2009, para 5 of which lists the notified banks, as amended from time to time, "
                 f"the latest amendment available in the section being {c0} (copy placed in References)."]
        if prec_file:
            lines.append("No earlier file on the subject is available in the section.")
        lines += ["Approval Requested:\n   a) To permit the undertaking to keep the deposit with the bank proposed.\n"
                  "   b) To approve the draft letter placed in the draft section.",
                  "Submitted for kind perusal and approval."]
        return lines
    raise ValueError(k)


def build(sc: dict, i: int, held: dict, rnd: random.Random, files_by_key: dict) -> tuple[dict, dict | None]:
    sec = sc["section"]
    dhead, fhead, label = SECTIONS[sec]
    year = sc["date"][:4]
    serial = 10 + i * 3
    file_no = f"{fhead}/{serial}/{year}-{sec}"
    comp_no = str(2_400_000 + i * 7919)
    who = {"name": NAMES[i % len(NAMES)], "post": POSTS[i % len(POSTS)],
           "office": OFFICES[sc.get("office", i % len(OFFICES))]}
    cites = [cite_text(c, held, sec) for c in sc["cite"]]
    prec = files_by_key.get(sc.get("precedent"))
    folder = STAGING / "efiles" / "FIN01" / sec / file_slug(file_no)
    for sub in ("Correspondence", "Note File1", "GO", "Drafts", "Documents"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    d0 = dt.date.fromisoformat(sc["date"])
    recv = d0 - dt.timedelta(days=6)
    (folder / "Correspondence" / "R-001.md").write_text(
        BANNER + f"Receipt No. {3000 + i}/{year}/{sec} · Diary date {recv.strftime('%d-%m-%Y')} · Received from: "
        f"{('State Undertaking No.%02d (synthetic)' % i) if sc['kind'].startswith('bank') else who['office']} · "
        f"Mode: e-Office · Marked to: {sec} · PUC\n\n**Sub:** {sc['subject']} – Reg.\n\n"
        + (f"Letter from the Managing Director, State Undertaking No.{i:02d} (synthetic), proposing to keep surplus funds "
           f"in fixed deposit with {sc.get('bank')}. (synthetic text)\n" if sc["kind"].startswith("bank") else
           f"Representation from {who['name']}, {who['post']}, requesting action on the above subject. (synthetic text)\n"))

    aso = next(o for o in OFFICERS if o[4] == sec and o[3] == 1) if any(o[4] == sec and o[3] == 1 for o in OFFICERS) \
        else next(o for o in OFFICERS if o[4] == sec)
    so = next(o for o in OFFICERS if o[4] == sec and o[3] == 2)
    ds, secy = OFFICERS[6], OFFICERS[7]
    chain = [aso, so, ds, secy] if aso != so else [so, ds, secy]
    paras = body(sc, who, cites, prec)
    if sc["kind"].startswith("bank"):
        subj = f"{sc['subject']} with {sc['bank']} – Permission – Reg."
        ref = (f"Lr.No.{100 + i}/Fin/{year}, dt. {recv.strftime('%d-%m-%Y')} of the Managing Director, "
               f"State Undertaking No.{i:02d} (synthetic) (Receipt No. {3000 + i}/{year}/{sec})")
    else:
        subj = f"{sc['subject']} – {who['name']}, {who['post']} – Reg."
        ref = f"Representation dt. {recv.strftime('%d-%m-%Y')} of {who['name']} (Receipt No. {3000 + i}/{year}/{sec})"
    head = f"Subject: {subj}\nRef: {ref}\n****\n"
    # who writes what, in order: (officer, lines, style)  style: "dealer" N) / "officer" N. / "" empty forward
    seq = [(chain[0], paras, "dealer")]
    mids = chain[1:-1]
    discuss = rnd.random() < 0.34 and len(mids) >= 2
    for j, o in enumerate(mids):
        if discuss and o[3] == 4:
            seq += [(o, ["Pl discuss."], "officer"),
                    (chain[0], ["Discussed. As desired, the proposal has been re-examined; the position stated at the "
                                "paras above stands. Resubmitted for orders."], "dealer"),
                    (o, [], "")]
        else:
            seq.append((o, ["May approve."] if (o[3] == 2 and rnd.random() < 0.6) else [], "officer" if o[3] == 2 else ""))
    seq.append((chain[-1], ["Approved."] if rnd.random() < 0.6 else ["Approved. Issue orders."], "officer"))
    movements, n = [], 1
    for k, (o, lines, style) in enumerate(seq):
        day = d0 + dt.timedelta(days=k // 2)
        when = ts(day.isoformat(), 10 + (k % 4) * 2, rnd.randint(0, 59))
        out = []
        for l in lines:
            out.append(f"{n}{')' if style == 'dealer' else '.'} {l}")
            n += 1
        text = (head if k == 0 else "") + "\n".join(out)
        sig = f"\n\n{when}\n{o[1].upper()}\n{o[2].upper()}"
        (folder / "Note File1" / f"note-{k + 1:03d}.md").write_text(BANNER + f"<!-- green -->\nNote # {k + 1}\n{text}{sig}\n")
        nxt = seq[k + 1][0] if k + 1 < len(seq) else None
        movements.append({"note": k + 1, "from": o[0], "name": o[1], "designation": o[2], "at": when,
                          "sent_to": nxt[2] if nxt else None,
                          "remark": ("returned for discussion" if lines == ["Pl discuss."] else
                                     "approved" if nxt is None else "for approval" if (nxt and nxt[3] > o[3]) else "returned")})
    (folder / "Drafts" / "DFA-001.md").write_text(
        BANNER + f"DRAFT — {sc['subject']}\n\nGOVERNMENT OF ANDHRA PRADESH\n{dhead.upper()}\n\n"
        f"Memo No.{file_no}, Dt. (to be dated)\n\nSub: {sc['subject']} – Orders – Reg.\nRef: " + "; ".join(cites) +
        "\n\n(draft text to be completed by the dealing hand)\n")
    write_json(folder / "GO" / "link.json", sc["cite"])
    write_json(folder / "movements.json", movements)
    write_json(folder / "links.json", [{"file_no": prec, "type": "Referred in"}] if prec else [])
    cls = "RESTRICTED" if sc["kind"] in ("transfer", "dr") else "UNCLASSIFIED"
    write_json(folder / "file.json", {
        "file_no": file_no, "computer_no": comp_no, "canonical_id": f"AP-FIN01-NOTE-{fhead.replace('-', '').replace('(', '').replace(')', '')}-{serial}-{year}",
        "subject": subj, "department_code": "FIN01",
        "section": sec, "section_label": label, "classification": cls, "status": "decided",
        "opened": recv.isoformat(), "scenario": sc["key"], "origin": "synthetic",
        "banner": "Synthetic — not a real government file", "cites": sc["cite"],
        "sources": sc.get("_sources", [])})
    gt = None
    if sc["conflict"]:
        c = dict(sc["conflict"])
        if c["type"] == "D":
            c["cited"] = files_by_key[c["cited"]]
        gt = {"file_no": file_no, "note": 1, "scenario": sc["key"], **c, "evidence": sc.get("_sources", [])}
    return {"file_no": file_no, "folder": str(folder.relative_to(STAGING))}, gt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--seed", type=int, default=2424)
    a = ap.parse_args()
    held, scope = held_orders(), load_scope()
    problems = []
    for sc in SCENARIOS:
        for c in sc["cite"]:
            if c not in held:
                problems.append(f"{sc['key']}: cites {c}, not held")
            else:
                back = parse_reference(cite_text(c, held, sc["section"]), "FIN01", scope)
                if not back or back["canonical_id"] != c:
                    problems.append(f"{sc['key']}: citation text for {c} parses back as {back and back['canonical_id']}")
        as_of = str(scope.get("as_of") or "9999-12-31")
        if sc["date"] > as_of:
            problems.append(f"{sc['key']}: dated {sc['date']}, after the corpus as-of date {as_of}")
        sc["_sources"] = []
        for cid, pat, claim in sc.get("evidence", []):
            if cid not in held:
                problems.append(f"{sc['key']}: evidence order {cid} not held")
                continue
            q = find_evidence(cid, pat)
            if not q:
                problems.append(f"{sc['key']}: claim not found in {cid}: {claim!r} /{pat}/")
            else:
                sc["_sources"].append({"order": cid, "claim": claim, "quote": q,
                                       "source_url": held[cid]["source_url"],
                                       "archive_identifier": held[cid].get("archive_identifier")})
        if not sc.get("evidence"):
            problems.append(f"{sc['key']}: no evidence quotes - every scenario must be backed by real order text")
        cf = sc["conflict"]
        if cf and cf["type"] != "D" and cf["governing"] not in held:
            problems.append(f"{sc['key']}: governing order {cf['governing']} not held")
        if cf and cf["type"] in ("A", "F") and held.get(cf["governing"], {}).get("date", "9") > sc["date"] and cf["type"] == "A":
            problems.append(f"{sc['key']}: type A but governing order is dated after the note")
        if cf and cf["type"] == "F" and held.get(cf["governing"], {}).get("date", "0") > sc["date"] \
                and not sc["key"].startswith("BANK"):
            problems.append(f"{sc['key']}: type F but governing order is dated after the note")
    for sc in SCENARIOS:
        for e in sc.get("_sources", []):
            print(f"  {sc['key']:<15} {e['order'][3:]:<20} ✓ {e['claim'][:60]}\n{'':18}“…{e['quote'][:150]}…”")
    for p in problems:
        print("PROBLEM", p)
    print(f"{len(SCENARIOS)} scenarios, {len(problems)} problems")
    if a.check or problems:
        sys.exit(1 if problems else 0)

    if (STAGING / "efiles" / "FIN01").exists() and any((STAGING / "efiles" / "FIN01").rglob("file.json")):
        sys.exit("staging/efiles/FIN01 already has files; move it to _archive/ first")
    rnd = random.Random(a.seed)
    files_by_key, gts, index = {}, [], []
    for i, sc in enumerate(SCENARIOS):
        info, gt = build(sc, i, held, rnd, files_by_key)
        files_by_key[sc["key"]] = info["file_no"]
        index.append({"scenario": sc["key"], **info, "conflict": sc["conflict"]["type"] if sc["conflict"] else None})
        if gt:
            gts.append(gt)
    write_json(STAGING / "directory" / "officers.json", [
        {"user_id": o[0], "name": o[1], "designation": o[2], "rank": o[3], "department": "FIN01", "section": o[4],
         "search_privilege": o[5], "clearance": "CONFIDENTIAL" if o[3] >= 4 else "RESTRICTED", "origin": "synthetic"}
        for o in OFFICERS])
    write_json(STAGING / "ground-truth" / "efiles_conflicts.json", gts)
    write_json(STAGING / "manifests" / "efiles_index.json", index)
    for r in index:
        print(f"{r['scenario']:<16} {r['conflict'] or 'clean':<6} {r['file_no']}")
    print(f"\n{len(index)} synthetic e-files, {len(gts)} planted conflicts -> staging/efiles, ground-truth/efiles_conflicts.json")


if __name__ == "__main__":
    main()
