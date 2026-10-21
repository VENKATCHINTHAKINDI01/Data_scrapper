# c2-24-data-tools

Local data workspace for the C2-24 Data Collection Plan. Kept **outside Project_1** until you decide to bring it in.
From Monday (GCP access) the same layout syncs 1:1 to `gs://c2-24-corpus-<project>/`.

## Layout

```
c2-24-data-tools/
├── scope.yaml                 departments, years, size, topics  (Step 1)
├── requirements.txt
├── tools/
│   ├── common.py              canonical IDs, reference parser, provenance helpers
│   ├── test_archive.py        Step 4a  discovery test, no downloads
│   ├── collect_ia.py          Step 4b/7  Internet Archive mirror -> staging/rule-library/goir|gazette
│   ├── add_manual.py          register a PDF you downloaded by hand (APUTF, PAG, Finance, Gazette, GOIR)
│   ├── validate.py            Step 5  checks before upload
│   ├── extract_relations.py   Step 6  Read-list + supersession -> manifests/relations.jsonl
│   └── seed_from_mock.py      builds seed/mock-v1 from the mock corpus
├── inbox/                     drop hand-downloaded PDFs here
├── staging/                   REAL public data (empty until you collect)
│   ├── rule-library/{goir,aputf,pag,finance,gazette,circulars}/<DEPT>/<YEAR>/<canonical-id>/
│   ├── efiles/  directory/  manifests/  ground-truth/  _review/
├── seed/mock-v1/              SYNTHETIC seed in the same layout (16 orders, 12 e-files, 8 officers)
└── notes/                     source_check.md, batches.md, crosscheck.md
```

Each document folder holds `order.pdf` (original bytes), `ocr.txt` and `meta.json`.
Each e-file folder holds `file.json`, `Correspondence/`, `Note File1/`, `GO/`, `Drafts/`, `Documents/`,
`movements.json`, `links.json`. Folder names replace `/` in file numbers with `_`.

## Quick start (run in your own Mac Terminal)

```bash
cd ~/Documents/c2-24-data-tools
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 0. prove the tools on the synthetic seed
python tools/validate.py seed/mock-v1
python tools/extract_relations.py seed/mock-v1 --compare seed/mock-v1/ground-truth/relations.csv

# 1. look at real archive records before collecting (send me this output)
python tools/test_archive.py
python tools/collect_ia.py --probe 5 --dept FIN01

# 2. pilot: five Finance G.O.s
python tools/collect_ia.py --dept FIN01 --from 2024-01-01 --to 2024-12-31 --limit 5 --dry-run
python tools/collect_ia.py --dept FIN01 --from 2024-01-01 --to 2024-12-31 --limit 5

# 3. one hand-downloaded APUTF order
python tools/add_manual.py inbox/<file>.pdf --source aputf --url "<exact PDF link>"

# 4. check and link
python tools/validate.py staging
python tools/extract_relations.py staging
```

## Rules
- **Synthetic data must rest on real references.** Every statement a synthetic note makes about a G.O. (a rate, a date,
  a clause, a supersession) must be backed by a quote found in that G.O.'s text in `staging/rule-library/`.
  `tools/generate_efiles.py` refuses to write a scenario whose quotes are not found, and stores each quote with its
  archive.org source URL in `file.json → sources` and in `ground-truth/efiles_conflicts.json → evidence`.
  Only the case facts (names, offices, amounts of a claim) are invented.
- Public documents only; synthetic content always says SYNTHETIC.
- Current phase (18 Oct 2026): build tools, dry-run them, test on a few files only (`--limit 2`); no bulk downloads. Download tools default to dry run / test mode; a full run needs an explicit flag (`--download`, `FULL=1`).
- GOIR: robots.txt allows all (checked 18 Oct 2026, `User-agent: * | Allow: /`); automate only after reading its terms of use, at one request per 10 s or slower. AP Finance, CAG PAG, AP e-Gazette: no robots.txt (no rules). APUTF: 10 s between requests. Re-check with `tools/check_robots.py` before any new collector.
- Never guess a canonical ID or department: unreadable records go to `staging/_review/`.
- Ground truth stays in `ground-truth/` and is never read by the app.
