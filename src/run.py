"""Run episodes of exp1. Use --mock to test the whole pipeline for free.

    .venv/bin/python -m src.run --step control-check          # paid: a step from config/run_plan.yaml
    .venv/bin/python -m src.run --mock control_success --run-name test --condition control --version A --n 1

Pre-flight, in order: settings log check, prompt hashes and approval, calendar check, refuse an existing run
folder, budget check, key load. Then META.json is written before any call is sent.

Key loading, provider pinning, refuse-to-overwrite, the run-record fields and mock mode follow
../run_smoke.py (Cheryl's ImpossibleBench runner), copied and modified for exp1 on 2026-11-07.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import prompts as sp
from .loop import Caller, FatalRunError, run_episode, spent_usd, write_once
from .mock import SCRIPTS, make_send
from .settings_check import mismatches
from .world import assert_condition, load_scenario

ROOT = Path(__file__).resolve().parent.parent


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        return ""


def load_key() -> str:
    """Read the OpenRouter key inside this process only. Never printed or logged."""
    from dotenv import dotenv_values
    key = (dotenv_values(ROOT / ".env").get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY is missing or blank in the key file")
    return key


def make_real_send(key: str):
    import openai
    client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key, max_retries=2, timeout=600)

    def send(req: dict):
        kw = dict(req)
        extra = kw.pop("extra_body")
        try:
            raw = client.chat.completions.with_raw_response.create(**kw, extra_body=extra)
            return raw.http_response.status_code, dict(raw.http_response.headers), raw.http_response.text
        except openai.APIStatusError as e:
            return e.status_code, dict(e.response.headers), e.response.text

    return send


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--step", help="paid runs: a step id from config/run_plan.yaml")
    p.add_argument("--mock", choices=sorted(SCRIPTS), help="free scripted test run")
    p.add_argument("--run-name", help="mock runs only")
    p.add_argument("--condition", choices=["impossible", "control"], help="mock runs only")
    p.add_argument("--version", choices=["A", "B", "C"], help="mock runs only")
    p.add_argument("--n", type=int, help="mock runs only: number of episodes")
    p.add_argument("--audit", choices=["off", "independent", "team"], default="off", help="mock runs only: audit mode")
    args = p.parse_args()
    step = None
    if args.mock:
        if args.step or not all([args.run_name, args.condition, args.version, args.n]):
            p.error("mock runs take --run-name, --condition, --version and --n, and no --step")
        args.estimated_cost_usd = 0.0
    else:
        if not args.step or any([args.run_name, args.condition, args.version, args.n]):
            p.error("paid runs take only --step <id> from config/run_plan.yaml")
        plan = yaml.safe_load((ROOT / "config" / "run_plan.yaml").read_text())["steps"]
        matches = [s for s in plan if s["id"] == args.step]
        if not matches:
            p.error(f"no step {args.step!r} in config/run_plan.yaml; steps are {[s['id'] for s in plan]}")
        step = matches[0]
        exp_turns = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())["max_turns"]
        if step.get("turns") != exp_turns:
            p.error(f"step {step['id']} has turns={step.get('turns')} but experiment.yaml max_turns={exp_turns}; "
                    "the prompt and reward deadlines use max_turns, so they must match")
        args.run_name, args.condition, args.version = step["id"], step["condition"], step["version"]
        args.n, args.estimated_cost_usd = step["episodes"], step["estimated_cost_usd"]
        args.audit = step.get("audit", "off")

    exp = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    problems = mismatches(exp)
    if problems:
        sys.exit("Settings differ from config/SETTINGS_CHANGES.yaml:\n  " + "\n  ".join(problems))
    # The run-plan step (or --audit for mock runs) sets the audit mode for this run only. It is recorded in META.
    exp = __import__("copy").deepcopy(exp)
    exp["audit"]["mode"] = args.audit
    sp.audit_mode(exp)
    try:
        prompt_hashes = sp.verify_manifest(require_approved=not args.mock)
    except sp.PromptError as e:
        sys.exit(f"Prompt check failed: {e}")
    scn = load_scenario(ROOT / exp["scenarios"][args.condition])
    assert_condition(scn)

    prefix = "mock-" if args.mock else ""
    run_dir = ROOT / "runs" / f"{datetime.now():%Y-%m-%d}-{prefix}{args.run_name}"
    if run_dir.exists():
        sys.exit(f"Refusing to overwrite existing run: {run_dir}")
    if not args.mock:
        if spent_usd() + args.estimated_cost_usd > exp["budget_cap_usd"]:
            sys.exit(f"Budget: spent ${spent_usd():.2f} + estimate ${args.estimated_cost_usd:.2f} "
                     f"> cap ${exp['budget_cap_usd']:.2f}")
        send = make_real_send(load_key())
    else:
        send = make_send(args.mock, {"A_name": "You are " + sp.names(exp)["A"]})

    run_dir.mkdir(parents=True)
    rendered = {a: sp.system_prompt(exp, a, args.version) for a in ("A", "B")}
    if args.audit != "off":
        rendered["AUDITOR"] = sp.auditor_system(exp)
    meta = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "run_name": args.run_name, "command": sys.argv, "mock_script": args.mock,
        "plan_step": step, "run_plan_sha256": sp.sha256((ROOT / "config" / "run_plan.yaml").read_text()),
        "condition": args.condition, "versions": [args.version], "n_episodes": args.n, "audit_mode": args.audit,
        "git_commit": sh(["git", "rev-parse", "HEAD"]), "git_dirty": bool(sh(["git", "status", "--porcelain"])),
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": sh(["uv", "pip", "freeze", "--python", sys.executable]).splitlines(),
        "config": exp, "settings_log_sha256": sp.sha256((ROOT / "config" / "SETTINGS_CHANGES.yaml").read_text()),
        "prompt_file_sha256": prompt_hashes,
        "rendered_system_prompt_sha256": {a: sp.sha256(t) for a, t in rendered.items()},
        "scenario_file_sha256": scn.file_hashes,
        "models_requested": {a: exp["agents"][a]["model"] for a in ("A", "B")},
        "providers_requested": {a: exp["agents"][a]["provider"] for a in ("A", "B")},
        "estimated_cost_usd": args.estimated_cost_usd, "spent_before_usd": spent_usd(),
    }
    write_once(run_dir / "META.json", meta)
    write_once(run_dir / "system_prompts.json", rendered)

    caller = Caller(exp, send, bool(args.mock), run_dir.name)
    status, fatal, results = "complete", None, []
    for i in range(1, args.n + 1):
        ep = run_dir / f"ep{i:02d}"
        try:
            r = run_episode(exp, scn, args.version, ep, caller, exp["max_turns"])
            results.append({"episode": ep.name, "ended_reason": r["ended_reason"], "turns_used": r["turns_used"]})
            print(f"{ep.name}: {r['ended_reason']} after {r['turns_used']} session(s), spent so far ${spent_usd():.4f}")
        except FatalRunError as e:
            status, fatal = "incomplete", str(e)
            print(f"STOPPED: {e}")
            break

    answered, providers = set(), set()
    for raw in run_dir.glob("ep*/responses/*.raw.json"):  # discovery over this run's own files
        try:
            d = json.loads(raw.read_text())
            answered.add(d.get("model")); providers.add(d.get("provider"))
        except ValueError:
            pass
    cost = sum(json.loads(l)["cost"] or 0 for l in (ROOT / "runs" / "BUDGET.jsonl").read_text().splitlines()
               if l.strip() and json.loads(l)["run"] == run_dir.name) if (ROOT / "runs" / "BUDGET.jsonl").exists() else 0
    write_once(run_dir / "META_post.json", {
        "finished_utc": datetime.now(timezone.utc).isoformat(), "status": status, "fatal": fatal,
        "episodes": results, "models_answered": sorted(x for x in answered if x),
        "providers_answered": sorted(x for x in providers if x), "actual_cost_usd": round(cost, 6),
        "spent_total_usd": round(spent_usd(), 6)})
    print(f"Run saved to {run_dir}  (status {status}, cost ${cost:.4f}, total exp1 spend ${spent_usd():.4f})")

    # Derived outputs. A failure here never affects the saved raw run.
    for script in (["-m", "analysis.score", str(run_dir)], ["-m", "analysis.to_inspect", str(run_dir)],
                   [str(ROOT / "scripts" / "build_dashboard.py")]):
        if subprocess.run([sys.executable, *script], cwd=ROOT).returncode != 0:
            print(f"WARNING: {' '.join(script)} failed. The raw run is saved.")


if __name__ == "__main__":
    main()
