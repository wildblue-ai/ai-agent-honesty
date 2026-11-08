#!/bin/bash
# Qwen3.6-27B on OpenRouter (approved by Cheryl 2026-11-08). Phase 1: control set + step 0 in parallel.
# Phase 2: the four audit-ladder steps in parallel, as the Gemini overnight runs did. Logs: runs/qwen-or-logs/.
cd "$(dirname "$0")/.."
L=runs/qwen-or-logs; mkdir -p $L
echo "phase 1 started $(date -u +%FT%TZ)" >> $L/status.txt
for step in qwen-control-set qwen-test-set; do
  .venv/bin/python -u -m src.run --step "$step" > "$L/$step.log" 2>&1 &
  sleep 5
done
wait
echo "phase 2 started $(date -u +%FT%TZ)" >> $L/status.txt
for step in qwen-audit1-test qwen-audit1-control qwen-audit2-test qwen-audit2-control; do
  .venv/bin/python -u -m src.run --step "$step" > "$L/$step.log" 2>&1 &
  sleep 5
done
wait
echo "finished $(date -u +%FT%TZ)" >> $L/status.txt
.venv/bin/python scripts/build_dashboard.py >> $L/status.txt 2>&1
