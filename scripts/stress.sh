#!/usr/bin/env bash
# Stress test across four evidence levels. Safe to rerun (--resume skips finished cases).
# On a Mac:  caffeinate -i bash scripts/stress.sh
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
for L in 0 1 2 3; do
  $PY -m fabtriage eval --method playbook --split stress_L$L
  $PY -m fabtriage eval --method always_hold --split stress_L$L
  for m in monitor_rule reset_recipe keep_recipe oracle; do $PY -m fabtriage recover --method $m --split stress_L$L; done
done
for L in 0 1 2 3; do
  $PY -m fabtriage recover --method agent --split stress_L$L --resume
  $PY -m fabtriage eval --method agent --split stress_L$L --resume
  $PY -m fabtriage eval --method oneshot --split stress_L$L --resume
done
$PY -m fabtriage sweep-report
echo "done"
