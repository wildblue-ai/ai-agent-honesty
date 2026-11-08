#!/bin/bash
# Overnight audit-ladder runs (approved by Cheryl 2026-11-07). All four plan steps run in parallel, so step 1 and step 2
# share the same time window. Started detached under caffeinate so the Mac stays awake. Logs go to runs/overnight/.
cd "$(dirname "$0")/.."
mkdir -p runs/overnight
echo "started $(date -u +%FT%TZ)" > runs/overnight/status.txt
for step in audit1-test audit1-control audit2-test audit2-control; do
  .venv/bin/python -u -m src.run --step "$step" > "runs/overnight/$step.log" 2>&1 &
  sleep 5
done
wait
echo "finished $(date -u +%FT%TZ)" >> runs/overnight/status.txt
.venv/bin/python scripts/build_dashboard.py >> runs/overnight/status.txt 2>&1
