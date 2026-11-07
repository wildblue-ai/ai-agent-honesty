"""Convert a run's raw files into a standard Inspect AI log, so it opens in the Inspect viewer.

    .venv/bin/python -m analysis.to_inspect runs/2026-11-07-control-check
    .venv/bin/inspect view --log-dir runs

Derived output only. runs/<run>/inspect/ is rebuilt from the raw files on every call.
Each episode is one sample:
- Messages tab: the combined timeline, each message labelled with the agent it belongs to.
- Transcript tab: one model event per call, with exactly what that agent was sent and what came back.
- Scores: the deterministic columns from analysis/score.py.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.event import InfoEvent, ModelEvent
from inspect_ai.log import (EvalConfig, EvalDataset, EvalLog, EvalResults, EvalSample, EvalSpec, EvalStats,
                            write_eval_log)
from inspect_ai.model import GenerateConfig, ModelOutput, messages_from_openai, model_output_from_openai
from inspect_ai.scorer import Score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.score import score_episode  # noqa: E402
from src.world import load_scenario  # noqa: E402


def clean(msg: dict) -> dict:
    """OpenAI-format message without OpenRouter-only fields."""
    out = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls", "tool_call_id")}
    if out.get("content") is None:
        out["content"] = ""
    return out


def labelled_timeline(ep_dir: Path, names: dict, systems: dict) -> list:
    msgs = [{"role": "system", "content": f"[{names[a]}'s system prompt]\n\n{systems[a]}"} for a in ("A", "B")]
    for line in (ep_dir / "conversation.jsonl").read_text().splitlines():
        rec = json.loads(line)
        m, who = clean(rec["message"]), names[rec["agent"]]
        if m["role"] == "user":
            m["content"] = f"[to {who}, session {rec['turn']}]\n\n{m['content']}"
        elif m["role"] == "assistant":
            m["content"] = f"[{who}]\n\n{m['content']}"
        else:
            m["content"] = f"[tool result for {who}]\n\n{m['content']}"
        msgs.append(m)
    return asyncio.run(messages_from_openai(msgs))


def model_events(ep_dir: Path, cfg: GenerateConfig) -> list:
    events = []
    for req_file in sorted((ep_dir / "requests").glob("*.json")):  # discovery within this episode
        tag = req_file.stem
        sent = json.loads(req_file.read_text())
        req = sent["request"]
        raw_file = ep_dir / "responses" / f"{tag}.raw.json"
        if raw_file.exists():
            raw = json.loads(raw_file.read_text())
            try:
                out = asyncio.run(model_output_from_openai(raw)) if "choices" in raw else ModelOutput.from_content(req["model"], json.dumps(raw))
            except Exception:
                out = ModelOutput.from_content(req["model"], json.dumps(raw)[:20000])
        else:
            out = ModelOutput.from_content(req["model"], "(no response saved; see responses/ for the error)")
        events.append(InfoEvent(source="exp1", data={"call": tag, "sent_utc": sent["sent_utc"]}))
        events.append(ModelEvent(model=req["model"], input=asyncio.run(messages_from_openai([clean(m) for m in req["messages"]])),
                                 tools=[], tool_choice="auto", config=cfg, output=out))
    return events


def main(run_dir: Path) -> None:
    meta = json.loads((run_dir / "META.json").read_text())
    post_file = run_dir / "META_post.json"
    post = json.loads(post_file.read_text()) if post_file.exists() else {}
    exp = meta["config"]
    names = {a: exp["agents"][a]["display_name"] for a in ("A", "B")}
    systems = json.loads((run_dir / "system_prompts.json").read_text())
    scn = load_scenario(ROOT / exp["scenarios"][meta["condition"]])
    g = exp["generation"]
    cfg = GenerateConfig(max_tokens=g["max_tokens"], temperature=g["temperature"], reasoning_effort=g["reasoning_effort"])

    samples = []
    for ep_dir in sorted(run_dir.glob("ep*")):
        if not (ep_dir / "episode.json").exists():
            continue
        row = score_episode(ep_dir, scn)
        detail = row.pop("eval_mentions_detail")
        scores = {k: Score(value=v if isinstance(v, (int, float, bool, str)) else str(v))
                  for k, v in row.items() if k not in ("episode", "condition", "version")}
        samples.append(EvalSample(
            id=ep_dir.name, epoch=1, input=f"{meta['condition']} calendar, reward version {row['version']}",
            target="all four partners free" if meta["condition"] == "control" else "report infeasible",
            messages=labelled_timeline(ep_dir, names, systems), events=model_events(ep_dir, cfg),
            scores=scores, metadata={"eval_mentions": detail, "ended_reason": row["ended_reason"]}))

    created = meta["started_utc"]
    log = EvalLog(
        status="success" if post.get("status") == "complete" else ("error" if post else "started"),
        eval=EvalSpec(created=created, task="exp1_calendar_conflict", dataset=EvalDataset(name=meta["condition"]),
                      model="openrouter/" + exp["agents"]["A"]["model"], model_generate_config=cfg, config=EvalConfig(),
                      metadata={"run": run_dir.name, "mock_script": meta.get("mock_script"),
                                "git_commit": meta.get("git_commit"), "versions": meta.get("versions"),
                                "actual_cost_usd": post.get("actual_cost_usd"),
                                "models_answered": post.get("models_answered")}),
        stats=EvalStats(started_at=created, completed_at=post.get("finished_utc", datetime.now(timezone.utc).isoformat())),
        results=EvalResults(total_samples=len(samples), completed_samples=len(samples)),
        samples=samples)
    out = run_dir / "inspect"
    if out.exists():
        shutil.rmtree(out)  # derived only
    out.mkdir()
    write_eval_log(log, location=str(out / f"{run_dir.name}.eval"))
    print(f"Inspect log: {out / (run_dir.name + '.eval')}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
