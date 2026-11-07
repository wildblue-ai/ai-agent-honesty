"""The two-agent turn loop for one episode.

Per model call: (1) write the exact request to disk, (2) send it, (3) write the raw response body and
headers to disk before parsing anything, (4) append to runs/BUDGET.jsonl, (5) run the tool calls.
Each agent keeps its own message history. The only shared channel is the workspace.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import prompts as sp
from .world import World, clock

ROOT = Path(__file__).resolve().parent.parent
BUDGET_FILE = ROOT / "runs" / "BUDGET.jsonl"
# Reserve per call for the pre-call budget check: 8000 output tokens at $2.50/M ($0.02) plus a large input.
# Budget mechanics only, not an experimental setting.
WORST_CASE_CALL_USD = 0.05


class FatalRunError(Exception):
    """Stops the whole run: out of credits, model mismatch, budget reached, or no cost reported."""


def write_once(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, indent=2, default=str)


def spent_usd() -> float:
    if not BUDGET_FILE.exists():
        return 0.0
    return sum(json.loads(l).get("cost") or 0 for l in BUDGET_FILE.read_text().splitlines() if l.strip())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Caller:
    """Sends one request through `send` (real OpenRouter or the mock) with full raw logging."""

    def __init__(self, exp: dict, send, mock: bool, run_name: str):
        self.exp, self.send, self.mock, self.run_name = exp, send, mock, run_name

    def request(self, agent: str, messages: list, tools: list) -> dict:
        a, g = self.exp["agents"][agent], self.exp["generation"]
        return {
            "model": a["model"], "messages": messages, "tools": tools, "tool_choice": "auto",
            "max_tokens": g["max_tokens"], "temperature": g["temperature"],
            "extra_body": {
                "reasoning": {"effort": g["reasoning_effort"]},
                "provider": {"order": [a["provider"]], "allow_fallbacks": False, "require_parameters": True},
                "usage": {"include": True},
            },
        }

    def call(self, agent: str, messages: list, tools: list, ep_dir: Path, tag: str) -> dict | None:
        if not self.mock and spent_usd() + WORST_CASE_CALL_USD > self.exp["budget_cap_usd"]:
            raise FatalRunError(f"budget: spent ${spent_usd():.4f}; another call could pass ${self.exp['budget_cap_usd']}")
        req = self.request(agent, messages, tools)
        write_once(ep_dir / "requests" / f"{tag}.json", {"sent_utc": now(), "request": req})
        try:
            status, headers, body = self.send(req)
        except Exception as exc:  # network failure: record it, end the episode
            write_once(ep_dir / "responses" / f"{tag}.error.json", {"received_utc": now(), "error": repr(exc)})
            return None
        write_once(ep_dir / "responses" / f"{tag}.raw.json", body)
        write_once(ep_dir / "responses" / f"{tag}.meta.json",
                   {"received_utc": now(), "status": status, "headers": headers})
        if status == 402:
            raise FatalRunError("OpenRouter returned 402 (out of credits)")
        if status != 200:
            return None
        data = json.loads(body)
        if "error" in data and "choices" not in data:
            return None
        got = data.get("model", "")
        if not got.startswith(self.exp["agents"][agent]["model"]):
            raise FatalRunError(f"model mismatch: requested {self.exp['agents'][agent]['model']}, got {got}")
        usage = data.get("usage") or {}
        if not self.mock:
            if usage.get("cost") is None:
                raise FatalRunError(f"no cost reported in {tag}; stopping so the budget stays known")
            with BUDGET_FILE.open("a") as f:
                f.write(json.dumps({"time": now(), "run": self.run_name, "episode": ep_dir.name, "call": tag,
                                    "generation_id": data.get("id"), "model": got, "provider": data.get("provider"),
                                    "cost": usage.get("cost"), "prompt_tokens": usage.get("prompt_tokens"),
                                    "completion_tokens": usage.get("completion_tokens"),
                                    "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")})
                        + "\n")
        return data


def assistant_message(msg: dict) -> dict:
    """The assistant turn as it goes back into this agent's own history. reasoning_details is kept,
    because OpenRouter asks for it to be returned for Gemini tool calling."""
    out = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    if msg.get("reasoning_details"):
        out["reasoning_details"] = msg["reasoning_details"]
    return out


def run_episode(exp: dict, scn, version: str, ep_dir: Path, caller: Caller, max_turns: int) -> dict:
    names = sp.names(exp)
    world = World(scn, names)
    tools = {a: sp.tool_specs(a) for a in ("A", "B")}
    hist = {a: [{"role": "system", "content": sp.system_prompt(exp, a, version)}] for a in ("A", "B")}
    seen = {"A": 0, "B": 0}
    ended, turns_used, calls = None, 0, 0
    flags = {"length_cutoffs": 0, "filtered": 0, "api_errors": 0, "skipped_tool_calls": 0}
    conv = ep_dir / "conversation.jsonl"
    ep_dir.mkdir(parents=True, exist_ok=False)

    for turn in range(1, max_turns + 1):
        turns_used = turn
        for agent in exp["turn_order"]:
            new = [x for x in world.workspace[seen[agent]:] if x["agent"] != agent]
            seen[agent] = len(world.workspace)
            user = {"role": "user", "content": sp.session_message(exp, turn, clock(scn, turn), world.render_entries(new))}
            hist[agent].append(user)
            with conv.open("a") as f:
                f.write(json.dumps({"turn": turn, "agent": agent, "message": user}) + "\n")
            actions, step, over = 0, 0, False
            while not over:
                step += 1
                tag = f"t{turn:02d}_{agent}_s{step}"
                data = caller.call(agent, hist[agent], tools[agent], ep_dir, tag)
                calls += 1
                if data is None:
                    flags["api_errors"] += 1
                    ended = "api_error"
                    break
                choice = data["choices"][0]
                msg, finish = choice["message"], choice.get("finish_reason")
                if finish == "length":
                    flags["length_cutoffs"] += 1
                if finish in ("content_filter", "error"):
                    flags["filtered"] += 1
                amsg = assistant_message(msg)
                hist[agent].append(amsg)
                with conv.open("a") as f:
                    f.write(json.dumps({"turn": turn, "agent": agent, "step": step, "finish_reason": finish,
                                        "message": amsg}) + "\n")
                tcs = msg.get("tool_calls") or []
                if not tcs:
                    over = True
                for tc in tcs:
                    fn = tc.get("function", {})
                    if over or ended or actions >= exp["steps_per_turn"]:
                        result = world.r["session_ended"]
                        flags["skipped_tool_calls"] += 1
                    else:
                        actions += 1
                        result = world.call(agent, fn.get("name", ""), fn.get("arguments", ""), turn, step)
                        if fn.get("name") == "end_session":
                            over = True
                        if fn.get("name") == "report_infeasible" and world.infeasible:
                            ended = "infeasible"
                    tmsg = {"role": "tool", "tool_call_id": tc.get("id"), "content": result}
                    hist[agent].append(tmsg)
                    with conv.open("a") as f:
                        f.write(json.dumps({"turn": turn, "agent": agent, "step": step, "message": tmsg}) + "\n")
                if actions >= exp["steps_per_turn"]:
                    over = True
                if world.confirmed() and not ended:
                    ended = "confirmed"
                if ended:
                    over = True
                write_once(ep_dir / "turns" / f"{tag}_workspace.json", world.snapshot())
            if ended:
                break
        if ended:
            break
    result = {"version": version, "condition": scn.condition, "ended_reason": ended or "max_turns",
              "turns_used": turns_used, "model_calls": calls, "flags": flags, "world": world.snapshot(),
              "tool_log": world.log}
    write_once(ep_dir / "episode.json", result)
    write_once(ep_dir / "histories.json", hist)
    return result
