#!/bin/bash
# Cheryl 2026-11-08: after run_qwen_openrouter.sh finishes, top up the control set and step 0 to 30 each (in parallel).
cd "$(dirname "$0")/.."
L=runs/qwen-or-logs
until grep -q "^finished" $L/status.txt 2>/dev/null; do sleep 60; done
echo "topups started $(date -u +%FT%TZ)" >> $L/status.txt
for step in qwen-control-set-topup qwen-test-set-topup; do
  .venv/bin/python -u -m src.run --step "$step" > "$L/$step.log" 2>&1 &
  sleep 5
done
wait
echo "topups finished $(date -u +%FT%TZ)" >> $L/status.txt
.venv/bin/python scripts/build_dashboard.py >> $L/status.txt 2>&1
