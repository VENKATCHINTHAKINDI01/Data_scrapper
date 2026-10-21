# Coverage check

Real documents in staging: 844  ·  links: 2891

| Need | Status | Evidence | Where the rest comes from |
|---|---|---|---|
| G.O.(Ms) rule library | PASS | 802 orders | Internet Archive mirror (automatic) |
| G.O.(Rt) orders | PASS | 42 (only fetched when cited) | Internet Archive (--cited) |
| Read-list parsed from OCR | PARTIAL | 643/717 orders that have a Read-list (90%) | tools (extract_relations) |
| Citations resolved to orders we hold | PASS | 1245/1749 resolvable citations point inside the corpus; 1142 unresolvable (other depts / GoI memos / Acts) | --cited (depth 1) + hand downloads |
| Supersession chains (conflict A) | PASS | 20 SUPERSEDES links with both orders held: ESE01-GOMS-82-2015→ESE01-GOMS-17-2014, FIN01-GOMS-57-2018→FIN01-GOMS-54-2018, FIN01-GOMS-45-2019→FIN01-GOMS-57-2018, FIN01-GOMS-61-2019→FIN01-GOMS-30-2019 | Internet Archive; synthetic e-files add more |
| Amendments | PASS | 48 AMENDS links with both orders held | Internet Archive |
| Rate series over time (conflict F) | PASS | 41 DA/DR orders: FIN01-GOMS-100-2010, FIN01-GOMS-102-2014, FIN01-GOMS-198-2014, FIN01-GOMS-18-2016, FIN01-GOMS-172-2016 | Internet Archive (dearness topic) + PAG (A&E) AP page by hand |
| Rules / Acts / Gazette above G.O.s (conflict G) | GAP | 0 documents | Internet Archive `--kind gazette` (2 to test) + APeGAZETTE by hand |
| Circulars / memos (conflict C) | GAP | 0 memos | Not in the mirror — AP Finance site, APUTF memos page, GOIR by hand |
| More than one department | PASS | ESE01: 169, FIN01: 369, GAD01: 306 | run tools/run_batches.sh for FIN01, GAD01, ESE01 |
| 2026 orders (latest rules) | GAP | 0; mirror ends 2025-12-12 | APUTF Latest GOs + GOIR by hand |
| OCR text present | PARTIAL | 841/844 with ≥500 chars | archive.org _djvu.txt |
| Metadata (date, section, subject) | PASS | 844/844 | archive description |
| Records needing review | PARTIAL | 6: in.gov.andhra.goir.2018-03-09.E-405876, in.gov.andhra.goir.2019-02-04.E-429090, in.gov.andhra.goir.2020-07-08.E-457973, in.gov.andhra.goir.2020-07-08.E-457975 | GOIR by hand (no PDF in mirror / duplicate numbers) |
| e-Office files + notes (synthetic) | PASS | 24 files, 84 notes (seed + generated) | Not public — synthetic (seed now, Step 8 generator) |
| Receipts / drafts / links (synthetic) | PASS | 12 receipts, 12 drafts, 1 files with links | Not public — Step 8 generator |
| Planted conflicts on real orders (synthetic e-files) | PASS | 8 planted, types A, D, F; B/C/E/G still only in mock seed | generate_efiles.py |
| Movements (synthetic) | PASS | 22 files with movements | Not public — synthetic |
| Officers, sections, access scopes (synthetic) | PASS | 8 (staging) + 8 (mock-v1) | Not public — synthetic |
