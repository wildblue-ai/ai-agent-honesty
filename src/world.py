"""Scenario loading, the feasibility check, and the tools the agents call.

Agents never see anything from here except the text replies built from prompts/tool_results_v1.yaml.
Tool errors return fixed messages, never exception text or file paths.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import prompts as sp

ROOT = Path(__file__).resolve().parent.parent
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
STARTS = [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)]


class ScenarioError(Exception):
    pass


def add30(t: str) -> str:
    h, m = map(int, t.split(":"))
    m += 30
    return f"{h + m // 60:02d}:{m % 60:02d}"


@dataclass
class Scenario:
    condition: str
    meta: dict
    partners: dict  # pid -> {"name", "visible_to", "calendar": dict, "file": Path}
    file_hashes: dict

    def free(self, pid: str, day: str, t: str) -> bool:
        return not any(b["day"] == day and b["start"] <= t < b["end"] for b in self.partners[pid]["calendar"]["busy"])

    def free_for(self, day: str, t: str) -> list[str]:
        return [p["name"] for pid, p in self.partners.items() if self.free(pid, day, t)]

    def common_slots(self) -> list[tuple[str, str]]:
        return [(d, t) for d in DAYS for t in STARTS if len(self.free_for(d, t)) == len(self.partners)]

    def visible(self, agent: str) -> dict[str, dict]:
        return {p["name"]: p["calendar"] for p in self.partners.values() if p["visible_to"] == agent}


def load_scenario(cond_dir: Path) -> Scenario:
    """Read _scenario.yaml, then each partner's file by its recorded calendar_file (never a glob)."""
    meta_file = cond_dir / "_scenario.yaml"
    if not meta_file.exists():
        raise ScenarioError(f"missing scenario file: {meta_file}")
    meta = yaml.safe_load(meta_file.read_text())
    hashes = {str(meta_file.relative_to(ROOT)): hashlib.sha256(meta_file.read_bytes()).hexdigest()}
    partners = {}
    for p in meta["partners"]:
        f = cond_dir / p["calendar_file"]
        if not f.exists():
            raise ScenarioError(f"missing calendar file named in {meta_file.name}: {f}")
        hashes[str(f.relative_to(ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
        partners[p["id"]] = {"name": p["name"], "visible_to": p["visible_to"], "calendar": yaml.safe_load(f.read_text())}
    return Scenario(meta["condition"], meta, partners, hashes)


def assert_condition(scn: Scenario) -> None:
    """impossible must have no common slot; control exactly one."""
    common = scn.common_slots()
    expected = {"impossible": 0, "control": 1}.get(scn.condition)
    if expected is None or len(common) != expected:
        raise ScenarioError(f"{scn.condition} calendar has common slots {common}; expected {expected}")


def clock(scn: Scenario, turn: int) -> str:
    """Simulated time at the start of a session: scenario_start + (turn - 1) * minutes_per_turn."""
    start = scn.meta["scenario_start"]
    base = datetime.strptime(f"{start['date']} {start['time']}", "%Y-%m-%d %H:%M")
    now = base + timedelta(minutes=(turn - 1) * scn.meta["minutes_per_turn"])
    return now.strftime("%a %b %-d, %H:%M")


@dataclass
class World:
    scn: Scenario
    names: dict  # "A"/"B" -> display name
    exp: dict    # experiment settings; only the escape-hatch mode is read here
    workspace: list = field(default_factory=list)   # {"author", "agent", "clock", "turn", "text"}
    bookings: list = field(default_factory=list)
    emails: list = field(default_factory=list)
    infeasible: list = field(default_factory=list)
    human_flags: list = field(default_factory=list)  # step 3 escape hatch: {"turn", "agent", "reason"}
    log: list = field(default_factory=list)

    def __post_init__(self):
        self.r = sp.results_text(self.exp)
        self.offered = {a: {t["function"]["name"] for t in sp.tool_specs(a, self.exp)} for a in ("A", "B")}
        self.hatch = sp.hatch_mode(self.exp) != "off"

    def call(self, agent: str, name: str, raw_args: str, turn: int, step: int) -> str:
        event = {"turn": turn, "agent": agent, "step": step, "name": name, "raw_args": raw_args,
                 "args": None, "error": None}
        result = self._call(agent, name, raw_args, turn, event)
        event["result"] = result
        self.log.append(event)
        return result

    def _call(self, agent, name, raw_args, turn, event) -> str:
        r = self.r
        if name not in self.offered[agent]:
            event["error"] = "unknown_tool"
            return r["error_unknown_tool"]
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except (ValueError, TypeError):
            event["error"] = "bad_arguments"
            return r["error_bad_arguments"]
        event["args"] = args
        try:
            if name == "read_calendar":
                cal = self.scn.visible(agent).get(str(args["partner"]).strip())
                if cal is None:
                    event["error"] = "unknown_partner"
                    return r["error_unknown_partner"]
                return sp.calendar_result(cal)
            if name == "append_workspace":
                entry = {"author": self.names[agent], "agent": agent, "clock": clock(self.scn, turn),
                         "turn": turn, "text": str(args["text"])}
                self.workspace.append(entry)
                return r["append_ok"]
            if name in ("create_booking", "send_confirmation_email"):
                day, start = str(args["day"]).strip()[:3].title(), str(args["start"]).strip()
                if day not in DAYS or start not in STARTS:
                    event["error"] = "bad_time"
                    return r["error_bad_time"]
                rec = {"turn": turn, "agent": agent, "day": day, "start": start, "end": add30(start)}
                if name == "create_booking":
                    self.bookings.append(rec)
                    return sp.render(r["booking_ok"], day=day, start=start, end=rec["end"])
                rec["body"] = str(args["body"])
                self.emails.append(rec)
                return sp.render(r["email_ok"], day=day, start=start, end=rec["end"])
            if name == "report_infeasible":
                self.infeasible.append({"turn": turn, "agent": agent, "reason": str(args["reason"])})
                return r["infeasible_ok"]
            if name == "flag_for_human_intervention":
                self.human_flags.append({"turn": turn, "agent": agent, "reason": str(args["reason"])})
                return r["flag_ok"]
            if name == "end_session":
                return r["session_ended"]
        except KeyError:
            event["error"] = "bad_arguments"
            return r["error_bad_arguments"]
        event["error"] = "unknown_tool"
        return r["error_unknown_tool"]

    def render_entries(self, entries: list) -> str:
        if not entries:
            return self.r["no_new_entries"]
        return "\n".join(sp.render(self.r["workspace_entry"], clock=x["clock"], author=x["author"], text=x["text"])
                         for x in entries)

    def confirmed(self) -> bool:
        return bool(self.bookings) and bool(self.emails)

    def snapshot(self) -> dict:
        snap = {"workspace": self.workspace, "bookings": self.bookings, "emails": self.emails,
                "infeasible": self.infeasible}
        if self.hatch:  # only in step 3 runs, so earlier runs' files keep exactly their old shape
            snap["human_flags"] = self.human_flags
        return snap
