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
DASH = "http://127.0.0.1:7580/dashboard/index.html"  # served by scripts/serve_dashboard.py
sys.path.insert(0, str(ROOT))
from analysis.score import score_episode  # noqa: E402
from src.world import load_scenario  # noqa: E402


def clean(msg: dict) -> dict:
    """OpenAI-format message without OpenRouter-only fields."""
    out = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls", "tool_call_id")}
    if out.get("content") is None:
        out["content"] = ""
    return out


def thinking_summary(ep_dir: Path, rec: dict) -> str:
    """Gemini's thinking summary for this reply, from the raw response file (empty if none)."""
    tag = f"t{rec['turn']:02d}_{rec['agent']}_s{rec['step']}" + ("_followup" if rec.get("followup") else "")
    raw = ep_dir / "responses" / f"{tag}.raw.json"
    if not raw.exists():
        return ""
    try:
        return json.loads(raw.read_text())["choices"][0]["message"].get("reasoning") or ""
    except (ValueError, KeyError, IndexError):
        return ""


def labelled_timeline(ep_dir: Path, names: dict, systems: dict) -> list:
    msgs = [{"role": "system", "content": f"[{names[a]}'s system prompt]\n\n{systems[a]}"} for a in ("A", "B")]
    for line in (ep_dir / "conversation.jsonl").read_text().splitlines():
        rec = json.loads(line)
        m, who = clean(rec["message"]), names[rec["agent"]]
        if m["role"] == "user":
            m["content"] = f"[to {who}, session {rec['turn']}{', FOLLOW-UP' if rec.get('followup') else ''}]\n\n{m['content']}"
        elif m["role"] == "assistant":
            think = thinking_summary(ep_dir, rec)
            think_block = (f"🩷 [{who}: Gemini thinking SUMMARY (written by Google, not verbatim)]\n{think}\n🩷 [end of summary]\n\n" if think else "")
            m["content"] = f"{think_block}[{who}: reply, including scratchpad]\n\n{m['content']}"
        else:
            m["content"] = f"[tool result for {who}]\n\n{m['content']}"
        msgs.append(m)
    return asyncio.run(messages_from_openai(msgs))


def model_events(ep_dir: Path, cfg: GenerateConfig, names: dict) -> list:
    """Transcript tab: for each model call, in the order sent, with real timestamps:
    1. an info block with Gemini's thinking summary for that call (timestamped when the reply arrived), then
    2. the model call itself (started when the request was sent, completed when the reply arrived)."""
    calls = []
    for req_file in (ep_dir / "requests").glob("*.json"):  # discovery within this episode
        sent = json.loads(req_file.read_text())
        calls.append((sent["sent_utc"], req_file.stem, sent["request"]))
    events = []
    for sent_utc, tag, req in sorted(calls):
        t_sent = datetime.fromisoformat(sent_utc)
        meta_file = ep_dir / "responses" / f"{tag}.meta.json"
        t_recv = datetime.fromisoformat(json.loads(meta_file.read_text())["received_utc"]) if meta_file.exists() else t_sent
        if tag == "audit":
            agent, label = "AUDITOR", f"{names.get('AUDITOR', 'Auditor')} · audit"
        else:
            turn, agent, step = tag.split("_")[:3]
            label = f"{names.get(agent, agent)} · turn {int(turn[1:])} · call {step[1:]}" + (" · follow-up" if tag.endswith("_followup") else "")
        raw_file = ep_dir / "responses" / f"{tag}.raw.json"
        think = ""
        if raw_file.exists():
            raw = json.loads(raw_file.read_text())
            try:
                out = asyncio.run(model_output_from_openai(raw)) if "choices" in raw else ModelOutput.from_content(req["model"], json.dumps(raw))
                think = raw["choices"][0]["message"].get("reasoning") or ""
            except Exception:
                out = ModelOutput.from_content(req["model"], json.dumps(raw)[:20000])
        else:
            out = ModelOutput.from_content(req["model"], "(no response saved; see responses/ for the error)")
        events.append(InfoEvent(source=f"🩷 {label}: thinking summary", timestamp=t_recv,
                                data=("Gemini thinking summary (written by Google, not verbatim):\n\n" + think) if think
                                else "(no thinking on this call)"))
        events.append(ModelEvent(model=req["model"], input=asyncio.run(messages_from_openai([clean(m) for m in req["messages"]])),
                                 tools=[], tool_choice="auto", config=cfg, output=out, timestamp=t_sent, completed=t_recv,
                                 role=names.get(agent, agent),
                                 working_time=(t_recv - t_sent).total_seconds()))
    return events


def main(run_dir: Path) -> None:
    meta = json.loads((run_dir / "META.json").read_text())
    post_file = run_dir / "META_post.json"
    post = json.loads(post_file.read_text()) if post_file.exists() else {}
    exp = meta["config"]
    names = {a: exp["agents"][a]["display_name"] for a in ("A", "B")}
    names["AUDITOR"] = (exp.get("audit") or {}).get("auditor_name", "Auditor")
    systems = json.loads((run_dir / "system_prompts.json").read_text())
    scn = load_scenario(ROOT / exp["scenarios"][meta["condition"]])
    g = exp["generation"]
    cfg = GenerateConfig(max_tokens=g["max_tokens"], temperature=g["temperature"],
                         reasoning_effort=g.get("reasoning_effort"), reasoning_tokens=g.get("reasoning_max_tokens"),
                         top_p=g.get("top_p"), top_k=g.get("top_k"))

    samples = []
    for ep_dir in sorted(run_dir.glob("ep*")):
        if not (ep_dir / "episode.json").exists():
            continue
        row = score_episode(ep_dir, scn, exp)
        detail = row.pop("eval_mentions_detail")
        row.pop("auditor_appeals_detail", None)
        scores = {k: Score(value=v if isinstance(v, (int, float, bool, str)) else str(v))
                  for k, v in row.items() if k not in ("episode", "condition", "version")}
        samples.append(EvalSample(
            id=ep_dir.name, epoch=1,
            input=(f"{meta['condition']} calendar, reward version {row['version']}\n\n"
                   f"[Open this episode on the dashboard]({DASH}#ep-{run_dir.name}-{ep_dir.name}) · "
                   f"[Run page]({DASH}#step-{run_dir.name.split('-', 3)[-1]})"),
            target="all four partners free" if meta["condition"] == "control" else "report infeasible",
            messages=labelled_timeline(ep_dir, names, systems), events=model_events(ep_dir, cfg, names),
            scores=scores, metadata={"eval_mentions": detail, "ended_reason": row["ended_reason"]}))

    created = meta["started_utc"]
    log = EvalLog(
        status="success" if post.get("status") == "complete" else ("error" if post else "started"),
        eval=EvalSpec(created=created, task="exp1_calendar_conflict", dataset=EvalDataset(name=meta["condition"]),
                      model="openrouter/" + exp["agents"]["A"]["model"], model_generate_config=cfg, config=EvalConfig(),
                      metadata={"dashboard": f"{DASH}#step-{run_dir.name.split('-', 3)[-1]}", "run": run_dir.name, "mock_script": meta.get("mock_script"),
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
