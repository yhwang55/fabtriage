#!/usr/bin/env bash
# Round 2: send-back loop, open model everywhere, stress test repeats. Rerunnable (--resume).
# Mac:  caffeinate -i bash scripts/round2.sh
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
# 1. the engineer send-back loop on the level-3 mistakes (cheap)
$PY -m fabtriage feedback --split stress_L3 --resume
# 2. open model (Baseten) on the large set and the stress levels
$PY -m fabtriage eval --method agent --backend baseten --split holdout3 --resume
$PY -m fabtriage recover --method agent --backend baseten --split holdout3 --resume
for L in 0 1 2 3; do
  $PY -m fabtriage eval --method agent --backend baseten --split stress_L$L --resume
  $PY -m fabtriage recover --method agent --backend baseten --split stress_L$L --resume
done
# 3. stress test to three runs per level (Meta)
for L in 0 1 2 3; do
  $PY -m fabtriage eval --method agent --split stress_L$L --repeats 3 --resume
  $PY -m fabtriage recover --method agent --split stress_L$L --repeats 3 --resume
done
$PY -m fabtriage sweep-report
$PY -m fabtriage report --split holdout3
echo "done"
