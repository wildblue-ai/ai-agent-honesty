#!/usr/bin/env python3
"""One diagnostic call: does an explicit thinking budget turn Gemini's thinking on?

It resends the first real request from a saved run (same messages and tools), changing only the reasoning
setting and max_tokens. The request is saved before sending and the raw response before parsing, in a new
folder runs/<date>-probe-<name>/. The cost goes into runs/BUDGET.jsonl.

    .venv/bin/python scripts/probe_thinking.py --from runs/2026-11-07-control-check/ep01/requests/t01_A_s1.json \
        --name thinking-4000 --reasoning-max-tokens 4000 --max-tokens 12000
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.loop import BUDGET_FILE, now, spent_usd, write_once  # noqa: E402
from src.run import load_key, make_real_send  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--reasoning-max-tokens", type=int)
    p.add_argument("--reasoning-json", help='full reasoning object, e.g. {"enabled": true}')
    p.add_argument("--minimal", action="store_true", help="replace messages with one plain question and drop tools")
    p.add_argument("--drop-tools", action="store_true", help="keep the real messages, drop the tools")
    p.add_argument("--no-scratchpad", action="store_true", help="remove the scratchpad paragraph from the system prompt")
    p.add_argument("--model", help="override the model, e.g. google/gemini-2.5-pro")
    p.add_argument("--max-tokens", type=int, required=True)
    a = p.parse_args()
    out = ROOT / "runs" / f"{datetime.now():%Y-%m-%d}-probe-{a.name}"
    if out.exists():
        sys.exit(f"Refusing to overwrite {out}")
    req = json.loads(Path(a.src).read_text())["request"]
    req["max_tokens"] = a.max_tokens
    if a.model:
        req["model"] = a.model
    req["extra_body"]["reasoning"] = json.loads(a.reasoning_json) if a.reasoning_json else {"max_tokens": a.reasoning_max_tokens}
    if a.minimal:
        req["messages"] = [{"role": "user", "content": "Four people have these free 30-minute slots. A: Mon 9, Tue 13, Thu 10. "
                            "B: Mon 9, Tue 13, Wed 15. C: Tue 13, Thu 10. D: Mon 9, Tue 13. Which slot works for all four?"}]
        req.pop("tools", None); req.pop("tool_choice", None)
    if a.drop_tools:
        req.pop("tools", None); req.pop("tool_choice", None)
        req["messages"] = [m for m in req["messages"] if m["role"] in ("system", "user")]  # no tool-call turns
    if a.no_scratchpad:
        sp_text = (ROOT / "prompts" / "scratchpad_v1.md").read_text().strip()
        sysmsg = req["messages"][0]
        assert sp_text in sysmsg["content"], "scratchpad paragraph not found in system prompt"
        sysmsg["content"] = sysmsg["content"].replace(sp_text + "\n\n", "")
    out.mkdir(parents=True)
    write_once(out / "META.json", {"purpose": "diagnostic: does an explicit thinking budget turn thinking on?",
                                   "based_on": a.src, "changed": {"max_tokens": a.max_tokens,
                                   "reasoning": req["extra_body"]["reasoning"], "minimal": a.minimal,
                                   "drop_tools": a.drop_tools, "no_scratchpad": a.no_scratchpad, "model": req["model"]}, "started_utc": now()})
    write_once(out / "request.json", {"sent_utc": now(), "request": req})
    status, headers, body = make_real_send(load_key())(req)
    write_once(out / "response.raw.json", body)
    write_once(out / "response.meta.json", {"received_utc": now(), "status": status, "headers": headers})
    d = json.loads(body)
    u = d.get("usage") or {}
    with BUDGET_FILE.open("a") as f:
        f.write(json.dumps({"time": now(), "run": out.name, "episode": "-", "call": "probe", "generation_id": d.get("id"),
                            "model": d.get("model"), "provider": d.get("provider"), "cost": u.get("cost"),
                            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}) + "\n")
    m = d["choices"][0]["message"] if "choices" in d else {}
    print("status", status, "| model", d.get("model"), "| provider", d.get("provider"))
    print("usage:", json.dumps(u))
    print("reasoning text chars:", len(m.get("reasoning") or ""), "| reasoning_details items:", len(m.get("reasoning_details") or []))
    print("finish:", d["choices"][0].get("finish_reason") if "choices" in d else d.get("error"))
    print(f"total exp1 spend ${spent_usd():.4f}")


if __name__ == "__main__":
    main()
