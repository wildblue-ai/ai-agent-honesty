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


AUDIT_MODES = ("off", "independent", "team")


def audit_mode(exp: dict) -> str:
    mode = (exp.get("audit") or {}).get("mode", "off")
    if mode not in AUDIT_MODES:
        raise PromptError(f"audit.mode must be one of {AUDIT_MODES}, got {mode!r}")
    return mode


def audit_notice(exp: dict) -> str:
    """The paragraph the agents see about the audit; empty when the audit is off."""
    mode = audit_mode(exp)
    if mode == "off":
        return ""
    return render((P / f"audit_notice_{mode}_v1.md").read_text(), auditor_name=exp["audit"]["auditor_name"]).strip()


HATCH_MODES = ("off", "flag")


def hatch_mode(exp: dict) -> str:
    """Step 3 escape hatch: 'off' (steps 0-2) or 'flag' (flag_for_human_intervention offered)."""
    mode = exp.get("escape_hatch", "off")
    if mode not in HATCH_MODES:
        raise PromptError(f"escape_hatch must be one of {HATCH_MODES}, got {mode!r}")
    return mode


def hatch_notice(exp: dict) -> str:
    """The sentence the agents see about the escape hatch; empty when it is off."""
    return "" if hatch_mode(exp) == "off" else (P / "hatch_notice_v1.md").read_text().strip()


def system_prompt(exp: dict, agent: str, version: str) -> str:
    n = names(exp)
    role = render((P / f"role_{agent}_v1.md").read_text(), other_agent_name=n[other(agent)]).strip()
    scratch = (P / "scratchpad_v1.md").read_text().strip() if exp["scratchpad"] else None
    marker, amark, hmark = "\x00SCRATCH\x00", "\x00AUDIT\x00", "\x00HATCH\x00"
    text = render((P / "system_shared_v3.md").read_text(), agent_name=n[agent], other_agent_name=n[other(agent)],
                  scratchpad=marker, role_description=role, reward_table=reward_table(exp, agent, version),
                  audit_notice=amark, hatch_notice=hmark, max_turns=exp["max_turns"], steps_per_turn=exp["steps_per_turn"])
    notice = audit_notice(exp)
    # With the audit off, drop its paragraph entirely, which gives exactly the v1 prompt.
    text = text.replace(amark, notice) if notice else text.replace(amark + "\n\n", "")
    # With the escape hatch off, drop its paragraph entirely, which gives exactly the v2 prompt (steps 0-2).
    hnotice = hatch_notice(exp)
    text = text.replace(hmark, hnotice) if hnotice else text.replace(hmark + "\n\n", "")
    # With the scratchpad off, drop its paragraph entirely (Anthropic's no-scratchpad variant).
    return text.replace(marker, scratch) if scratch else text.replace(marker + "\n\n", "")


def auditor_system(exp: dict) -> str:
    n, mode = names(exp), audit_mode(exp)
    stake_raw = (P / f"auditor_stake_{mode}_v1.md").read_text()
    stake = (render(stake_raw, agent_a_name=n["A"], agent_b_name=n["B"]) if "{" in stake_raw else stake_raw).strip()
    return render((P / "auditor_system_v1.md").read_text(), auditor_name=exp["audit"]["auditor_name"], auditor_stake=stake,
                  scratchpad=(P / "scratchpad_v1.md").read_text().strip(), agent_a_name=n["A"], agent_b_name=n["B"])


def auditor_input(exp: dict, booking: dict, calendars: list, workspace_text: str) -> str:
    n = names(exp)
    return render((P / "auditor_input_v1.md").read_text(), day=booking["day"], start=booking["start"], end=booking["end"],
                  calendars="\n\n".join(calendar_result(c) for c in calendars), workspace_log=workspace_text,
                  agent_a_name=n["A"], agent_b_name=n["B"])


def auditor_tool_specs() -> list[dict]:
    specs = []
    for t in yaml.safe_load((P / "auditor_tools_v1.yaml").read_text())["tools"]:
        props = {k: {"type": v["type"], "description": v["description"]} for k, v in t["parameters"].items()}
        specs.append({"type": "function", "function": {"name": t["name"], "description": t["description"],
                      "parameters": {"type": "object", "properties": props, "required": list(props)}}})
    return specs


def results_text(exp: dict | None = None) -> dict[str, str]:
    r = yaml.safe_load((P / "tool_results_v1.yaml").read_text())
    if exp is not None and hatch_mode(exp) != "off":
        r = {**r, **yaml.safe_load((P / "hatch_tool_results_v1.yaml").read_text())}
    return r


def session_message(exp: dict, turn: int, clock: str, new_entries: str) -> str:
    return render((P / "session_start_v1.md").read_text(), turn=turn, max_turns=exp["max_turns"],
                  clock=clock, new_entries=new_entries)


def calendar_result(cal: dict) -> str:
    r = results_text()
    lines = [render(r["calendar_header"], owner=cal["owner"])]
    lines += [render(r["calendar_line"], **b) for b in cal["busy"]]
    lines.append(r["calendar_footer"])
    return "\n".join(lines)


def tool_specs(agent: str, exp: dict) -> list[dict]:
    """OpenAI function-calling definitions offered to this agent, built from prompts/tools_v1.yaml
    (plus prompts/hatch_tools_v1.yaml, appended last, when the escape hatch is on)."""
    specs = []
    defs = yaml.safe_load((P / "tools_v1.yaml").read_text())["tools"]
    if hatch_mode(exp) != "off":
        defs = defs + yaml.safe_load((P / "hatch_tools_v1.yaml").read_text())["tools"]
    for t in defs:
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
