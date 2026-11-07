"""The only renderer for agent-visible text. scripts/render_review.py and the runner both use it.

All wording comes from prompts/. All values come from config/experiment.yaml. Rendering fails on any
unfilled or unused placeholder.
"""
from __future__ import annotations

import hashlib
import string
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "prompts"


class PromptError(Exception):
    pass


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def render(template: str, /, **vars) -> str:
    text = template
    names = {f for _, f, _, _ in string.Formatter().parse(text) if f}
    missing, unused = names - vars.keys(), vars.keys() - names
    if missing or unused:
        raise PromptError(f"placeholder mismatch: missing {sorted(missing)}, unused {sorted(unused)}")
    return text.format(**vars)


def names(exp: dict) -> dict[str, str]:
    return {k: v["display_name"] for k, v in exp["agents"].items()}


def other(agent: str) -> str:
    return "B" if agent == "A" else "A"


def reward_table(exp: dict, agent: str, version: str) -> str:
    sched = sorted(exp["reward"]["confirmed_by_turn"].items())
    if len(sched) != 3:
        raise PromptError("reward_table_v1.md expects exactly 3 deadlines in reward.confirmed_by_turn")
    if sched[-1][0] != exp["max_turns"]:
        raise PromptError(f"last reward deadline ({sched[-1][0]}) must equal max_turns ({exp['max_turns']})")
    return render((P / "reward_table_v1.md").read_text(), other_agent_name=names(exp)[other(agent)],
                  deadline_1=sched[0][0], points_1=sched[0][1], deadline_2=sched[1][0], points_2=sched[1][1],
                  deadline_3=sched[2][0], points_3=sched[2][1], points_incomplete=exp["reward"]["incomplete"],
                  infeasible_points=exp["versions"][version]["infeasible_points"]).strip()


def system_prompt(exp: dict, agent: str, version: str) -> str:
    n = names(exp)
    role = render((P / f"role_{agent}_v1.md").read_text(), other_agent_name=n[other(agent)]).strip()
    scratch = (P / "scratchpad_v1.md").read_text().strip() if exp["scratchpad"] else None
    marker = "\x00SCRATCH\x00"
    text = render((P / "system_shared_v1.md").read_text(), agent_name=n[agent], other_agent_name=n[other(agent)],
                  scratchpad=marker, role_description=role, reward_table=reward_table(exp, agent, version),
                  max_turns=exp["max_turns"], steps_per_turn=exp["steps_per_turn"])
    # With the scratchpad off, drop its paragraph entirely (Anthropic's no-scratchpad variant).
    return text.replace(marker, scratch) if scratch else text.replace(marker + "\n\n", "")


def results_text() -> dict[str, str]:
    return yaml.safe_load((P / "tool_results_v1.yaml").read_text())


def session_message(exp: dict, turn: int, clock: str, new_entries: str) -> str:
    return render((P / "session_start_v1.md").read_text(), turn=turn, max_turns=exp["max_turns"],
                  clock=clock, new_entries=new_entries)


def calendar_result(cal: dict) -> str:
    r = results_text()
    lines = [render(r["calendar_header"], owner=cal["owner"])]
    lines += [render(r["calendar_line"], **b) for b in cal["busy"]]
    lines.append(r["calendar_footer"])
    return "\n".join(lines)


def tool_specs(agent: str) -> list[dict]:
    """OpenAI function-calling definitions offered to this agent, built from prompts/tools_v1.yaml."""
    specs = []
    for t in yaml.safe_load((P / "tools_v1.yaml").read_text())["tools"]:
        if agent not in t["agents"]:
            continue
        props = {k: {"type": v["type"], "description": v["description"]} for k, v in t["parameters"].items()}
        specs.append({"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": {"type": "object", "properties": props, "required": list(props)}}})
    return specs


def verify_manifest(require_approved: bool) -> dict[str, str]:
    """Return file -> sha256. Raise if any prompt file differs from MANIFEST.yaml, or is unapproved."""
    manifest = yaml.safe_load((P / "MANIFEST.yaml").read_text())["files"]
    out = {}
    on_disk = {f.name for f in P.iterdir() if f.suffix in (".md", ".yaml")
               and f.name not in ("MANIFEST.yaml", "REVIEW_v1.md", "CHANGELOG.md")}
    if on_disk != set(manifest):
        raise PromptError(f"prompt files and MANIFEST.yaml disagree: {sorted(on_disk ^ set(manifest))}")
    for name, entry in manifest.items():
        sha = hashlib.sha256((P / name).read_bytes()).hexdigest()
        if sha != entry["sha256"]:
            raise PromptError(f"{name} changed since MANIFEST.yaml was written; re-render and re-approve")
        if require_approved and not entry.get("approved_by"):
            raise PromptError(f"{name} is not approved in MANIFEST.yaml")
        out[name] = sha
    return out
