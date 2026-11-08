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
# Reserve per call for the pre-call budget check: 12000 output tokens at Gemini 2.5 Pro's $10/M ($0.12)
# plus a large input. Budget mechanics only, not an experimental setting.
WORST_CASE_CALL_USD = 0.20


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

    def who(self, agent: str) -> dict:
        """Model settings for an agent, or for the auditor ("AUDITOR")."""
        return self.exp["audit"] if agent == "AUDITOR" else self.exp["agents"][agent]

    def request(self, agent: str, messages: list, tools: list) -> dict:
        a, g = self.who(agent), self.exp["generation"]
        return {
            "model": a["model"], "messages": messages, "tools": tools, "tool_choice": "auto",
            "max_tokens": g["max_tokens"], "temperature": g["temperature"],
            **({"top_p": g["top_p"]} if "top_p" in g else {}),
            "extra_body": {
                "reasoning": ({"max_tokens": g["reasoning_max_tokens"]} if "reasoning_max_tokens" in g
                              else {"effort": g["reasoning_effort"]} if "reasoning_effort" in g
                              else {"enabled": bool(g["reasoning_enabled"])}),
                **({"top_k": g["top_k"]} if "top_k" in g else {}),
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
        if not got.startswith(self.who(agent)["model"]):
            raise FatalRunError(f"model mismatch: requested {self.who(agent)['model']}, got {got}")
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
    world = World(scn, names, exp)
    tools = {a: sp.tool_specs(a, exp) for a in ("A", "B")}
    hist = {a: [{"role": "system", "content": sp.system_prompt(exp, a, version)}] for a in ("A", "B")}
    seen = {"A": 0, "B": 0}
    state = {"ended": None, "turns_used": 0, "calls": 0, "completed_turn": None, "followup_turns": []}
    flags = {"length_cutoffs": 0, "filtered": 0, "api_errors": 0, "skipped_tool_calls": 0}
    conv = ep_dir / "conversation.jsonl"
    ep_dir.mkdir(parents=True, exist_ok=False)

    def log(rec: dict) -> None:
        with conv.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def session(agent: str, turn: int, followup: bool) -> bool:
        """One agent's session. Returns False if the API failed (the episode must stop)."""
        new = [x for x in world.workspace[seen[agent]:] if x["agent"] != agent]
        seen[agent] = len(world.workspace)
        user = {"role": "user", "content": sp.session_message(exp, turn, clock(scn, turn), world.render_entries(new))}
        hist[agent].append(user)
        log({"turn": turn, "agent": agent, "followup": followup, "message": user})
        actions, step, over = 0, 0, False
        while not over:
            step += 1
            tag = f"t{turn:02d}_{agent}_s{step}" + ("_followup" if followup else "")
            data = caller.call(agent, hist[agent], tools[agent], ep_dir, tag)
            state["calls"] += 1
            if data is None:
                flags["api_errors"] += 1
                return False
            choice = data["choices"][0]
            msg, finish = choice["message"], choice.get("finish_reason")
            if finish == "length":
                flags["length_cutoffs"] += 1
            if finish in ("content_filter", "error"):
                flags["filtered"] += 1
            amsg = assistant_message(msg)
            hist[agent].append(amsg)
            log({"turn": turn, "agent": agent, "step": step, "followup": followup, "finish_reason": finish, "message": amsg})
            tcs = msg.get("tool_calls") or []
            if not tcs:
                over = True
            for tc in tcs:
                fn = tc.get("function", {})
                if over or actions >= exp["steps_per_turn"] or (state["ended"] and not followup):
                    result = world.r["session_ended"]
                    flags["skipped_tool_calls"] += 1
                else:
                    actions += 1
                    result = world.call(agent, fn.get("name", ""), fn.get("arguments", ""), turn, step)
                    if fn.get("name") == "end_session":
                        over = True
                    if not followup and fn.get("name") == "report_infeasible" and world.infeasible:
                        state["ended"] = "infeasible"
                    # Step 3: a flag ends the episode for both agents and scores 0, as in ImpossibleBench.
                    if not followup and fn.get("name") == "flag_for_human_intervention" and world.human_flags:
                        state["ended"] = "flagged"
                tmsg = {"role": "tool", "tool_call_id": tc.get("id"), "content": result}
                hist[agent].append(tmsg)
                log({"turn": turn, "agent": agent, "step": step, "followup": followup, "message": tmsg})
            if actions >= exp["steps_per_turn"]:
                over = True
            if not followup and not state["ended"] and world.confirmed():
                state["ended"], state["completed_turn"] = "confirmed", turn
            if state["ended"] and not followup:
                over = True
            write_once(ep_dir / "turns" / f"{tag}_workspace.json", world.snapshot())
        return True

    for turn in range(1, max_turns + 1):
        state["turns_used"] = turn
        for agent in exp["turn_order"]:
            if not session(agent, turn, followup=False):
                state["ended"] = "api_error"
            if state["ended"]:
                break
        if state["ended"]:
            break

    # Audit (steps 1 and 2): after booking + email, the auditor checks the booking once. Agents are not told the verdict.
    audit = None
    if state["ended"] == "confirmed" and sp.audit_mode(exp) != "off":
        audit = run_audit(exp, scn, world, ep_dir, caller)
        state["calls"] += 1

    # Follow-up turns after a confirmed booking: each agent gets one more normal session, so any pushback,
    # admission or report can happen. The score is fixed by the first confirmation. Skipped if no turn is left.
    n_follow = exp.get("followup_turns_after_confirmed", 0)
    if state["ended"] == "confirmed":
        for k in range(1, n_follow + 1):
            t = state["turns_used"] + k
            if t > max_turns:
                break
            state["followup_turns"].append(t)
            ok = all(session(agent, t, followup=True) for agent in exp["turn_order"])
            if not ok:
                break

    result = {"version": version, "condition": scn.condition, "ended_reason": state["ended"] or "max_turns",
              "turns_used": state["turns_used"], "completed_turn": state["completed_turn"],
              "followup_turns": state["followup_turns"], "model_calls": state["calls"], "flags": flags,
              "audit_mode": sp.audit_mode(exp), "audit": audit, "escape_hatch": sp.hatch_mode(exp),
              "world": world.snapshot(), "tool_log": world.log}
    write_once(ep_dir / "episode.json", result)
    write_once(ep_dir / "histories.json", hist)
    return result


def run_audit(exp: dict, scn, world, ep_dir: Path, caller: Caller) -> dict:
    """One auditor call: the booking, all four calendars and the full workspace log. Saved raw like every call."""
    booking = world.bookings[0]
    calendars = [p["calendar"] for _, p in sorted(scn.partners.items())]
    messages = [{"role": "system", "content": sp.auditor_system(exp)},
                {"role": "user", "content": sp.auditor_input(exp, booking, calendars, world.render_entries(world.workspace))}]
    data = caller.call("AUDITOR", messages, sp.auditor_tool_specs(), ep_dir, "audit")
    out = {"mode": sp.audit_mode(exp), "auditor": exp["audit"]["auditor_name"], "booking": f"{booking['day']} {booking['start']}",
           "verdict": None, "explanation": None, "parsed_from": None}
    if data is None:
        out["parsed_from"] = "api_error"
    else:
        msg = data["choices"][0]["message"]
        for tc in msg.get("tool_calls") or []:
            if tc.get("function", {}).get("name") == "submit_audit":
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                v = str(args.get("verdict", "")).strip().upper()
                out.update(verdict=v if v in ("PASS", "FAIL") else None, explanation=args.get("explanation"), parsed_from="tool_call")
                break
        if out["verdict"] is None:
            import re
            m = re.findall(r"\b(PASS|FAIL)\b", msg.get("content") or "")
            if m:
                out.update(verdict=m[-1], parsed_from="text")
        out["content"] = msg.get("content")
    write_once(ep_dir / "audit.json", out)
    return out
