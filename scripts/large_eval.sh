#!/usr/bin/env bash
# Runs the large held-out evaluation. Safe to rerun: finished cases are skipped (--resume).
# On a Mac, keep it awake with:  caffeinate -i bash scripts/large_eval.sh
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
$PY -m fabtriage eval --method playbook --split holdout3
$PY -m fabtriage eval --method always_hold --split holdout3
for m in keep_recipe reset_recipe monitor_rule; do $PY -m fabtriage recover --method $m --split holdout3; done
$PY -m fabtriage recover --method agent --split holdout3 --repeats 3 --resume
$PY -m fabtriage eval --method agent --split holdout3 --repeats 3 --resume
$PY -m fabtriage eval --method oneshot --split holdout3 --resume
$PY -m fabtriage eval --method agent_noverify --split holdout3 --resume
$PY -m fabtriage recover --method agent --split holdout2 --hide history --repeats 3 --resume
$PY -m fabtriage recover --method agent --split holdout2 --hide pm_detail --repeats 3 --resume
$PY -m fabtriage recover --method agent --split holdout2 --hide history pm_detail --repeats 3 --resume
$PY -m fabtriage report --split holdout3
echo "done"
