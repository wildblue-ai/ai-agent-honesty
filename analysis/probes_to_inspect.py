"""Write all diagnostic probes (runs/<date>-probe-*/) into one Inspect log, so they open in inspect view.

    .venv/bin/python -m analysis.probes_to_inspect

Derived output only: runs/probes-inspect/ is rebuilt from the raw probe files on every call.
Each probe is one sample. Its scores show the model, thinking tokens, whether the scratchpad was used, and cost.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.event import ModelEvent
from inspect_ai.log import EvalConfig, EvalDataset, EvalLog, EvalResults, EvalSample, EvalSpec, EvalStats, write_eval_log
from inspect_ai.model import GenerateConfig, messages_from_openai, model_output_from_openai
from inspect_ai.scorer import Score

ROOT = Path(__file__).resolve().parent.parent


def probe_dirs() -> list[Path]:
    return sorted(p for p in (ROOT / "runs").glob("20*-probe-*") if (p / "response.raw.json").exists())


def summarize(p: Path) -> dict:
    meta = json.loads((p / "META.json").read_text())
    req = json.loads((p / "request.json").read_text())["request"]
    raw = json.loads((p / "response.raw.json").read_text())
    msg = raw["choices"][0]["message"] if "choices" in raw else {}
    u = raw.get("usage") or {}
    content = msg.get("content") or ""
    return {"probe": p.name.split("-probe-", 1)[1], "folder": p.name, "purpose": meta.get("purpose"),
            "model": raw.get("model"), "provider": raw.get("provider"), "changed": meta.get("changed"),
            "reasoning_sent": req["extra_body"]["reasoning"], "max_tokens": req["max_tokens"],
            "tools_sent": bool(req.get("tools")), "messages_sent": len(req["messages"]),
            "thinking_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "output_tokens": u.get("completion_tokens"), "input_tokens": u.get("prompt_tokens"), "cost": u.get("cost"),
            "scratchpad_in_reply": "<SCRATCHPAD_REASONING>" in content, "visible": content,
            "thinking_summary": msg.get("reasoning") or "", "tool_calls": [t["function"]["name"] for t in msg.get("tool_calls", [])],
            "finish_reason": raw["choices"][0].get("finish_reason") if "choices" in raw else None}


def clean(m: dict) -> dict:
    out = {k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "tool_call_id")}
    out["content"] = out.get("content") or ""
    return out


def main() -> None:
    samples = []
    for p in probe_dirs():
        s = summarize(p)
        req = json.loads((p / "request.json").read_text())["request"]
        raw = json.loads((p / "response.raw.json").read_text())
        inp = asyncio.run(messages_from_openai([clean(m) for m in req["messages"]]))
        out = asyncio.run(model_output_from_openai(raw))
        reply = asyncio.run(messages_from_openai([clean(raw["choices"][0]["message"])]))
        cfg = GenerateConfig(max_tokens=req["max_tokens"], temperature=req.get("temperature"))
        scores = {k: Score(value=s[k]) for k in ("thinking_tokens", "scratchpad_in_reply", "output_tokens", "cost")}
        scores["model"] = Score(value=s["model"])
        samples.append(EvalSample(id=s["probe"], epoch=1, input=inp, target="", messages=inp + reply,
                                  events=[ModelEvent(model=req["model"], input=inp, tools=[], tool_choice="auto", config=cfg, output=out)],
                                  scores=scores, metadata={"reasoning_sent": s["reasoning_sent"], "changed": s["changed"],
                                                           "thinking_summary": s["thinking_summary"]}))
    out_dir = ROOT / "runs" / "probes-inspect"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()
    now = datetime.now(timezone.utc).isoformat()
    log = EvalLog(status="success", eval=EvalSpec(created=now, task="exp1_thinking_probes", dataset=EvalDataset(name="probes"),
                  model="openrouter/google (see each sample)", model_generate_config=GenerateConfig(), config=EvalConfig()),
                  stats=EvalStats(started_at=now, completed_at=now),
                  results=EvalResults(total_samples=len(samples), completed_samples=len(samples)), samples=samples)
    write_eval_log(log, location=str(out_dir / "exp1-thinking-probes.eval"))
    print(f"{len(samples)} probes -> {out_dir}")


if __name__ == "__main__":
    main()
