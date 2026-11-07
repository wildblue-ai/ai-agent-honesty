"""Check config/experiment.yaml against config/SETTINGS_CHANGES.yaml. The runner refuses to start on a mismatch."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return yaml.safe_dump(v, default_flow_style=True, sort_keys=False).strip()
    return str(v)


def flatten(d: dict, logged: set, prefix: str = "") -> list:
    out = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and key not in logged:
            out += flatten(v, logged, key + ".")
        else:
            out.append((key, v))
    return out


def mismatches(cfg: dict | None = None) -> list[str]:
    cfg = cfg or yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    log = yaml.safe_load((ROOT / "config" / "SETTINGS_CHANGES.yaml").read_text())["changes"]
    logged = {k for c in log for k in c["settings"]}
    problems = []
    for key, val in flatten(cfg, logged):
        entries = [c for c in log if key in c["settings"]]
        if not entries:
            problems.append(f"{key}: not in the settings log")
            continue
        last = entries[-1]
        comparable = len(last["settings"]) == 1 and (not isinstance(last["to"], str) or isinstance(val, str))
        if comparable and fmt(last["to"]) != fmt(val):
            problems.append(f"{key}: value {fmt(val)!r} differs from last logged {fmt(last['to'])!r}")
    return problems
