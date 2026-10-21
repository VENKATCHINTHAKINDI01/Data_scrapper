#!/usr/bin/env bash
# Collect FIN01, GAD01, ESE01 for 2018–2025 from the archive mirror, then the orders they cite (depth 1).
# Usage:   bash tools/run_batches.sh                 # TEST MODE: 2 new orders per dept-year
#          bash tools/run_batches.sh ESE01           # one department
#          LIMIT=20 bash tools/run_batches.sh GAD01  # fewer orders per year
# Safe to stop (Ctrl+C) and re-run: existing orders are skipped. Logs go to logs/.
# Corpus is frozen as of 31-12-2025 (scope.yaml as_of); no 2026 orders are collected.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
# TEST MODE by default (18 Oct 2026: tools are built and tested on a few files only).
# Full run needs FULL=1:  FULL=1 bash tools/run_batches.sh   (cap 60 per dept-year; highest estimate is 42)
if [ "${FULL:-0}" = "1" ]; then LIMIT=${LIMIT:-60}; else LIMIT=${LIMIT:-2}; echo "TEST MODE: $LIMIT new orders per dept-year (FULL=1 for a full run)"; fi
DEPTS=${*:-FIN01 GAD01 ESE01}
mkdir -p logs

for d in $DEPTS; do
  for y in 2025 2024 2023 2022 2021 2020 2019 2018; do
    echo "== $d $y"
    $PY tools/collect_ia.py --dept "$d" --from "$y-01-01" --to "$y-12-31" --limit "$LIMIT" >> "logs/collect_${d}.log" 2>&1
    grep -E "^seen" "logs/collect_${d}.log" | tail -1
  done
  echo "== $d: links, then cited orders (depth 1)"
  $PY tools/extract_relations.py staging | head -1
  $PY tools/collect_ia.py --cited staging/manifests/missing.txt >> "logs/cited_${d}.log" 2>&1
  grep -E "^seen" "logs/cited_${d}.log" | tail -1
  $PY tools/extract_relations.py staging | head -1
  $PY tools/validate.py staging 2>/dev/null | tail -1
done

echo; echo "== coverage"
$PY tools/check_coverage.py | grep -E "PASS|PARTIAL|GAP"
find staging/rule-library -name meta.json | sed 's|.*rule-library/[a-z]*/||;s|/[0-9]*/AP.*||' | sort | uniq -c
