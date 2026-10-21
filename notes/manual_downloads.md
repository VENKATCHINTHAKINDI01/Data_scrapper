# Hand downloads — what the internet has but scripts can't fetch (14 Oct 2026)

Bulk collection is **stopped** (69 real orders are enough to verify the pipeline).
Download only the items below, save each PDF in `inbox/`, then register it with `tools/add_manual.py`
(give the exact document URL, never the site homepage). Then run:

```
python tools/extract_relations.py staging && python tools/validate.py staging && python tools/check_coverage.py
```

## 1. GOIR — https://goir.ap.gov.in/  (18 Oct: robots.txt allows all; terms read — no prohibition on automated access; disclaimer: not a statement of law. Collector to be built and tested on 2 documents)
Search by department + G.O. number + date, open the order, save the PDF.

| Order | Why we need it | Command after saving |
|---|---|---|
| G.O.Ms.No.126, Finance (HR-III Pension), 01-12-2023 — DR to judicial pensioners | Second order with number 126 of 2023; the DA/DR series needs it | needs an ID suffix — send me the PDF first |
| G.O.Ms.No.124, Finance (IF), 23-04-2009 | Cited by GOMS-204-2016 and GOMS-110-2023; not in mirror | `--source goir --type GOMS --number 124 --date 23-04-2009 --dept FIN01` |
| G.O.Ms.No.653, Finance (Pension.I), 22-09-2004 | Cited by GOMS-82-2023 (with 654, 655 of the same day); not in mirror | `--source goir --type GOMS --number 653 --date 22-09-2004 --dept FIN01` |
| G.O.Ms.No.59, Finance & Planning, 30-03-2001 | Cited by GOMS-101-2015; not in mirror | `--type GOMS --number 59 --date 30-03-2001 --dept FIN01` |

Lowest priority: the three pre-2010 orders. Skip them if GOIR does not show older years.

Skipped on purpose (individual cases, not rules): G.O.Ms.No.66 and G.O.Rt.No.1770 of 08-07-2020 (departmental
proceedings against one officer; in `_review/` because the mirror has no PDF) and Memo FIN04-36/18/2018 (Director of
Insurance, one officer's case).

## 2. AP Finance Department — https://apfinance.gov.in/Finance_gos.html  (and GOIR "Memos")
Circular memos are not G.O.s, so the archive mirror never has them. Needed for conflict type C.

| Memo | Cited by | Command |
|---|---|---|
| Cir. Memo No.FIN01-COOROMISC/93/2023-CASPS-FC, 05-03-2024 | GOMS-95-2024 | `--source circulars --type CIRMEMO --filecode FIN01-COOROMISC --number 93 --fileyear 2023 --date 05-03-2024 --dept FIN01` |
| Cir. Memo No.FIN01-COOROMISC/93/2023-CASPS-FC, 26-06-2024 | GOMS-95-2024 | same, `--date 26-06-2024` |
| "Processing of files in e-Office — File Codes, Functional Heads & General Heads" (GAD, 2018) | Realistic e-File numbers for the synthetic files | save to `inbox/` only (reference, not a rule) |

If these memos are not on the Finance page, search GOIR → Memos, or skip: synthetic e-files can carry circulars.

## 3. APUTF — not needed (decision 16 Oct 2026)
The corpus is frozen as of 31-12-2025; no 2026 orders are collected.

## 4. Gazette (rules / Acts above G.O.s — conflict type G)
Try the archive first (a 2-item test, not a bulk run):

```
python tools/collect_ia.py --kind gazette --from 2024-11-29 --to 2024-11-29 --limit 2 --dry-run
```

Target: **A.P. Public Employment (Regulation of Age of Superannuation) (Amendment) Act, 2024 (Act No.13 of 2024),
Gazette Part IV-B Extraordinary No.13, 29-11-2024** — the Act GOMS-97-2024 implements.
If the dry run doesn't list it, download it by hand from **https://apegazette.cgg.gov.in/** (Part IV-B Extraordinary)
and register with `--source gazette --type RULE --number 13 --date 29-11-2024 --dept GAZ`.

## 5. PAG (A&E) AP — https://cag.gov.in/ae/andhra-pradesh/en/page-ae-andhra-pradesh-andhra-pradesh-go-s
Optional. We already hold 8 DA/DR orders from the archive (2022–2024). Use PAG only for
pre-2015 DR orders if the temporal demo needs a longer chain.

## Not on the internet at all → synthetic (Step 8)
e-Office notings, receipts, drafts, movements, file links, officers and access scopes. Never public; the seed
covers files, notes, movements and officers; receipts, drafts and links come from the Step 8 generator.

## Not needed
e-Procurement G.O. page (robots blocks it; no conflict value for C2-24 scope).
