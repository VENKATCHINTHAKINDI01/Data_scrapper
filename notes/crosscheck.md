# Cross-check: Data Collection Plan vs CLAUDE.md / IMPLEMENTATION_PLAN vs tools vs seed — 14 Oct 2026

Seed run: `validate.py seed/mock-v1` → 16 documents + 12 e-files, 0 problems.
`extract_relations.py` vs ground truth → precision 96%, recall 96% (27/28).
- Miss: D16 Telugu photo circular (needs Telugu OCR).
- "Extra": planted unresolvable G.O.Ms.No.104/2026 — correctly listed in missing.txt (feeds conflict type E).

| # | Finding | Fixed in tools | Action left |
|---|---|---|---|
| 1 | Plan doc used REFERS_TO / CANCELS; CLAUDE.md §5.7 uses REFERENCES / REPEALS | Tools use CLAUDE.md vocabulary | Doc Step 6 updated |
| 2 | Mock v1 used CITES, SAME_FILE, CONFLICTS_WITH, CITES_UNRESOLVED | CITES→REFERENCES; same file = one e-file folder; unresolved → missing.txt | Decide: keep CITES as a type? (ADR if yes) |
| 3 | Doc's ID regex rejected memo IDs with file codes (AP-FIN01-CIRMEMO-FIN01HROPDPPOUTS-7-2024) | Regex widened; all 29 mock IDs pass | Doc Step 5 updated |
| 4 | e-File numbers contain "/" → nested folders | Folder slug uses "_"; real number kept in file.json | Doc Step 8 updated |
| 5 | Archive collection mixes gazette (`in.gazette.andhra_new.*`) and G.O.s (`in.gov.andhra.goir.*`) | Collector filters by identifier prefix; `--kind gazette` | Confirm with test_archive.py |
| 6 | meta.json lacked hierarchy level, classification, status, effective dates (CLAUDE.md §5.2) | Unified schema for real + seed | — |
| 7 | Alias "GA" matched inside "GAD01" → wrong department | Word-boundary matching; unknown departments stay unresolved | — |
| 8 | School Education GOIR code unknown | `SE-TBD` in scope.yaml | Read it off GOIR (Step 2) |
| 9 | Real archive title/description format unverified (archive.org blocked from Claude's sandbox) | Collector reads description fields, falls back to the order's own header; `--probe` first | Run probe, send output |
| 10 | Mock v1 has no receipts, drafts, links, search-privilege profiles; e-files only for USD01 | Empty `Correspondence/`, `Drafts/` marked | Step 8 generator |
| 11 | Seed OCR is clean ground-truth text; real OCR is noisier | Noted in meta (`ocr_source`) | Hand-check 20 relations per dept |
| 12 | CLAUDE.md expects `data/synthetic/` and `data/real/` in Project_1 | Folder kept outside | When you say: seed → data/synthetic, staging → data/real or GCS |

## Probe results — 14 Oct 2026 (your run of test_archive.py and --probe 5 --dept FIN01)

| # | Finding | Fix |
|---|---|---|
| 13 | Only 2 of 5 probe hits were FIN01; MAU01, TRB01, ENE01 matched because "Finance" is in their abstracts | Query now filters on the code in the title (`title:(FIN01)`); end-of-run summary shows how many records were skipped for department |
| 14 | Labels vary: `Fin01\n- Finance` (title), `FIN01\n- FINANCE` (description), `ENE01-E- ENERGY` | Code regex is case-insensitive and no longer needs a "-" after the code; tested on all three |
| 15 | Old code could take a department from a word in the abstract | Department is taken from the code in the Department field or title, then the name in the Department field, then the order's own heading — never the abstract |
| 16 | Mirror ends 2025-12-12; scope runs to 2026-09-30 | `archive_latest` in scope.yaml; collector warns; 2026 orders come from APUTF/GOIR via add_manual.py |
| 17 | Every record has .pdf, _djvu.txt (OCR) and .xml metadata | Collector uses .pdf + _djvu.txt; no change |

## Dry run — 14 Oct 2026 (FIN01, 2024, limit 5)

| # | Finding | Fix |
|---|---|---|
| 18 | Department filter now works live: 5 seen, 5 kept, 0 skipped for department | — |
| 19 | All 5 were individual staff orders and 3 were G.O.(Rt); scope.order_types and keep_topics were not applied | Collector now applies both (pre-filters Routine/Manuscript on the search title before fetching metadata); `--all-types`, `--all-topics` to override; summary shows skips by department/type/topic |
| 20 | Dry run did not show the archive identifier, so IDs could not be checked against records | OK lines now print the identifier and the full abstract |
| 21 | Topic "pay" matched "Pay & Accounts Officer" | Replaced with pay scale / pay revision / pay fixation; matching at word starts |

## Dry run 2 — 14 Oct 2026 (FIN01, 2024, limit 5): seen 90, kept 5, skipped dept 0 / type 78 / topic 7
All 5 kept IDs checked by hand against archive.org: number, date, Ms type and FIN01 match.

| # | Finding | Fix |
|---|---|---|
| 22 | "transfer" kept GOMS-95 (Quick Transfers = money) | Replaced by general transfer / transfers of employees, staff, officers / transfer of employees / transfers and postings |
| 23 | GOMS-94 (A.P. Financial Code amendment) skipped | Added code, amendment, procedure, regulations |
| 24 | Budget estimates / Appropriation Act skipped | Kept out on purpose (no conflict value) |

## First real batch — 14 Oct 2026: 5 FIN01 G.O.(Ms) 2024 downloaded, validate 0 problems
OCR is usable (printed PDFs). Relation extraction on real text had errors; fixed and re-tested on the same 5 files:

| # | Finding on real data | Fix | Result on the 5 orders |
|---|---|---|---|
| 25 | OCR swaps 0/O: `G.0.Ms`, `6.0.`, `FINO1` | `normalize_ocr()` before parsing; `fix_codes()` in IDs | GOMS-100 Read 1 now resolves to AP-FIN01-GOMS-101-2015; memo IDs use FIN01 |
| 26 | Two circular memos from one e-File (…/93/2023) got the same ID and the file year | Memo/circular IDs end with the issue date: `…-93-2023-D20240305` | Read 4 and 5 of GOMS-95 are now distinct |
| 27 | Read-list items not split (`1.G.0.Ms…` with no space) and noise lines (`ok ok 2k`, `* KOK`) | Split on numbered items with or without space; drop lines with no 4-letter word | GOMS-94 now 3 items; no junk in edges |
| 28 | Empty item `-` became an edge | Items need at least two words | gone |
| 29 | GOMS-97 marked AMENDS an Act it implements; GOMS-96 marked CLARIFIES a GoI memo it follows | Keywords must say what THIS order does ("in supersession of", "hereby amend", "following amendment is issued", "following clarifications are issued"); subject fallback only for Amendment/Clarification documents | all 18 edges REFERENCES |
| 30 | Orders cited by kept orders (GOMS-98/99 budget) are filtered out by topic | `collect_ia.py --cited staging/manifests/missing.txt` fetches cited G.O.s by department+year, bypassing topic/type filters; reports what is not in the mirror | — |
| 31 | References to other departments (I&CAD, ITEC) and to GoI OMs stay unresolved | Correct per "never guess"; add departments to scope.yaml if wanted | — |

Decision for Project_1 (ADR when you bring data in): canonical memo IDs carry `-D<yyyymmdd>`.
Seed rebuilt with the new memo IDs (old seed moved to _archive/); seed score unchanged, P 96% / R 96%.

## Cited-order fetch — 14 Oct 2026: staging now 12 FIN01 orders, 27 links, validate 0 problems
| # | Finding | Fix |
|---|---|---|
| 32 | `--cited` found nothing: search results give the description on one line, so "Order Number" swallowed the date | Fixed on the Mac by your other session (each field stops at the next label); merged here; "Date" added as a field |
| 33 | archive.org returned HTTP 500 for GOMS-33's PDF twice, then served it | All archive requests retry 3 times (5 s, 15 s, 45 s) before failing |
| 34 | Cited orders cite further orders (GOMS-101-2015 → GOMS-59-2001, Finance & Planning, not in mirror) | Re-run `--cited` after each batch; add what's not in the mirror by hand |
| 35 | Circular memos (FIN01-COOROMISC/93/2023) are not G.O.s, so the mirror doesn't carry them | Get them from the Finance site/GOIR by hand (add_manual.py --type CIRMEMO) |

## 2023 batch + coverage check — 14 Oct 2026: 69 real orders (FIN01 66, GAD01 3), 158 links, validate 0 problems
Bulk collection stopped here on purpose; the goal was to verify the pipeline end to end, not to build the corpus yet.

| # | Finding | Fix |
|---|---|---|
| 36 | Two different FIN01 G.O.Ms.No.126 of 2023 (Budget-I and HR-III Pension DR); second silently skipped as "exists" | Same ID from a different archive record now goes to `_review/` as DUPLICATE ID |
| 37 | `--cited` read a stale missing.txt and found nothing | `--cited` refuses to run if missing.txt is older than the newest order; order is collect → extract_relations → --cited → validate → extract_relations |
| 38 | Each --cited round pulled in older, off-topic orders (9 → 63 → 85 missing) | Depth 1: only citations made by topic-collected orders are followed (`collected_via` in meta.json; existing 69 tagged 35 topic / 34 cited). Remaining followable: 7, none in the mirror |
| 39 | Topic filter missed loans & advances and budget release orders | Added `loans and advances`, `budget release` |
| 40 | meta.json department_name was "FIN01" | Now the scope name (FINANCE) |
| 41 | Coverage check (`tools/check_coverage.py`, `notes/coverage.md`) | PASS: Ms library, Rt, Read-lists 93%, citations 69/97 inside corpus, 3 supersession chains, 8 DA/DR orders, 2 depts, OCR, metadata. GAP: gazette rules, circular memos, 2026 orders (hand downloads — notes/manual_downloads.md); receipts/drafts (Step 8 synthetic) |

## Link verification — 14 Oct 2026 (all 69 orders, every supersession/amendment sentence read)
Signal sentences in OCR: 16. Extracted typed links: 15 (7 SUPERSEDES, 7 AMENDS, 1 REPEALS), all correct on review; 0 false.
Missed: 2 that amend a Rule/Act rather than a G.O. (no G.O. target — acceptable).

| # | Finding | Fix |
|---|---|---|
| 43 | Read-lists with OCR-lost item numbers (`G.O.Ms…` / `.Ms.No…` per line) and `Read:-` headings not parsed | New item = line that starts a reference; `Read:-` accepted; `.Ms.No` → `G.O.Ms.No` |
| 44 | Ordinals as words or OCR junk ("eighth", "1%", "1°", `3"!`, "ist") | Normalised to `Nth` before "read above / cited" |
| 45 | "partial modification of" / "in modification of" not seen as AMENDS; supersession naming the G.O. directly (no "read above") missed | Added; inline target parsed from the G.O. reference after the keyword |
| 46 | GOMS-69-2023 falsely SUPERSEDES (sentence described what the cited order did) | Sentences with "were/was/have/has/had (been) issued" are skipped |
| 47 | "Fin (IF) Dept", "G.A (Cabinet.I)" not resolved | Aliases `Fin`, `G.A` |
| 48 | device copy silently kept old files when re-sent under the same file name | Always re-send under a new name; checksums compared after every copy |

## Step 8 v1 — synthetic e-files on real orders (14 Oct 2026)
`tools/generate_efiles.py`: 12 Finance e-files (HR.I transfers, PC-TA HRA, HR.III DR, IF bank deposits) in the
Digital File layout, each citing real G.O.s held in staging. 8 planted conflicts (A×3, F×4, D×1) + 4 clean controls,
answers in ground-truth/efiles_conflicts.json; 8 synthetic officers with search privileges in directory/officers.json.
Checks: every cited order held and its citation text parses back to the same ID; validate 0 problems;
extract_relations resolves all 12 notes' citations to held orders. B/E/G types wait for hand-downloaded rules.

## Step 8 v1.1 — notes follow real e-Office noting structure (14 Oct 2026)
Compared against a real Budget noting chain (user sample), the NIC eFile 7.0 manual, the APSRTC e-Office manual and
CSMOP noting rules (¶15–17, ¶25). Generator now writes: Subject / Ref / `****` header; `It is submitted that…` with
`1)` paragraphs numbered continuously across notes; `Approval Requested: a) b)`; e-Office referencing (PUC, copy placed
in References) instead of paper flags; signature block = date-time, NAME, DESIGNATION (capitals); empty forwarding
notes; one-line officer remarks ("May approve.", "Approved. Issue orders."); a "Pl discuss" → resubmission loop in about
a third of files; Indian-grouped amounts (Rs. 25,00,00,000/-). Bank files come from an undertaking's MD, not an employee.
Validate 0 problems; all note citations still resolve to held orders.

## Step 8 v1.2 — every claim in a synthetic note is backed by a quote from the real order (14 Oct 2026)
Rule: a scenario is generated only if each factual statement it makes about a G.O. is found in that G.O.'s text
(raw or OCR-normalised); quote + archive.org source URL stored in file.json "sources" and in the ground truth.
Checking v1 against the real texts found wrong assumptions, now fixed:
- HRA-F: G.O.Ms.118/2023 covers only Mangalagiri–Tadepalli MC area; Parvathipuram's 12%→16% is G.O.Ms.69 of 09-05-2023.
- TRF-CLEAN-2022 was dated after "The ban on transfers shall come into force with effect from 18 June 2022" → moved to 17-06-2022.
- Transfer notes now quote the real clause "Husband and Wife cases (only one of the spouses shall be shifted…)".
- DR notes use the real rates: 20.02→22.75% wef 01.01.2022 (67/2023); 22.75→26.39% wef 01.07.2022 (115/2023).
- Bank notes: the notified list is para 5 of G.O.Ms.124/2009; 126/2019, 75/2021, 110/2023 add Sl.49, 50, 51.
Result: 12 scenarios, 25 claims, 25 verified, 0 problems; validate 0 problems.

## ESE01 / GAD01 dry runs — 16 Oct 2026 (2024, limit 8)
| # | Finding | Fix |
|---|---|---|
| 49 | Disciplinary cases kept (pension-cut penalties cite "rule 9 of A.P. Revised Pension Rules" → match pension + rules) | `skip_topics` in scope.yaml (departmental proceedings, allegation, imposition of penalty, cut in pension, dismiss, …) override keep_topics |
| 50 | ~95% of ESE01/GAD01 records are G.O.(Rt); only 3 + 1 rule orders kept from 400 records | `tools/estimate_yield.py` counts Ms/Rt kept per dept-year from search results (no downloads) before deciding order_types / target size |
| 51 | Topic filter ran only after a metadata fetch, and paging stopped at 400 records | Topic decided first from the abstract in the search result; paging cap raised (whole year scanned) |
| 52 | Per-department order types needed | `departments.<CODE>.order_types` in scope.yaml overrides the global `order_types` |
| 53 | Yield estimate (16 Oct): G.O.(Ms) kept 939 (FIN01 410, GAD01 375, ESE01 154); G.O.(Rt) "kept" ~11,000, almost all individual budget releases, postings, retirements and reimbursements | Decision: G.O.(Ms) only; Rt only when a kept order cites it |
| 54 | Individual cases still passed the filter (Sri/Smt/Kum. + name, panels, promotions, medical reimbursement); "disciplinary" excluded "Multi-Disciplinary Committee" and "Tribunal for Disciplinary Proceedings – Delegate the powers" | `skip_patterns` excludes abstracts naming one person (committee/commission names removed first); disciplinary exclusions made specific; `delegat` added to keep topics; 14 real abstracts tested, 0 mismatches |
| 55 | Sample check 2023+2020 (16 Oct): filtered Ms down a third (263 → 179); ~1 in 5 kept Ms still one-off sanctions; `budget release` kept single BROs; `delegat` matched "Members delegation"; GPF ceiling kept only by chance | `budget release` → `comprehensive budget release`; `delegat` → delegation of (financial) powers / delegate the powers; excluded "appointment of (", "administrative sanction for", "creation of (", "permission for filling", "members delegation"; added `provident fund`; 15 sample abstracts, 0 mismatches |
| 56 | Full estimate 2018–2025 (16 Oct): 645 G.O.(Ms) pass (FIN01 246, GAD01 264, ESE01 135); 800 not reachable without individual cases; default LIMIT 35 would drop 24 orders | Target = every Ms order that passes (~550 real rules) plus cited orders; LIMIT 60 per dept-year, per_department_limit 300 (caps only) |
| 57 | Batch spot check (FIN01 2024–25, 41 new orders): mostly real rules, but "Smt.M.Rama Devi" (no space after Smt.) and one-off recruitment permissions ("Filling-up of (10) vacant posts") were kept; earlier batches also hold departmental-proceedings orders from before skip_topics | Name pattern allows no space ("Smt.X"); "promoted to", "filling up of", "filling-up of" excluded; `tools/refilter.py` moves already-kept orders that now fail the filter to `staging/_review/refiltered/` (dry run lists 17); run with --move after the batch |
| 58 | Full requirement audit (CLAUDE.md §5) on 150 orders mid-batch: IDs, folders, dates, Ms-only, PDFs (sha256), OCR, read-lists, duplicates all pass. Gaps: official_url = literal "URL" in all 150 (mirror placeholder); status "unknown" in all; archive OCR has no page breaks and 83/150 PDFs are scans; GOMS-73-2024 (cited gazette) OCR unreadable; 1 failed download (E-517126) | `tools/audit_corpus.py` (report → staging/manifests/audit_report.json; `--fix` nulls the placeholder); collect_ia no longer stores "URL"; status derived from relations at ingestion; page/paragraph locations from Document AI on order.pdf at ingestion (Monday, GCP); retry E-517126 with `--cited` re-run |
| 59 | Source check (18 Oct, `tools/check_robots.py` from your Terminal): GOIR robots.txt is `Allow: /` (earlier "blocked" came from my fetch tool's own refusal, not the site); AP Finance, CAG PAG, e-Gazette have no robots.txt; APUTF allows with 10 s delay. GOIR needs JavaScript/postbacks; Finance (27 PDFs), APUTF (304), CAG (71) are static HTML; e-Gazette entry URL wrong (404) | README and manual_downloads corrected; check_robots.py now skips pages it may not load; static sites → `tools/list_web.py` (list only); GOIR → Playwright after you check its terms of use |
| 60 | Web sources (18 Oct): e-Gazette search = CSRF form POST (captcha only on officer login, not search); GOIR = ASP.NET postback, no captcha; APUTF 304 PDFs (300 in 2018–2025), CAG 71, Finance 27 (no COOROMISC memos). First APUTF trial: titles carry effective dates ("due from 01-01-2024") not issue dates → GOMS-60..63-2025 would have been saved as 2024 | `tools/collect_web.py` (dry run default): issue date only from the PDF's own "G.O.Ms.No.X Dated:" line, department only from the order's heading, Ms only, as_of enforced, already-held IDs skipped, 10 s delay; no PDF date/heading → `_review/web/` |
| 61 | APUTF run (18 Oct): `--limit` counted saves, not downloads, so ~70 already-held PDFs were fetched; then APUTF refused a connection and the run crashed. Audit: GOMS-2200-2022 = same PDF as GORT-2200-2022 (archive metadata mislabelled an IAS postings list as Ms) | collect_web: held/Rt/other-department decided before download from GOIR-style file names (`2025FIN_MS61_E`, `31032020FIN_MS26`, `…-Dt.01.05.2023`) plus subject match when the title names no department → 10 fetches instead of ~81; `--limit` caps downloads; connection errors logged to failed.jsonl, stop after 3 in a row. GOMS-2200-2022 moved to `_review/refiltered/`; "postings of certain" excluded |
| 62 | e-Gazette test (18 Oct, 9 dry-run searches): search works with a department + YEAR; date ranges (DDMMYYYY) return nothing; Act No.13 of 2024 not found under Finance/Law/Legislature (no Part IV-B rows for 2024). Bugs: gazette no. read from the Type/Part column; site dates are "19-jul-2024"; download links are signed tokens (JWT) | collect_gazette.py: columns parsed by position (S.No, Type/Part, Dept, Abstract, Date, Gazette No, Issue No, Notification No, Download), "dd-mon-yyyy" dates, held check on the stable file path inside the token, `--pick N` (max 2) instead of first-N, marks topic and republished G.O.s already held. Act No.13 of 2024: find its department once by hand |
| 63 | e-Gazette 1-file test (18 Oct): saved Gazette Part I Ext. No.137, 30-05-2024 (Finance) = commencement notice of the Regulation of Appointments … (Amendment) Act 2024, not the Act text; body is a scanned image; was stored as level 3 with source_url = search page | collect_gazette: level from content (Act/Part IV-B = 2, rules notified/amended = 3, other notifications = 4), source_url = site + stable file path (`source_url_direct: false`), text layer saved or `needs_ocr: true`; record corrected; relations re-extracted (GOMS-2200-2022 link gone) |
| 64 | e-Gazette 2nd test (18 Oct): Gazette Part I Ext. No.3880, 19-02-2024 = A.P. Government Life Insurance Fund Rules, 2024, full text layer (49 pages); its parent G.O. AP-FIN01-GOMS-18-2024 (16-02-2024) already held. Text-layer rate so far 1 of 2. "republishes" read "…, FROM FINANCE"; no gazette→G.O. link | collect_gazette strips "FROM/Dated" and stores `republishes_id`; extract_relations adds REFERENCES gazette→G.O. (source gazette_republishes); link now in relations.jsonl |
| 65 | CAG/PAG listing (18 Oct): titles say "GO No.239 dt …" with no Ms/Rt, use "RPS"/"DR @"/"DR to" abbreviations, and some files hold several G.O.s ("GO NO.73,75"); 64 of 71 were skipped | collect_web: unmarked "GO No.N" = candidate, type confirmed from the PDF (Rt dropped after download); `--since YEAR` keeps older orders on purpose, labelled `collected_via: older-chain`; multi-G.O. files skipped; keep topics rps, dr @/to/from, da to/from. CAG dry run: 9 candidates (2018–2025), 35 with --since 1993 incl. the RPS chain 1993→2022; APUTF decisions unchanged |
| 66 | CAG 2-file test (18 Oct): RPS 1993 (G.O.239) and RPS 1999 (G.O.156) are image-only scans → _review (correct). Other session fixed a crash (held is a dict now). PAG "Forwarding of Special Seal…" letters carry another order's number; PDFs come from a CloudFront CDN; CAG lists the DR-to-judicial-pensioners G.O.Ms.126 of 2023, whose number collides with held AP-FIN01-GOMS-126-2023 (Budget Estimates) | collect_web: `--match REGEX` for targeted tests; scans listed in `_review/web/<source>/pending_ocr.jsonl` and not re-fetched; robots.txt checked per serving host; same ID + different subject → `_review` as ID collision (no guessed suffix); "forwarding of" excluded |
| 67 | CAG targeted test (18 Oct): "Amendment to G.O.Ms.No.61 dated 20.10.2025" was dropped as "already held" — 61 is the AMENDED order's number (an AMENDS pair lost); "GO No.12 dt 08-01-2025" is a Law G.O.(Rt) with noisy OCR ("GORtNo12", "DFPARTMENT") and went to review over a garbled date instead of being dropped. Regression check also found the department heading regex captured only 2 letters when the heading had no bracket | collect_web: amendment/modification/corrigendum titles never give the own number (taken from the PDF, else review; `amends_ref` kept); post-download order = scanned? → own G.O. line (below the LAST department heading, above Read/ORDER) Rt? → department (whole heading line, OCR-tolerant, split-line names) out of scope? → number → date → window → ID/collision. On 200 archive orders: number+department agree 177/191 (was 140); all differences fail safe to review |
| 68 | Other session (18 Oct): CAG "Amendment to G.O.Ms.No.61" link is the original G.O.Ms.61 (held) — my "lost AMENDS pair" was wrong; own_line() returned slice-relative positions so the date search looked in the wrong place (merged its fix). Date regression on 191 archive orders: 8 would get a wrong date (Read-list dates when the own line had none) | issue date searched only between the own G.O. line and 'Read'; listing/file-name date vs PDF > 3 days apart → `_review` (date conflict). Now 0 Read-list dates; 3 remaining differences are archive metadata vs printed date. audit_corpus reports "issue date in header differs from metadata": 13 in the corpus, mostly 1 day (archive date a day later). GOMs61 copy moved to `_review/web/cag/resolved/` |
| 69 | Header-date reader still took other dates when the own line had none (1987/1999/2013 for 2021–23 orders) | `own_date()`: date must be on the order's own G.O. line (≤80 chars, no other G.O. in between) else review; used by collect_web and audit_corpus. On ALL 784 archive G.O.(Ms): 685 agree on number+department+date, 52 → review (no date on own line), 3 → review (number differs), 7 differ only on date (6 by 1–2 days, GAD-95-2021 02-09 vs 20-09 — printed date vs archive metadata) |
| 70 | Date rule agreed (18 Oct): printed date is the document date only when corroborated; archive date and evidence always kept; issue date ≠ effective date | `tools/reconcile_dates.py --write`: printed_date, archive_date, date_source, date_mismatch, date_verification_status (auto_agree / corroborated / needs_review / printed_unreadable / verified), date_evidence {method, page, text}; `--verify ID --as printed|archive` records a person's decision (refuses a year change). Result: 721 auto_agree, 101 printed_unreadable, 2 corroborated by APUTF (FIN-57-2020, GAD-95-2021, printed used), 6 needs_review (manifests/date_review.csv). `effective_from_source: assumed_issue_date` on all records until effective dates are extracted |
| 71 | GOIR terms read (18 Oct, by Vyas): GAD portal; content "should not be construed as a statement of law or used for any legal purposes"; no clause forbids automated access or bulk download; robots.txt `Allow: /`. Act No.13 of 2024 confirmed from held AP-FIN01-GOMS-97-2024 (Read 1): "A.P. Public Employment (Regulation of Age of Superannuation) (Amendment) Act, 2024 (ACT No.13 of 2024) published in the A.P. Gazette Part-IV-B Extraordinary, No.13, Amaravati, dt.29.11.2024"; it amends the principal Act of 1984. PRS hosts "Bill13of2024AP.pdf" (a Bill, third-party copy, number not yet matched to the Act) and the 1984 Act | GOIR automation allowed → Playwright/postback collector, test phase, ≥10 s, records the GOIR disclaimer. PRS copies may be added only as `origin: unofficial-copy`, `verification_status: pending`, never as the authoritative Act text or a confirmed relationship |
| 72 | GOIR dry run (18 Oct, other session): search works (Finance Ms 16-02-2024 → 4 records: MS-19, MS-18 = held GOMS-18-2024, MS-12/MS-11 "Not issued"); dates dd-MM-yyyy; downloads = GET dgo.ashx?gid=<id>&fileType=E|T; type dropdown is …DDLGoType (1/2) — other session fixed link parsing and the dropdown match | collect_goir: rows parsed into type/number/date/department/section/abstract/Telugu link; "Not issued" skipped; held check from the row BEFORE download (APUTF lesson); dry run shows held/topic flags; help corrected to dd-MM-yyyy |
| 73 | GOIR end-to-end (18 Oct, other session): MS-18 matched as held from the result row (no download); MS-19 first went to review — "Dated:16-02-2024" sits ~92 spaces after "G.O.Ms.No.19" (text-layer padding), beyond own_date's 80-char window; other session widened it to two lines and saved AP-FIN01-GOMS-19-2024 (goir-direct, disclaimer, dgo.ashx URL). Two-lines-only then missed OCR dates split over short lines (101→106 unreadable). GOIR has only Reports.aspx — no memo/circular search | own_date window = max(80 chars, two lines), ≤300, never past Read; reconcile_dates re-written: 723 auto_agree, 100 unreadable, 2 corroborated, 6 needs_review (same 8 as before); leftover review copy moved to `_review/goir/resolved/`. Circular memos (conflict C) are not on GOIR |
