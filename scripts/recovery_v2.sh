#!/usr/bin/env bash
# Recovery v2 (noise rule) against the original, on the stress seeds and on fresh seeds.
# Safe to run alongside round2.sh: different method names and splits. Rerunnable (--resume).
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
for L in 0 1 2 3; do
  $PY -m fabtriage recover --method agent_v2 --split stress_L$L --resume
done
for L in 0 1 2 3; do
  for m in monitor_rule reset_recipe keep_recipe oracle; do $PY -m fabtriage recover --method $m --split stress2_L$L; done
  $PY -m fabtriage recover --method agent --split stress2_L$L --resume
  $PY -m fabtriage recover --method agent_v2 --split stress2_L$L --resume
done
$PY -m fabtriage sweep-report
$PY -m fabtriage sweep-report --prefix stress2
echo "done"
