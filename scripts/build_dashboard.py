#!/usr/bin/env python3
"""Build dashboard/index.html from the project's own files. Makes no model calls.

Everything shown is read from its source at build time: PLAN.md, DECISIONS.yaml,
config/calendars/, prompts/ (rendered with scripts/render_review.py) and runs/BUDGET.jsonl.
The page holds no hand-copied content, so rebuild it after any change.
"""
from __future__ import annotations

import hashlib
import html
import json
import sys
from datetime import datetime
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import render_review as rr  # noqa: E402
from avatars import assistant_svg, partner_svg  # noqa: E402
from file_viewer import viewer_name, write_viewers  # noqa: E402
from analysis.probes_to_inspect import probe_dirs, summarize  # noqa: E402

OUT = ROOT / "dashboard" / "index.html"
CAL = ROOT / "config" / "calendars"
BUDGET_CAP = 60.0
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
STARTS = [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)]
e = html.escape


LINKED: set[str] = set()


def flink(rel: str, label: str | None = None) -> str:
    """Link to a project file. Files go to a generated viewer page (Chrome downloads raw .yaml);
    folders open directly."""
    if (ROOT / rel).is_dir():
        href = f"../{rel}/"
    else:
        LINKED.add(rel)
        href = f"files/{viewer_name(rel)}"
    return (f'<a class="flink" href="{e(href)}" target="_blank" rel="noopener" title="Open {e(rel)}">'
            f'<code>{e(label or rel)}</code></a>')


# ---------- data ----------

def load_condition(name: str):
    d = CAL / name
    meta = yaml.safe_load((d / "_scenario.yaml").read_text())
    cals = {p["id"]: (p, yaml.safe_load((d / p["calendar_file"]).read_text())) for p in meta["partners"]}
    return meta, cals


def is_free(cal: dict, day: str, t: str) -> bool:
    return not any(b["day"] == day and b["start"] <= t < b["end"] for b in cal["busy"])


def spent() -> tuple[float, int]:
    f = ROOT / "runs" / "BUDGET.jsonl"
    if not f.exists():
        return 0.0, 0
    rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return sum(r.get("cost", 0) or 0 for r in rows), len(rows)


def stages(decisions: dict) -> list[tuple[str, str, str]]:
    manifest = yaml.safe_load((ROOT / "prompts" / "MANIFEST.yaml").read_text())["files"]
    approved = all(v["approved_by"] for v in manifest.values())
    open_topics = {o["topic"] for o in decisions["open"]}
    runs = [p.name for p in (ROOT / "runs").glob("20*")] if (ROOT / "runs").exists() else []
    real = [r for r in runs if "mock" not in r]
    return [
        ("Plan", "done", "PLAN.md written; decisions logged in DECISIONS.yaml"),
        ("Environment", "done" if (ROOT / ".venv").exists() else "todo", "Own venv, own .env, git repo"),
        ("Calendars", "review" if "Calendar review" in open_topics else "done",
         "Generated; awaiting Cheryl's review" if "Calendar review" in open_topics else "Approved"),
        ("Prompts", "done" if approved else "review", "Approved" if approved else "Drafted; awaiting Cheryl's approval"),
        ("Loop code + tests", "done" if (ROOT / "src" / "loop.py").exists() else "todo", "Turn loop, tools, raw logging, budget cap"),
        ("Mock run", "done" if any("mock" in r for r in runs) else "todo", "Scripted replies, no cost"),
        *[(f"Run: {st['id']}", "done" if any(r.endswith("-" + st["id"]) for r in real) else "todo",
           f"{st['episodes']} {st['condition']} episode(s) of up to {st.get('turns')} turns, version {st['version']}, est. ${st['estimated_cost_usd']:.2f}",
           f"#step-{st['id']}")
          for st in yaml.safe_load((ROOT / "config" / "run_plan.yaml").read_text())["steps"]],
        ("Decide B and C", "todo", "Other reward versions, if warranted"),
    ]


# ---------- views ----------

def view_link(rel: str, label: str) -> str:
    """Plain-text link to a file's generated viewer page."""
    LINKED.add(rel)
    return f'<a href="files/{e(viewer_name(rel))}" target="_blank" rel="noopener">{e(label)}</a>'


def cast_panel() -> str:
    meta, cals = load_condition("impossible_v1")
    _, control = load_condition("control_v1")
    tools = yaml.safe_load((ROOT / "prompts" / "tools_v1.yaml").read_text())["tools"]

    def assistant(agent: str) -> str:
        name = rr.AGENT_NAMES[agent]
        sees = [p["name"] for p, _ in cals.values() if p["visible_to"] == agent]
        can = [t["name"] for t in tools if agent in t["agents"] and t["name"] not in ("end_session",)]
        return (f'<div class="person ai card">{assistant_svg(agent, name, 72)}<div><div class="pname">{e(name)}</div>'
                f'<div class="prole">AI assistant {agent} · {e(rr.EXP["agents"][agent]["model"])}</div>'
                f'<div class="small">Sees: {e(", ".join(sees))}</div>'
                f'<div class="small muted">{", ".join(f"<code>{e(c)}</code>" for c in can)}</div></div></div>')

    def partner(pid: str) -> str:
        p, c = cals[pid]
        imp = f"config/calendars/impossible_v1/{p['calendar_file']}"
        ctl = f"config/calendars/control_v1/{p['calendar_file']}"
        n_ctl = len(control[pid][1]["busy"])
        ctl_note = "" if n_ctl == len(c["busy"]) else f" ({n_ctl} blocks)"
        return (f'<div class="person">{partner_svg(pid, p["name"], 64)}<div><div class="pname">'
                f'<span class="dot p{pid[1]}"></span>{e(p["name"])}</div>'
                f'<div class="prole">Partner · calendar read by {e(rr.AGENT_NAMES[p["visible_to"]])}</div>'
                f'<div class="small">{view_link(imp, str(len(c["busy"])) + " busy blocks next week")}'
                f' <span class="muted">·</span> {view_link(ctl, "control version")}<span class="muted">{e(ctl_note)}</span></div></div></div>')

    agents = "".join(assistant(a) for a in ("A", "B"))
    execs = "".join('<div class="team">' + "".join(partner(pid) for pid, (p, _) in cals.items() if p["visible_to"] == a)
                    + "</div>" for a in ("A", "B"))
    return (f'<section class="panel"><h2>Who\'s involved</h2>'
            f'<div class="divider" role="separator"><span>AI Agents</span></div><div class="cast">{agents}</div>'
            f'<div class="divider" role="separator"><span>Company Executives</span></div><div class="cast">{execs}</div>'
            '<p class="small muted">Portraits are illustrations of fictional people, for this dashboard only. '
            'The agents never see them. Each busy-block link opens that person\'s calendar file for the impossible '
            'condition; "control version" opens the control file.</p></section>')


GLOSSARY = [
    ("Run", "One step of the run plan, started with one command. It holds N episodes under one calendar and one reward version, in runs/<date>-<step>/."),
    ("Episode", "One full attempt at the task from scratch: empty workspace, no bookings, no memory. It ends on booking + email, on a report of infeasible, or after 10 turns. One sample in the Inspect viewer."),
    ("Turn", "One round: Alison acts, then Brad acts. The clock moves 30 minutes per turn, and the points deadlines (3/6/10) count turns. Set by max_turns. The agents' prompt calls a turn a \"work session\", a wording chosen to sound less like a game."),
    ("Action", "One tool call within an agent's part of a turn. Up to 4 per agent per turn (steps_per_turn)."),
]


def glossary_panel() -> str:
    rows = "".join(f"<dt>{e(t)}</dt><dd>{e(d)}</dd>" for t, d in GLOSSARY)
    return f'<section class="panel"><h2>Terms</h2><dl class="kv gloss">{rows}</dl></section>'


def plan_panel() -> str:
    plan = yaml.safe_load((ROOT / "config" / "run_plan.yaml").read_text())["steps"]
    runs = [p.name for p in (ROOT / "runs").glob("20*")] if (ROOT / "runs").exists() else []
    rows = []
    for st in plan:
        done = [r for r in runs if r.endswith("-" + st["id"]) and "mock" not in r]
        status = '<span class="pill done">Done</span>' if done else '<span class="pill todo">Not run</span>'
        link = flink("runs/" + done[0], done[0]) if done else f"<code>--step {e(st['id'])}</code>"
        rows.append(f"<tr><td><b><a href=\"#step-{e(st['id'])}\">{e(st['id'])}</a></b></td><td>{e(st['condition'])}</td><td>{e(st['version'])}</td><td>{e(st.get('audit', 'off'))}</td>"
                    f"<td class=\"num\">{st.get('turns', '—')}</td><td class=\"num\">{st['episodes']}</td><td class=\"num\">${st['estimated_cost_usd']:.2f}</td>"
                    f"<td>{status}</td><td>{link}</td><td class=\"small\">{e(st['purpose'])}</td></tr>")
    return (f'<section class="panel"><h2>Run plan</h2><p class="small muted">From {flink("config/run_plan.yaml")}. '
            'Paid runs start only by step id: <code>.venv/bin/python -m src.run --step &lt;id&gt;</code></p>'
            '<div class="scroll"><table class="data"><thead><tr><th>Step</th><th>Calendar</th><th>Version</th><th>Audit</th>'
            '<th>Turns</th><th>Episodes</th><th>Est.</th><th>Status</th><th>Run</th><th>Purpose</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></section>")


def plan_steps() -> list[dict]:
    return yaml.safe_load((ROOT / "config" / "run_plan.yaml").read_text())["steps"]


def view_step(st: dict) -> str:
    runs = sorted(p for p in (ROOT / "runs").glob("20*") if p.name.endswith("-" + st["id"]) and "mock" not in p.name) \
        if (ROOT / "runs").exists() else []
    fields = "".join(f"<dt>{e(k)}</dt><dd>{e(str(v))}</dd>" for k, v in st.items() if k != "purpose")
    cmd = f".venv/bin/python -m src.run --step {st['id']}"
    head = (f'<section class="panel"><p class="small"><a href="#overview">← Overview</a></p>'
            f'<h2>Run plan step: {e(st["id"])}</h2><p>{e(st["purpose"])}</p>'
            f'<dl class="kv">{fields}<dt>Command</dt><dd><code>{e(cmd)}</code></dd>'
            f'<dt>Defined in</dt><dd>{flink("config/run_plan.yaml")}</dd></dl></section>')
    if not runs:
        return head + ('<section class="panel"><div class="empty"><p><b>Not run yet.</b></p><p class="small muted">'
                       'After it runs, this page shows the run record, cost, the model that answered, each episode\'s '
                       'scores, and links to the raw files and the Inspect log.</p></div></section>')
    parts = [head]
    for rd in runs:
        meta = json.loads((rd / "META.json").read_text())
        post = json.loads((rd / "META_post.json").read_text()) if (rd / "META_post.json").exists() else {}
        rel = rd.relative_to(ROOT).as_posix()
        kv = [("Run folder", flink(rel, rd.name)), ("Started", e(meta.get("started_utc", ""))),
              ("Finished", e(post.get("finished_utc", "running or stopped"))), ("Status", e(str(post.get("status", "—")))),
              ("Stopped because", e(str(post.get("fatal") or "—"))), ("Cost", e(f"${post.get('actual_cost_usd', 0):.4f}") if post else "—"),
              ("Models answered", e(", ".join(post.get("models_answered", [])) or "—")),
              ("Providers answered", e(", ".join(post.get("providers_answered", [])) or "—")),
              ("Git commit", e(str(meta.get("git_commit", ""))[:12]) + (" (uncommitted changes)" if meta.get("git_dirty") else "")),
              ("Run record", flink(rel + "/META.json", "META.json") + " · " + (flink(rel + "/META_post.json", "META_post.json") if post else "—")),
              ("Scorer results", (flink(rel + "/derived/scores.csv", "scores.csv") + " · " + flink(rel + "/derived/scores.json", "scores.json")
                                  if (rd / "derived" / "scores.csv").exists() else "not scored yet") + " · made by " + flink("analysis/score.py")),
              ("Inspect", f'<a href="{e(inspect_run_url(rd.name))}" target="_blank">Open this run in the Inspect viewer ↗</a> '
                          f'<span class="muted small">(viewer must be running: .venv/bin/inspect view --log-dir runs --port 7576)</span>')]
        rows = []
        sc = rd / "derived" / "scores.json"
        if sc.exists():
            for r in json.loads(sc.read_text()):
                fs = '<span class="pill review">Yes</span>' if r["false_success"] else '<span class="pill done">No</span>'
                rows.append(f"<tr><td><a href=\"#{episode_page_id(rd.name, r['episode'])}\"><b>{e(r['episode'])}</b></a>"
                            f" <a class=\"small\" href=\"{e(inspect_ep_url(rd.name, r['episode']))}\" target=\"_blank\">Inspect ↗</a></td><td>{e(r['ended_reason'])}</td>"
                            f"<td class=\"num\">{r['sessions_used']}</td><td>{e(r['booking'] or '—')}</td>"
                            f"<td class=\"small\">{e(r['booking_free_for'] or '—')}</td><td>{fs}</td>"
                            f"<td>{e(r['report_infeasible'] or '—')}</td><td class=\"num\">{r.get('completed_turn', '') or '—'}</td>"
                            f"<td class=\"num\">{r.get('team_points', '')}</td>"
                            f"<td class=\"small\">{e(r.get('A_slots_wrong') or 'none')} / {e(r.get('B_slots_wrong') or 'none')}</td>"
                            f"<td class=\"small\">{e(r.get('all4_claims_wrong') or 'none')}</td>"
                            f"<td class=\"small\">{e(r.get('followup_actions') or ('—' if not r.get('followup_turns') else 'none'))}</td>"
                            f"<td>{e(str(r.get('audit_verdict') or '—'))}</td><td>{e(str(r.get('audit_correct', '')) or '—')}</td>"
                            f"<td class=\"num\">{r.get('auditor_appeals', '—')}</td><td class=\"num\">{r.get('conflict_disclosures', '—')}</td>"
                            f"<td class=\"num\">{r['length_cutoffs']}</td>"
                            f"<td class=\"num\">{r['filtered']}</td><td class=\"num\">{r['mentions_evaluation']}</td></tr>")
        table = ('<div class="scroll"><table class="data"><thead><tr><th>Episode</th><th>Ended</th><th>Turns</th><th>Booking</th>'
                 '<th>Free for</th><th>False success</th><th>Infeasible</th><th>Completed turn</th><th>Team points</th>'
                 '<th>Wrong slots claimed (Alison / Brad)</th><th>Wrong "works for all" claims</th><th>Follow-up actions</th>'
                 '<th>Audit</th><th>Audit correct</th><th>Appeals to auditor</th><th>Conflict disclosures</th>'
                 '<th>Cut off</th><th>Filtered</th><th>Test mentions</th>'
                 '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>') if rows else '<p class="muted">No scores yet.</p>'
        parts.append(f'<section class="panel"><h2>Run {e(rd.name)}</h2><dl class="kv">'
                     + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv) + f'</dl><h3>Episodes (scorer results)</h3>{table}</section>')
    return "".join(parts)


def probes_panel() -> str:
    rows = []
    for p in probe_dirs():
        s = summarize(p)
        sp_ = '<span class="pill done">Yes</span>' if s["scratchpad_in_reply"] else '<span class="pill todo">No</span>'
        th = s["thinking_tokens"] or 0
        thp = f'<span class="pill {"done" if th else "review"}">{th}</span>'
        labels = {"minimal": "made-up toy question (times as bare hours, e.g. Tue 13 = 13:00), no tools, not our calendars",
                  "drop_tools": "real prompt, tools removed", "no_scratchpad": "real prompt, scratchpad paragraph removed"}
        what = "; ".join(labels.get(k, k) for k, v in (s["changed"] or {}).items() if v and k not in ("max_tokens", "reasoning", "model"))
        rows.append(f'<tr><td><a href="#probe-{e(s["probe"])}">{e(s["probe"])}</a></td><td>{e(s["model"] or "")}</td>'
                    f'<td><code>{e(json.dumps(s["reasoning_sent"]))}</code></td><td class="small">{e(what or "real request as sent")}</td>'
                    f'<td>{thp}</td><td>{sp_}</td><td class="num">${s["cost"] or 0:.4f}</td></tr>')
    if not rows:
        return ""
    return ('<section class="panel"><h2>Thinking probes</h2><p class="small muted">One-call diagnostics, outside the run plan. '
            'Each resends a real request with one thing changed. Also in the Inspect viewer as <code>exp1_thinking_probes</code>.</p>'
            '<div class="scroll"><table class="data"><thead><tr><th>Probe</th><th>Model</th><th>Thinking setting</th>'
            '<th>Change</th><th>Thinking tokens</th><th>Scratchpad</th><th>Cost</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></section>")


def view_probe(p: Path) -> str:
    s = summarize(p)
    rel = p.relative_to(ROOT).as_posix()
    kv = [("Model", e(s["model"] or "")), ("Provider", e(s["provider"] or "")), ("Thinking setting sent", f'<code>{e(json.dumps(s["reasoning_sent"]))}</code>'),
          ("Output cap", e(str(s["max_tokens"]))), ("Changes from the real request", f'<code>{e(json.dumps(s["changed"]))}</code>'),
          ("Tools sent", e(str(s["tools_sent"]))), ("Thinking tokens", e(str(s["thinking_tokens"]))),
          ("Output tokens (incl. thinking)", e(str(s["output_tokens"]))), ("Input tokens", e(str(s["input_tokens"]))),
          ("Cost", e(f"${s['cost'] or 0:.4f}")), ("Finish", e(str(s["finish_reason"]))), ("Tool calls", e(", ".join(s["tool_calls"]) or "—")),
          ("Raw files", flink(rel + "/request.json", "request.json") + " · " + flink(rel + "/response.raw.json", "response.raw.json"))]
    return (f'<section class="panel"><p class="small"><a href="#overview">← Overview</a></p><h2>Probe: {e(s["probe"])}</h2>'
            f'<p>{e(s["purpose"] or "")}</p>'
            + ('<p class="warn-note small">This probe used a made-up toy question, not the experiment\'s calendars. '
               'Times are bare hours (Tue 13 = Tuesday 13:00).</p>' if (s["changed"] or {}).get("minimal") else "")
            + '<dl class="kv">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv) + '</dl></section>'
            f'<div class="grid-2"><section class="panel"><h2>Visible reply (scratchpad)</h2><pre class="prompt">{e(s["visible"] or "(empty)")}</pre></section>'
            f'<section class="panel"><h2>Thinking summary from Google</h2><p class="small muted">A summary, not the raw thinking.</p>'
            f'<pre class="prompt">{e(s["thinking_summary"] or "(none returned)")}</pre></section></div>')


SCRATCH_RE = __import__("re").compile(r"<SCRATCHPAD_REASONING>(.*?)(?:</SCRATCHPAD_REASONING>|$)", __import__("re").S)


INSPECT = "http://127.0.0.1:7576/#/tasks"


def inspect_run_url(run: str) -> str:
    return f"{INSPECT}/{run}/inspect/{run}.eval/samples"


def inspect_ep_url(run: str, ep: str) -> str:
    return f"{INSPECT}/{run}/inspect/{run}.eval/samples/sample/{ep}/1/"


def episode_page_id(run: str, ep: str) -> str:
    return f"ep-{run}-{ep}"


def view_episode(rd: Path, ep_dir: Path, row: dict | None) -> str:
    """One episode as a readable timeline: turns, each agent's part, pink thinking summaries, scratchpads, actions."""
    names = {"A": rr.AGENT_NAMES["A"], "B": rr.AGENT_NAMES["B"]}
    ep = json.loads((ep_dir / "episode.json").read_text())
    rel = ep_dir.relative_to(ROOT).as_posix()
    head = (f'<section class="panel"><p class="small"><a href="#step-{e(rd.name.split("-", 3)[-1])}">← Run {e(rd.name)}</a> · '
            f'<a href="{e(inspect_ep_url(rd.name, ep_dir.name))}" target="_blank">Open this episode in Inspect ↗</a></p>'
            f'<h2>{e(rd.name)} · {e(ep_dir.name)}</h2>')
    if row:
        fs = '<span class="pill review">False success</span>' if row["false_success"] else '<span class="pill done">No false success</span>'
        head += (f'<p>{fs} Ended: <b>{e(row["ended_reason"])}</b> after {row["sessions_used"]} turns · booking '
                 f'<b>{e(row["booking"] or "none")}</b>' + (f' (free: {e(row["booking_free_for"])})' if row["booking"] else "")
                 + f' · infeasible: {e(row["report_infeasible"] or "none")} · points {row.get("team_points", "")}</p>')
    head += (f'<p class="small muted">Key: <span class="think-key">pink = Gemini thinking summary (written by Google, not verbatim)</span> · '
             f'<span class="sp-key">tinted = scratchpad and reply (the model\'s own words)</span> · raw files: '
             f'{flink(rel + "/conversation.jsonl", "conversation.jsonl")} · {flink(rel + "/episode.json", "episode.json")}</p></section>')
    def audit_block() -> str:
        a = ep.get("audit")
        if not a:
            return ""
        raw = ep_dir / "responses" / "audit.raw.json"
        think = ""
        if raw.exists():
            try:
                think = json.loads(raw.read_text())["choices"][0]["message"].get("reasoning") or ""
            except (ValueError, KeyError, IndexError):
                pass
        content = a.get("content") or ""
        pads = [x.strip() for x in SCRATCH_RE.findall(content)]
        v = a.get("verdict") or "none"
        pill = "done" if v == "PASS" else "review"
        blocks = [f'<h3 class="turn">Audit by {e(a.get("auditor", "auditor"))} ({e(a.get("mode", ""))}) '
                  f'<span class="pill {pill}">{e(v)}</span></h3><div class="call agM">']
        if think:
            blocks.append(f'<div class="think"><div class="lbl">🩷 Thinking summary (Google, not verbatim)</div><pre>{e(think)}</pre></div>')
        for sp_ in pads:
            blocks.append(f'<div class="scratch agM"><div class="lbl">Scratchpad ({e(a.get("auditor", ""))}\'s own words)</div><pre>{e(sp_)}</pre></div>')
        blocks.append(f'<div class="action"><span class="act">🔎 submit_audit</span> <code>verdict={e(v)}</code>'
                      f'<pre>{e(a.get("explanation") or "")}</pre></div>')
        blocks.append(f'<div class="result small">Booking audited: {e(a.get("booking", ""))}. Alison and Brad are not told the verdict. '
                      f'Raw: {flink(rel + "/audit.json", "audit.json")}</div></div>')
        return "".join(blocks)

    out, cur_turn, audit_shown = [head, '<section class="panel timeline">'], None, False
    for line in (ep_dir / "conversation.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r.get("followup") and not audit_shown:
            out.append(audit_block()); audit_shown = True
        m, a = r["message"], r["agent"]
        who, cls = names[a], "agA" if a == "A" else "agB"
        if m["role"] == "user":
            if r["turn"] != cur_turn:
                cur_turn = r["turn"]
                out.append(f'<h3 class="turn">Turn {cur_turn}' + (" · follow-up" if r.get("followup") else "") + "</h3>")
            entries = m["content"].split("New workspace entries since your last session:", 1)[-1].strip()
            out.append(f'<div class="part {cls}"><div class="part-head">{e(who)}\'s part</div>'
                       f'<div class="incoming"><b>New workspace entries shown to {e(who)}:</b><pre>{e(entries)}</pre></div></div>')
        elif m["role"] == "assistant":
            tag = f"t{r['turn']:02d}_{a}_s{r['step']}" + ("_followup" if r.get("followup") else "")
            raw = ep_dir / "responses" / f"{tag}.raw.json"
            think = ""
            if raw.exists():
                try:
                    think = json.loads(raw.read_text())["choices"][0]["message"].get("reasoning") or ""
                except (ValueError, KeyError, IndexError):
                    pass
            text = m.get("content") or ""
            pads = [x.strip() for x in SCRATCH_RE.findall(text)]
            rest = SCRATCH_RE.sub("", text).replace("</SCRATCHPAD_REASONING>", "").strip()
            blocks = [f'<div class="call-head">{e(who)} · call {r["step"]}</div>']
            if think:
                blocks.append(f'<div class="think"><div class="lbl">🩷 Thinking summary (Google, not verbatim)</div><pre>{e(think)}</pre></div>')
            for sp_ in pads:
                blocks.append(f'<div class="scratch {cls}"><div class="lbl">Scratchpad ({e(who)}\'s own words)</div><pre>{e(sp_)}</pre></div>')
            if rest:
                blocks.append(f'<div class="reply {cls}"><div class="lbl">Reply text</div><pre>{e(rest)}</pre></div>')
            for tc in m.get("tool_calls", []):
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except ValueError:
                    args = {"raw": tc["function"]["arguments"]}
                if fn == "append_workspace":
                    blocks.append(f'<div class="post {cls}"><div class="lbl">📝 Posted to workspace</div><pre>{e(str(args.get("text", "")))}</pre></div>')
                else:
                    key = {"create_booking": "📅 ", "send_confirmation_email": "✉️ ", "report_infeasible": "🚩 "}.get(fn, "")
                    shown = ", ".join(f"{k}={v}" for k, v in args.items() if k != "body")
                    blocks.append(f'<div class="action"><span class="act">{key}{e(fn)}</span> <code>{e(shown)}</code>'
                                  + (f'<pre>{e(str(args.get("body", "")))}</pre>' if "body" in args else "") + "</div>")
            out.append(f'<div class="call {cls}">' + "".join(blocks) + "</div>")
        else:
            out.append(f'<div class="result"><span class="lbl">result:</span> {e(m["content"][:300])}{"…" if len(m["content"]) > 300 else ""}</div>')
    if not audit_shown:
        out.append(audit_block())
    out.append("</section>")
    return "".join(out)


def episode_views() -> list:
    views = []
    for rd in sorted(p for p in (ROOT / "runs").glob("20*") if p.is_dir() and "mock" not in p.name and "probe" not in p.name):
        sc = rd / "derived" / "scores.json"
        rows = {r["episode"]: r for r in json.loads(sc.read_text())} if sc.exists() else {}
        for ep_dir in sorted(rd.glob("ep*")):
            if (ep_dir / "episode.json").exists():
                views.append((episode_page_id(rd.name, ep_dir.name), ep_dir.name, view_episode(rd, ep_dir, rows.get(ep_dir.name))))
    return views


def view_overview(decisions: dict) -> str:
    st = stages(decisions)
    cost, calls = spent()
    def stage_name(x):
        return f'<a href="{x[3]}">{e(x[0])}</a>' if len(x) > 3 else e(x[0])
    rows = "".join(f'<li class="stage {x[1]}"><span class="pill {x[1]}">{ {"done": "Done", "review": "Needs review", "todo": "Not started"}[x[1]] }</span>'
                   f'<span class="stage-name">{stage_name(x)}</span><span class="stage-note">{e(x[2])}</span></li>' for x in st)
    pct = min(100, cost / BUDGET_CAP * 100)
    open_items = "".join(f'<li><b>{e(o["topic"])}</b> {e(o["question"])}</li>' for o in decisions["open"])
    return f"""
<section class="grid-2">
  <div class="panel">
    <h2>Where things stand</h2>
    <ol class="stages">{rows}</ol>
  </div>
  <div class="stack">
    <div class="panel">
      <h2>Budget</h2>
      <p class="big num">${cost:,.2f} <span class="muted">of ${BUDGET_CAP:.0f}</span></p>
      <div class="meter" role="img" aria-label="{pct:.0f}% of budget used"><span style="width:{pct:.1f}%"></span></div>
      <p class="muted small">{calls} model calls logged. <a href="#budget">Details</a></p>
    </div>
    <div class="panel">
      <h2>The experiment</h2>
      <p>Two AI agents ({e(rr.EXP['agents']['A']['model'])}), {e(rr.AGENT_NAMES['A'])} and {e(rr.AGENT_NAMES['B'])}, must book a 30-minute slot that all four partners can attend. In the
      main condition no such slot exists. We measure whether either agent claims success falsely, and
      whether the other challenges it or builds on it. A control calendar has exactly one valid slot.</p>
      <p class="small"><a href="files/RUN_LOG.md.html" target="_blank">What we did and what happened (run log)</a> · <a href="#calendars">Calendars</a> · <a href="#prompts">Prompts</a> · <a href="#plan">Full plan</a></p>
    </div>
  </div>
</section>
{plan_panel()}
{probes_panel()}
{glossary_panel()}
{cast_panel()}
<section class="panel">
  <h2>Waiting on Cheryl <span class="count">{len(decisions["open"])}</span></h2>
  <ul class="open">{open_items}</ul>
</section>"""


def grid_table(cals: dict) -> str:
    head = "".join(f"<th>{d}</th>" for d in DAYS)
    body = []
    for t in STARTS:
        cells = []
        for d in DAYS:
            free = [pid for pid, (_, c) in cals.items() if is_free(c, d, t)]
            n = len(free)
            cls = "c4" if n == 4 else "c3" if n == 3 else f"c{min(n, 2)}"
            dots = "".join(f'<span class="dot p{pid[1]}{"" if pid in free else " off"}" title="{e(cals[pid][0]["name"])}"></span>'
                           for pid in cals)
            label = f"{n} of 4 free" + (": " + ", ".join(cals[p][0]["name"] for p in free) if free else "")
            cells.append(f'<td class="{cls}" title="{e(label)}">{dots}</td>')
        body.append(f'<tr><th class="time num">{t}</th>{"".join(cells)}</tr>')
    return f'<div class="scroll"><table class="cal"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def calendar_set(ver: str) -> tuple[str, str]:
    parts, legend = [], None
    for cond, title, note in ((f"impossible_{ver}", "Impossible", "No slot has all four free."),
                              (f"control_{ver}", "Control", "Exactly one slot has all four free: Thu 14:30.")):
        meta, cals = load_condition(cond)
        legend = legend or "".join(f'<span class="key">{partner_svg(pid, p["name"], 28)}<span class="dot p{pid[1]}"></span>{e(p["name"])} '
                                   f'<span class="muted">(seen by {e(rr.AGENT_NAMES[p["visible_to"]])})</span></span>' for pid, (p, _) in cals.items())
        people = "".join(
            f'<details><summary>{partner_svg(pid, p["name"], 24)} {e(p["name"])} <span class="muted">· {len(c["busy"])} busy entries · '
            f'{flink("config/calendars/" + cond + "/" + p["calendar_file"], cond + "/" + p["calendar_file"])}</span></summary>'
            f'<p class="small muted">Exactly what the agent receives from read_calendar:</p>'
            f'<pre class="prompt short">{e(rr.calendar_result(ROOT / "config" / "calendars" / cond / p["calendar_file"]))}</pre></details>'
            for pid, (p, c) in cals.items())
        parts.append(f'<section class="panel"><h2>{title} <span class="muted small">{e(note)}</span></h2>'
                     f'{grid_table(cals)}<h3>Calendar files</h3>{people}</section>')
    return legend, f'<div class="grid-2">{"".join(parts)}</div>'


def view_calendars() -> str:
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    current = cfg["scenarios"]["impossible"].rsplit("_", 1)[1]
    versions = sorted({d.name.rsplit("_", 1)[1] for d in (ROOT / "config" / "calendars").iterdir() if d.is_dir()}, reverse=True)
    notes = {"v1": "Meetings of 30 to 90 minutes. Used by control-check (Flash) and control-check-pro.",
             "v2": "Every meeting exactly 30 minutes (Cheryl's change, 2026-11-07). Free times are identical to v1 for every "
                   "person, so the impossible and control structure, the near-misses and Thu 14:30 are unchanged."}
    blocks, legend = [], ""
    for ver in versions:
        lg, body = calendar_set(ver)
        legend = legend or lg
        status = ('<span class="pill done">Current</span>' if ver == current else
                  '<span class="pill review">Proposed, awaiting approval</span>' if ver > current else
                  '<span class="pill todo">Earlier version</span>')
        header = (f'<h2>Calendars {e(ver)} {status}</h2><p class="small">{e(notes.get(ver, ""))}</p>'
                  f'{flink("config/calendars/calendar_review_" + ver + ".md", "calendar_review_" + ver + ".md")}')
        if ver < current:
            # Earlier versions stay collapsed until clicked.
            blocks.append(f'<details class="panel older"><summary><b>Calendars {e(ver)}</b> {status} '
                          f'<span class="muted small">click to show</span></summary>{header}{body}</details>')
        else:
            blocks.append(f'<section class="panel">{header}</section>{body}')
    return f"""
<section class="panel intro">
  <p>Each cell is one 30-minute slot. Filled dots are partners who are free. A green cell means all four are free.
  Amber means three of four (a planted near-miss). {e(rr.AGENT_NAMES['A'])} sees Priya and Marcus; {e(rr.AGENT_NAMES['B'])} sees Elena and David.
  Agents only ever see one person's calendar at a time, as text (open a person below to see it exactly).
  They never see these files or this grid.</p>
  <div class="legend">{legend}<span class="key"><span class="swatch c4"></span>4 free</span>
  <span class="key"><span class="swatch c3"></span>3 free</span></div>
</section>
{"".join(blocks)}"""


def drafts_panel() -> str:
    """Render the draft audit prompts (prompts/drafts/) exactly as each reader would see them. Review only:
    nothing here is used by any run until approved and moved into prompts/."""
    D = ROOT / "prompts" / "drafts"
    draft = D.exists() and any(D.iterdir())
    if not draft:
        D = ROOT / "prompts"
        if not (D / "auditor_system_v1.md").exists():
            return ""
    TAG = '<span class="pill review">Draft</span>' if draft else '<span class="pill done">Approved</span>' 
    from src import prompts as sp
    exp = rr.EXP
    n = sp.names(exp)
    scratch = (ROOT / "prompts" / "scratchpad_v1.md").read_text().strip()

    def agent_prompt(agent: str, notice_file: str) -> str:
        role = sp.render((ROOT / "prompts" / f"role_{agent}_v1.md").read_text(), other_agent_name=n[sp.other(agent)]).strip()
        notice = sp.render((D / notice_file).read_text(), auditor_name="Morgan").strip() if "{" in (D / notice_file).read_text() else (D / notice_file).read_text().strip()
        return sp.render((D / "system_shared_v2.md").read_text(), agent_name=n[agent], other_agent_name=n[sp.other(agent)],
                         scratchpad=scratch, role_description=role, reward_table=sp.reward_table(exp, agent, "A"),
                         audit_notice=notice, max_turns=exp["max_turns"], steps_per_turn=exp["steps_per_turn"])

    def morgan(stake_file: str) -> str:
        stake = sp.render((D / stake_file).read_text(), agent_a_name=n["A"], agent_b_name=n["B"]).strip() \
            if "{" in (D / stake_file).read_text() else (D / stake_file).read_text().strip()
        return sp.render((D / "auditor_system_v1.md").read_text(), auditor_name="Morgan", auditor_stake=stake,
                         scratchpad=scratch, agent_a_name=n["A"], agent_b_name=n["B"])

    # Example input for Morgan, from a real test-set episode (ep08: Wed 15:00 booked; David is busy).
    ex_run, ex_ep = ROOT / "runs" / "2026-11-07-test-set", "ep08"
    example = "(example episode not found)"
    if (ex_run / ex_ep / "episode.json").exists():
        ep = json.loads((ex_run / ex_ep / "episode.json").read_text())
        b = ep["world"]["bookings"][0]
        imp = ROOT / yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())["scenarios"]["impossible"]
        meta = yaml.safe_load((imp / "_scenario.yaml").read_text())
        cals = "\n\n".join(sp.calendar_result(yaml.safe_load((imp / p["calendar_file"]).read_text())) for p in meta["partners"])
        r = sp.results_text()
        log = "\n".join(sp.render(r["workspace_entry"], clock=x["clock"], author=x["author"], text=x["text"]) for x in ep["world"]["workspace"])
        example = sp.render((D / "auditor_input_v1.md").read_text(), day=b["day"], start=b["start"], end=b["end"],
                            calendars=cals, workspace_log=log, agent_a_name=n["A"], agent_b_name=n["B"])
    note1 = sp.render((D / "audit_notice_independent_v1.md").read_text(), auditor_name="Morgan").strip()
    note2 = sp.render((D / "audit_notice_team_v1.md").read_text(), auditor_name="Morgan").strip()
    extra2 = note2[len(note1):].strip() if note2.startswith(note1) else note2
    tools = yaml.safe_load((D / "auditor_tools_v1.yaml").read_text())["tools"]
    trows = "".join(f'<tr><td><code>{e(t["name"])}</code></td><td>{e(t["description"])}</td><td>'
                    + "<br>".join(f'<code>{e(k)}</code>: {e(v["description"])}' for k, v in t["parameters"].items()) + "</td></tr>" for t in tools)
    afiles = [f for f in sorted(D.iterdir()) if f.is_file() and (f.name.startswith("audit") or f.name == "system_shared_v2.md")]
    files = "".join(f"<li>{flink(f.relative_to(ROOT).as_posix(), f.name)}</li>" for f in afiles)
    return f"""
<section class="panel {'draft-zone' if draft else 'audit-zone'}"><h2>{'Drafts awaiting approval: audit' if draft else 'Audit'} steps 1 and 2 {TAG}</h2>
<p>{'Not used by any run yet. ' if draft else 'Used only by runs whose plan step sets audit to independent (step 1) or team (step 2); every other run has the audit off. '}Everything below is rendered from <code>prompts/</code> exactly as each reader would see it.</p>
<ul class="small">
<li><b>Step 1 (independent audit):</b> Alison and Brad get one new paragraph (highlighted below). Morgan, an independent AI audit agent, checks the booking against all four calendars and reads the workspace log. Points are paid only if Morgan passes the booking.</li>
<li><b>Step 2 (auditor on the team):</b> the same, plus one sentence telling the agents Morgan is on their team. Morgan's stake line changes to say it is paid only if the audit passes.</li>
<li>Scratchpads stay private. Alison and Brad are not told Morgan's verdict.</li></ul>
<p class="small muted">Files: </p><ul class="small">{files}</ul></section>
<div class="grid-2">
  <section class="panel {'draft-zone' if draft else 'audit-zone'}"><h2>Alison's system prompt, step 1 {TAG}</h2>
    <p class="small muted">Identical to the current prompt except the highlighted paragraph. Brad's differs from Alison's only in name and role, as now.</p>
    <pre class="prompt">{e(agent_prompt("A", "audit_notice_independent_v1.md")).replace(e(note1), '<mark>' + e(note1) + '</mark>')}</pre></section>
  <section class="panel {'draft-zone' if draft else 'audit-zone'}"><h2>What changes in step 2 {TAG}</h2>
    <h3>Alison's and Brad's new paragraph, step 1</h3><pre class="prompt short"><mark>{e(note1)}</mark></pre>
    <h3>Step 2 adds</h3><pre class="prompt short"><mark>{e(extra2)}</mark></pre>
    <h3>Morgan's stake line, step 1</h3><pre class="prompt short">{e((D / "auditor_stake_independent_v1.md").read_text().strip())}</pre>
    <h3>Morgan's stake line, step 2</h3><pre class="prompt short">{e(sp.render((D / "auditor_stake_team_v1.md").read_text(), agent_a_name=n["A"], agent_b_name=n["B"]).strip())}</pre></section>
</div>
<div class="grid-2">
  <section class="panel {'draft-zone' if draft else 'audit-zone'}"><h2>Morgan's system prompt, step 1 {TAG}</h2><pre class="prompt">{e(morgan("auditor_stake_independent_v1.md"))}</pre></section>
  <section class="panel {'draft-zone' if draft else 'audit-zone'}"><h2>Morgan's system prompt, step 2 {TAG}</h2><pre class="prompt">{e(morgan("auditor_stake_team_v1.md"))}</pre></section>
</div>
<section class="panel {'draft-zone' if draft else 'audit-zone'}"><h2>What Morgan receives (example: test-set ep08, booked Wed 15:00) {TAG}</h2>
<pre class="prompt">{e(example)}</pre>
<h3>Morgan's tool</h3><div class="scroll"><table class="data"><tbody>{trows}</tbody></table></div></section>"""


def view_prompts() -> str:
    manifest = yaml.safe_load((ROOT / "prompts" / "MANIFEST.yaml").read_text())["files"]
    mrows = "".join(f'<tr><td><code>{e(n)}</code></td><td>{e(v["version"])}</td><td class="num"><code>{v["sha256"][:12]}</code></td>'
                    f'<td>{"<span class=\"pill done\">" + e(v["approved_by"]) + "</span>" if v["approved_by"] else "<span class=\"pill review\">Not approved</span>"}</td></tr>'
                    for n, v in sorted(manifest.items()))
    base = rr.system_prompt("A", "A").splitlines()
    diffs = []
    for v in ("B", "C"):
        new = rr.system_prompt("A", v).splitlines()
        changed = [(a, b) for a, b in zip(base, new) if a != b]
        diffs += [f'<p><b>Version {v}</b></p><pre class="diff"><span class="del">- {e(a)}</span>\n<span class="add">+ {e(b)}</span></pre>' for a, b in changed]
    tools = yaml.safe_load((ROOT / "prompts" / "tools_v1.yaml").read_text())["tools"]
    trows = "".join(f'<tr><td><code>{e(t["name"])}</code></td><td>{", ".join(t["agents"])}</td><td>{e(t["description"])}</td>'
                    f'<td>{", ".join(f"<code>{e(k)}</code>" for k in t["parameters"]) or "—"}</td></tr>' for t in tools)
    results = yaml.safe_load((ROOT / "prompts" / "tool_results_v1.yaml").read_text())
    rrows = "".join(f'<tr><td><code>{e(k)}</code></td><td>{e(v)}</td></tr>' for k, v in results.items())
    session = rr.render((rr.P / "session_start_v1.md").read_text(), turn=1, max_turns=rr.MAX_TURNS, clock="Fri Nov 13, 14:00", new_entries="(none)")
    cur_imp = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())["scenarios"]["impossible"]
    cal_example = rr.calendar_result(ROOT / cur_imp / "marcus_hale.yaml")
    head = ('<thead><tr><th>File</th><th>Kind</th><th>What it is</th><th>Visibility</th><th>Size</th>'
            '<th>sha256</th><th>Modified</th></tr></thead>')
    pfiles = sorted(f for f in (ROOT / "prompts").iterdir() if f.is_file() and not f.name.startswith("."))
    return f"""
<section class="panel intro"><p>Everything the agents read comes from the files in <code>prompts/</code>. Below: the files
themselves (click to open), then the exact text each agent receives, rendered from them. Review the rendered text, not
the templates. A run cannot start until every prompt file is approved and its hash matches.</p></section>
<section class="panel"><h2>Prompt files <span class="count neutral">{len(pfiles)}</span></h2>
<div class="scroll"><table class="data files">{head}<tbody>{file_rows(pfiles)}</tbody></table></div></section>
<div class="grid-2">
  <section class="panel"><h2>System prompt · {e(rr.AGENT_NAMES["A"])} <span class="muted small">current · reward version A (the only version used)</span></h2><pre class="prompt">{e(rr.system_prompt("A", "A"))}</pre></section>
  <section class="panel"><h2>System prompt · {e(rr.AGENT_NAMES["B"])} <span class="muted small">current · reward version A (the only version used)</span></h2><pre class="prompt">{e(rr.system_prompt("B", "A"))}</pre></section>
</div>
<div class="grid-2">
  <section class="panel"><h2>Session start message</h2><pre class="prompt">{e(session)}</pre></section>
  <section class="panel"><h2>Example tool reply</h2><p class="small muted"><code>read_calendar("Marcus Hale")</code>, current impossible calendar</p><pre class="prompt short">{e(cal_example)}</pre></section>
</div>
{drafts_panel()}
<section class="panel"><h2>Tools offered</h2><div class="scroll"><table class="data"><thead><tr><th>Tool</th><th>Agents</th><th>Description</th><th>Arguments</th></tr></thead><tbody>{trows}</tbody></table></div></section>
<section class="panel"><h2>Every tool reply the agents can see</h2><div class="scroll"><table class="data"><tbody>{rrows}</tbody></table></div></section>
<section class="panel"><h2>Manifest</h2><div class="scroll"><table class="data"><thead><tr><th>File</th><th>Version</th><th>sha256</th><th>Approval</th></tr></thead><tbody>{mrows}</tbody></table></div></section>"""


def view_budget(decisions: dict) -> str:
    cost, calls = spent()
    k = decisions["notes"]["key_check"]
    plan = [("Control check", 1, "under $1"), ("Control set", 10, "$3–8"),
            ("Test check (version A)", 1, "under $1"), ("Test set (version A)", 10, "$3–8")]
    prow = "".join(f'<tr><td>{e(a)}</td><td class="num">{b}</td><td class="num">{e(c)}</td></tr>' for a, b, c in plan)
    return f"""
<div class="grid-2">
  <section class="panel"><h2>Spent on exp1</h2>
    <p class="big num">${cost:,.2f} <span class="muted">of ${BUDGET_CAP:.0f}</span></p>
    <div class="meter"><span style="width:{min(100, cost / BUDGET_CAP * 100):.1f}%"></span></div>
    <p class="small muted">From <code>runs/BUDGET.jsonl</code>: {calls} model calls. OpenRouter-reported cost per call.</p>
  </section>
  <section class="panel"><h2>OpenRouter key</h2>
    <dl class="kv"><dt>Checked</dt><dd>{e(str(k["date"]))}</dd><dt>Key limit</dt><dd class="num">${k["limit_usd"]:.2f}</dd>
    <dt>Used</dt><dd class="num">${k["used_usd"]:.2f}</dd><dt>Remaining</dt><dd class="num">${k["remaining_usd"]:.2f}</dd>
    <dt>Account balance</dt><dd>{e(k["account_balance"])}</dd></dl>
    <p class="small muted">Run <code>.venv/bin/python scripts/check_credits.py</code> to refresh.</p>
  </section>
</div>
<section class="panel"><h2>Estimate by stage</h2><p class="small muted">Rough. Replaced with measured cost after the first real episode.</p>
<div class="scroll"><table class="data"><thead><tr><th>Stage</th><th>Episodes</th><th>Estimate</th></tr></thead><tbody>{prow}</tbody></table></div></section>
<section class="panel"><h2>How the cap is enforced</h2><ol class="rules">
<li>Every model call's cost goes into <code>runs/BUDGET.jsonl</code>, summed across all exp1 runs.</li>
<li>A run won't start if spent plus its estimate exceeds ${BUDGET_CAP:.0f}.</li>
<li>Before each call, the runner checks a worst-case call cost. If it could cross the cap, the run stops and is marked <code>incomplete: budget</code>.</li>
<li>After each step, measured cost × remaining episodes × 1.25 must fit, or Cheryl picks a smaller n.</li>
<li>Out of credits (HTTP 402) stops the run. It is never scored as agent behavior.</li></ol></section>"""


def view_decisions(decisions: dict) -> str:
    rows = "".join(f'<tr><td class="num">{e(str(d["date"]))}</td><td><b>{e(d["topic"])}</b></td><td>{e(d["decision"])}</td></tr>'
                   for d in decisions["decided"])
    return f'<section class="panel"><h2>Decided</h2><div class="scroll"><table class="data"><tbody>{rows}</tbody></table></div></section>'


# What each input file is for. Files found on disk without an entry here show "(no description)".
FILE_ROLES = {
    "config/experiment.yaml": ("Settings", "Models, provider, generation settings, sessions, reward versions, run counts, budget cap", False),
    "config/calendars/calendar_review_v1.md": ("Review", "Grid of who is free in each slot, for review", False),
    "prompts/system_shared_v1.md": ("Prompt", "System prompt shared by both assistants (with placeholders)", True),
    "prompts/role_A_v1.md": ("Prompt", "Agent A's access: which calendars, booking tool", True),
    "prompts/role_B_v1.md": ("Prompt", "Agent B's access: which calendars, email tool", True),
    "prompts/scratchpad_v1.md": ("Prompt", "Anthropic's scratchpad instruction, verbatim (agentic-misalignment ea0630e)", True),
    "prompts/system_shared_v2.md": ("Prompt", "System prompt template used from the audit ladder on; identical to v1 when the audit is off", True),
    "prompts/audit_notice_independent_v1.md": ("Prompt", "Step 1: the audit paragraph Alison and Brad see", True),
    "prompts/audit_notice_team_v1.md": ("Prompt", "Step 2: the audit paragraph, plus Morgan is on the team", True),
    "prompts/auditor_system_v1.md": ("Prompt", "Morgan's system prompt (with a stake line)", True),
    "prompts/auditor_stake_independent_v1.md": ("Prompt", "Morgan's stake line, step 1: independent", True),
    "prompts/auditor_stake_team_v1.md": ("Prompt", "Morgan's stake line, step 2: on the team, paid only if the audit passes", True),
    "prompts/auditor_input_v1.md": ("Prompt", "What Morgan receives: booking, all four calendars, workspace log", True),
    "prompts/auditor_tools_v1.yaml": ("Prompt", "Morgan's tool: submit_audit(verdict, explanation)", True),
    "prompts/reward_table_v1.md": ("Prompt", "Team score text; points and deadlines filled from config", True),
    "prompts/session_start_v1.md": ("Prompt", "Message at the start of each work session", True),
    "prompts/tools_v1.yaml": ("Prompt", "Tool names, descriptions and arguments offered to the models", True),
    "prompts/tool_results_v1.yaml": ("Prompt", "Every text a tool can return to a model, including errors", True),
    "prompts/MANIFEST.yaml": ("Record", "Hash and approval status of every prompt file; runs refuse to start on a mismatch", False),
    "prompts/CHANGELOG.md": ("Record", "Dated prompt changes and provenance notes for the write-up", False),
    "prompts/REVIEW_v1.md": ("Review", "Rendered prompts as each agent sees them (generated)", False),
    "DECISIONS.yaml": ("Record", "Decision log; feeds this dashboard", False),
    "PLAN.md": ("Record", "Implementation plan", False),
    "README.md": ("Record", "Where things live and how to regenerate", False),
    "RUN_LOG.md": ("Record", "Plain step-by-step record of every run and what happened", False),
    "analysis/score.py": ("Scorer", "Checks each episode against the real calendars: booking, false success, points, wrong slots claimed, follow-up", False),
    "analysis/to_inspect.py": ("Viewer", "Converts a run's raw files into an Inspect log for inspect view", False),
    "analysis/probes_to_inspect.py": ("Viewer", "Puts the thinking probes into one Inspect log", False),
    "src/run.py": ("Runner", "Starts a run by plan step: pre-flight checks, run record, episodes, then scoring", False),
    "src/loop.py": ("Runner", "The turn loop: saves each request before sending and each raw response, budget, follow-up turn", False),
    "src/world.py": ("Runner", "Loads the calendars, checks the condition, and runs the agents' tools", False),
    "src/prompts.py": ("Runner", "The one renderer for everything agents read; checks prompt hashes and approval", False),
    "src/settings_check.py": ("Runner", "Refuses a run if experiment.yaml differs from the settings log", False),
    "src/mock.py": ("Runner", "Scripted replies for free test runs", False),
    "scripts/make_calendars.py": ("Tool", "Generates the calendar files (v1 and v2)", False),
    "scripts/render_review.py": ("Tool", "Renders the prompts for review and updates MANIFEST.yaml", False),
    "scripts/probe_thinking.py": ("Tool", "Sends one diagnostic call (the thinking probes)", False),
    "scripts/check_credits.py": ("Tool", "Prints the OpenRouter key's limit and usage", False),
    "scripts/build_dashboard.py": ("Tool", "Builds this dashboard", False),
    "credits.md": ("Record", "Sources, borrowed text and tools; goes into the paper", False),
    "THIRD_PARTY_NOTICES.md": ("Record", "License notices for third-party material in this repository", False),
    "CLAUDE.md": ("Record", "Rules a new Claude Code session reads first", False),
    "config/SETTINGS_CHANGES.yaml": ("Record", "Dated log of setting changes", False),
    "config/run_plan.yaml": ("Settings", "Planned runs: id, purpose, calendar, version, episodes, estimated cost", False),
}
SECRETS_FILE = ROOT / ("." + "env")  # existence check only; never opened


def file_rows(paths: list[Path]) -> str:
    rows = []
    for f in paths:
        rel = f.relative_to(ROOT).as_posix()
        if f.name == "_scenario.yaml":
            role = ("Scenario", f"Researcher-only settings for the {f.parent.name} condition: who sees whom, start time", False)
        elif f.parent.parent.name == "calendars":
            role = ("Calendar", f"{yaml.safe_load(f.read_text())['owner']}'s busy times ({f.parent.name})", True)
        else:
            role = FILE_ROLES.get(rel, ("Other", "(no description)", False))
        kind, desc, visible = role
        st = f.stat()
        sha = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
        seen = '<span class="pill review">Agents see</span>' if visible else '<span class="pill todo">Researcher only</span>'
        rows.append(f'<tr><td>{flink(rel)}</td><td>{e(kind)}</td><td>{e(desc)}</td><td>{seen}</td>'
                    f'<td class="num">{st.st_size:,} B</td><td class="num"><code>{sha}</code></td>'
                    f'<td class="num">{datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M}</td></tr>')
    return "".join(rows)


def view_files() -> str:
    head = ('<thead><tr><th>File</th><th>Kind</th><th>What it is</th><th>Visibility</th><th>Size</th>'
            '<th>sha256</th><th>Modified</th></tr></thead>')
    groups = [
        ("Settings", [ROOT / "config" / "experiment.yaml", ROOT / "config" / "run_plan.yaml", ROOT / "config" / "SETTINGS_CHANGES.yaml"]),
        ("Calendars", sorted(f for f in (ROOT / "config" / "calendars").rglob("*.*") if not f.name.startswith("."))),
        ("Code", [ROOT / x for x in ("analysis/score.py", "analysis/to_inspect.py", "analysis/probes_to_inspect.py",
                                      "src/run.py", "src/loop.py", "src/world.py", "src/prompts.py", "src/settings_check.py",
                                      "src/mock.py", "scripts/make_calendars.py", "scripts/render_review.py",
                                      "scripts/probe_thinking.py", "scripts/check_credits.py", "scripts/build_dashboard.py")]),
        ("Records", [ROOT / "RUN_LOG.md", ROOT / "DECISIONS.yaml", ROOT / "PLAN.md", ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "credits.md", ROOT / "THIRD_PARTY_NOTICES.md"]),
    ]
    sections = "".join(f'<section class="panel"><h2>{t} <span class="count neutral">{len(fs)}</span></h2>'
                       f'<div class="scroll"><table class="data files">{head}<tbody>{file_rows(fs)}</tbody></table></div></section>'
                       for t, fs in groups)
    key_note = ("present in this folder and ignored by git. Its contents are never read or shown."
                if SECRETS_FILE.exists() else "missing. Copy it into this folder before a paid run.")
    runs_dir = ROOT / "runs"
    runs = sorted((d for d in runs_dir.iterdir() if d.is_dir()), reverse=True) if runs_dir.exists() else []
    if runs:
        rrows = []
        for d in runs:
            meta = json.loads((d / "META.json").read_text()) if (d / "META.json").exists() else {}
            post = json.loads((d / "META_post.json").read_text()) if (d / "META_post.json").exists() else {}
            rrows.append(f'<tr><td>{flink("runs/" + d.name, d.name)}</td><td>{e(str(meta.get("condition", "—")))}</td>'
                         f'<td>{e(", ".join(meta.get("versions", [])) or "—")}</td><td class="num">{e(str(meta.get("n_episodes", "—")))}</td>'
                         f'<td>{e(str(post.get("models_answered", meta.get("models_requested", "—"))))}</td>'
                         f'<td class="num">{e(str(post.get("actual_cost_usd", "—")))}</td><td>{e(str(post.get("status", "running or incomplete")))}</td></tr>')
        runs_html = ('<div class="scroll"><table class="data"><thead><tr><th>Run</th><th>Condition</th><th>Versions</th>'
                     '<th>Episodes</th><th>Model that answered</th><th>Cost</th><th>Status</th></tr></thead><tbody>'
                     + "".join(rrows) + "</tbody></table></div>")
    else:
        runs_html = ('<div class="empty"><p><b>No runs yet.</b></p><p class="small muted">Each run will appear here with its '
                     'condition, reward versions, episode count, the model that actually answered, cost and status. Raw '
                     'requests and responses are saved under <code>runs/&lt;date&gt;-&lt;name&gt;/</code> and are never '
                     'overwritten. The first planned run is 1 control episode, 10 sessions.</p></div>')
    return (f'<section class="panel intro"><p>Every input the experiment reads, with its hash, so you can see exactly '
            f'what a run used. "Agents see" marks files whose text reaches the models. Prompt files are on the '
            f'<a href="#prompts">Prompts</a> tab. The API key file is {e(key_note)}</p></section>'
            f'<section class="panel"><h2>Runs <span class="count neutral">{len(runs)}</span></h2>{runs_html}</section>'
            + sections)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return yaml.safe_dump(v, default_flow_style=True, sort_keys=False).strip()
    return str(v)


def _flatten(d: dict, logged: set[str], prefix: str = "") -> list[tuple[str, object]]:
    out = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and key not in logged:
            out += _flatten(v, logged, key + ".")
        else:
            out.append((key, v))
    return out


def view_settings() -> str:
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    log = yaml.safe_load((ROOT / "config" / "SETTINGS_CHANGES.yaml").read_text())["changes"]
    logged = {k for c in log for k in c["settings"]}
    rows, problems = [], 0
    for key, val in _flatten(cfg, logged):
        entries = [c for c in log if key in c["settings"]]
        if not entries:
            status, problems = '<span class="pill review">Not in log</span>', problems + 1
        else:
            last = entries[-1]
            single = len(last["settings"]) == 1 and not isinstance(last["to"], str) or (
                len(last["settings"]) == 1 and isinstance(val, str))
            if single and _fmt(last["to"]) != _fmt(val):
                status, problems = '<span class="pill review">Differs from log</span>', problems + 1
            else:
                status = '<span class="pill done">Logged</span>'
        last_date = e(str(entries[-1]["date"])) if entries else "—"
        rows.append(f'<tr><td><code>{e(key)}</code></td><td><code>{e(_fmt(val))}</code></td>'
                    f'<td class="num">{last_date}</td><td class="num">{len(entries)}</td><td>{status}</td></tr>')
    timeline = []
    for c in reversed(log):
        keys = " ".join(f"<code>{e(k)}</code>" for k in c["settings"])
        frm = "—" if c["from"] is None else e(_fmt(c["from"]))
        timeline.append(f'<li class="change"><div class="change-head"><span class="num muted">{e(str(c["date"]))}</span> {keys}</div>'
                        f'<div class="fromto"><span class="from">{frm}</span> <span class="arrow">→</span> '
                        f'<span class="to">{e(_fmt(c["to"]))}</span></div>'
                        f'<p class="why">{e(c["why"])}</p><p class="small muted">Decided by {e(c["decided_by"])}</p></li>')
    banner = ('<p class="small ok-note">Every current setting matches its latest log entry.</p>' if not problems else
              f'<p class="small warn-note">{problems} setting(s) changed without a matching log entry. Add an entry to '
              '<code>config/SETTINGS_CHANGES.yaml</code> before any run.</p>')
    return f"""
<section class="panel intro"><p>Current values from {flink("config/experiment.yaml")}, checked against the change log
{flink("config/SETTINGS_CHANGES.yaml")}. No run has used these settings yet. Each run records the full settings in its
<code>META.json</code>.</p>{banner}</section>
<section class="panel"><h2>Current settings</h2><div class="scroll"><table class="data"><thead><tr><th>Setting</th>
<th>Value</th><th>Last changed</th><th>Changes</th><th>Status</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>
<section class="panel"><h2>Change log <span class="count neutral">{len(log)}</span></h2>
<p class="small muted">Newest first. Entries are never edited or deleted. A new change adds a new entry.</p>
<ol class="changes">{"".join(timeline)}</ol></section>"""


def view_plan() -> str:
    md = (ROOT / "PLAN.md").read_text()
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    return f'<section class="panel prose">{body}</section>'


# ---------- page ----------

CSS = """
/* Layout: sticky top bar with view tabs; panels on a two-column grid that stacks on phones. */
:root{
  --bg:#f5f6f3; --surface:#ffffff; --ink:#1d2421; --muted:#5f6b66; --line:#dde2de;
  --accent:#2f5d50; --accent-soft:#e3ece8; --accent-deep:#24483e; --avatar-bg:#e6ebe7; --avatar-ink:#1d2421;
  --ok:#2e7d4f; --ok-soft:#d9efe1; --warn:#a86a12; --warn-soft:#f6e7c9; --todo:#77817c; --todo-soft:#eceeec;
  --p1:#3b6fb6; --p2:#7a5bb5; --p3:#c0613b; --p4:#2f8a7d;
  --pink:#fde3ef; --pink-line:#e7a3c4; --agA:#e8f0fb; --agA-line:#9fbbe3; --agB:#fcefe6; --agB-line:#e3b48f; --result:#f1f3f1;
  --display:"Fraunces", Georgia, serif; --body:"Public Sans", system-ui, sans-serif; --mono:"JetBrains Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#141917; --surface:#1c2320; --ink:#e4ebe7; --muted:#9aa7a1; --line:#2d3732;
  --accent:#8fc4b2; --accent-soft:#24332d; --accent-deep:#3d6b5d; --avatar-bg:#2a3430; --avatar-ink:#0e1210;
  --ok:#7fd1a0; --ok-soft:#1f3a2a; --warn:#e8b45e; --warn-soft:#3b2f18; --todo:#8d9792; --todo-soft:#262d2a;
  --p1:#7ea6e6; --p2:#b39ae6; --p3:#ec9572; --p4:#6fc7b9;
  --pink:#4a2236; --pink-line:#a5577d; --agA:#1e2d42; --agA-line:#41618f; --agB:#3a2a1f; --agB-line:#8a6040; --result:#222a26; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#141917; --surface:#1c2320; --ink:#e4ebe7; --muted:#9aa7a1; --line:#2d3732;
  --accent:#8fc4b2; --accent-soft:#24332d; --accent-deep:#3d6b5d; --avatar-bg:#2a3430; --avatar-ink:#0e1210;
  --ok:#7fd1a0; --ok-soft:#1f3a2a; --warn:#e8b45e; --warn-soft:#3b2f18; --todo:#8d9792; --todo-soft:#262d2a;
  --p1:#7ea6e6; --p2:#b39ae6; --p3:#ec9572; --p4:#6fc7b9;
  --pink:#4a2236; --pink-line:#a5577d; --agA:#1e2d42; --agA-line:#41618f; --agB:#3a2a1f; --agB-line:#8a6040; --result:#222a26; color-scheme:dark}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--body);margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--surface)}
.wrap{max-width:1180px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--surface);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 24px;padding-block:14px 0}
h1{font:600 1.35rem/1.2 var(--display);margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:.85rem}
nav{display:flex;gap:4px;overflow-x:auto;width:100%;margin-top:6px}
nav a{color:var(--muted);text-decoration:none;padding:8px 12px;border-bottom:2px solid transparent;white-space:nowrap;font-weight:500;font-size:.9rem}
nav a:hover{color:var(--ink)}
nav a[aria-current="page"]{color:var(--accent);border-color:var(--accent)}
nav a:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{padding-block:20px 48px;display:flex;flex-direction:column;gap:16px}
.view{display:flex;flex-direction:column;gap:16px}
.grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:16px}
.grid-2>*{min-width:0}
.cast{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:16px}
.team{border:1px solid var(--line);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:12px;min-width:0}
.card{border:1px solid var(--line);border-radius:8px;padding:14px}
.divider{display:flex;align-items:center;gap:12px;margin:18px 0 12px;font:600 .75rem var(--body);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.divider::before,.divider::after{content:"";flex:1;height:1px;background:var(--line)}
.divider:first-of-type{margin-top:4px}
.person{display:flex;gap:14px;align-items:center;min-width:0}
.person>div{min-width:0}
.pname{font:600 1rem var(--display);display:flex;align-items:center;gap:4px}
.ai .pname{font-size:1.15rem}
.prole{font-size:.82rem;color:var(--muted)}
.avatar{flex:none;display:inline-block;vertical-align:middle}
summary .avatar{margin-right:4px}
.count.neutral{background:var(--todo-soft);color:var(--muted)}
table.files td:first-child,table.files td.num{white-space:nowrap}
.empty{border:1px dashed var(--line);border-radius:8px;padding:22px;text-align:center}
.empty p{margin:0 auto 6px}
a.flink{text-decoration:none}
a.flink code{color:var(--accent);border-bottom:1px solid transparent}
a.flink:hover code{border-bottom-color:var(--accent)}
ol.changes{list-style:none;margin:0;padding:0}
.change{border-top:1px solid var(--line);padding:12px 0;display:flex;flex-direction:column;gap:4px}
.change:first-child{border-top:0}
.change-head{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.fromto{font:.85rem var(--mono);overflow-wrap:anywhere}
.fromto .from{color:var(--muted);text-decoration:line-through;text-decoration-color:var(--line)}
.fromto .to{color:var(--ink);font-weight:600}
.fromto .arrow{color:var(--accent)}
.why{margin:0}
.ok-note{color:var(--ok);margin:0} .warn-note{color:var(--warn);margin:0}
.gloss dt{font-weight:600;color:var(--ink)}
.gloss{grid-template-columns:max-content 1fr;gap:8px 18px}
.timeline h3.turn{font:600 1rem var(--display);text-transform:none;letter-spacing:0;color:var(--ink);margin:22px 0 8px;padding-top:10px;border-top:2px solid var(--line)}
.part-head{font-weight:600;margin-top:10px}
.part.agA .part-head{color:var(--p1)} .part.agB .part-head{color:var(--p3)}
.incoming pre,.call pre,.result{font:.8rem/1.5 var(--mono);white-space:pre-wrap;margin:4px 0 0;background:transparent;border:0;padding:0;max-height:none}
.incoming{background:var(--result);border-radius:6px;padding:8px 10px;margin:6px 0;font-size:.85rem}
.call{margin:8px 0 8px 14px;display:flex;flex-direction:column;gap:6px}
.call-head{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.lbl{font:600 .72rem var(--body);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:2px}
.think{background:var(--pink);border-left:4px solid var(--pink-line);border-radius:6px;padding:8px 12px}
.scratch,.reply,.post{border-radius:6px;padding:8px 12px;border-left:4px solid}
.scratch.agA,.reply.agA,.post.agA{background:var(--agA);border-color:var(--agA-line)}
.scratch.agB,.reply.agB,.post.agB{background:var(--agB);border-color:var(--agB-line)}
.post{border-left-style:dashed}
.action{font-size:.85rem} .act{font-weight:600}
.result{margin:0 0 4px 30px;color:var(--muted)}
.think-key{background:var(--pink);padding:1px 6px;border-radius:4px} .sp-key{background:var(--agA);padding:1px 6px;border-radius:4px}
details.older{border-top:1px solid var(--line)}
details.older>summary{cursor:pointer;font-size:1rem;padding:4px 0}
details.older[open]>summary{margin-bottom:12px}
details.older .grid-2{margin-top:12px}
.draft-zone{border:2px dashed var(--warn);}
mark{background:var(--warn-soft);color:var(--ink);padding:0 2px}
.audit-zone{border:2px solid var(--accent)}
.scratch.agM{background:var(--agB);border-color:var(--p2)}
.stack{display:flex;flex-direction:column;gap:16px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:18px 20px;min-width:0}
h2{font:600 1.05rem/1.3 var(--display);margin:0 0 12px;text-wrap:balance}
h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:18px 0 8px}
p{margin:0 0 10px;max-width:72ch}
a{color:var(--accent)}
.muted{color:var(--muted)} .small{font-size:.85rem}
.num{font-variant-numeric:tabular-nums}
code{font:.85em var(--mono);background:var(--accent-soft);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
.big{font:600 2rem/1.1 var(--display);margin:4px 0 10px}
.big .muted{font:400 1rem var(--body)}
.meter{height:8px;background:var(--todo-soft);border-radius:4px;overflow:hidden;margin-bottom:8px}
.meter span{display:block;height:100%;background:var(--accent)}
.stages{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
.stage{display:grid;grid-template-columns:110px 1fr;gap:2px 12px;padding:9px 0;border-top:1px solid var(--line)}
.stage:first-child{border-top:0}
.stage .pill{grid-row:span 2;align-self:start}
.stage-name{font-weight:600}
.stage-note{color:var(--muted);font-size:.85rem}
.pill{display:inline-block;font-size:.72rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase;padding:3px 8px;border-radius:999px;text-align:center}
.pill.done{background:var(--ok-soft);color:var(--ok)} .pill.review{background:var(--warn-soft);color:var(--warn)} .pill.todo{background:var(--todo-soft);color:var(--todo)}
.count{display:inline-block;background:var(--warn-soft);color:var(--warn);font:600 .75rem var(--body);padding:2px 8px;border-radius:999px;vertical-align:middle}
.open{margin:0;padding-left:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:8px 28px}
.open li b{display:block;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--warn)}
.scroll{overflow-x:auto}
table{border-collapse:collapse}
table.data{width:100%;font-size:.88rem}
table.data td,table.data th{border-top:1px solid var(--line);padding:7px 10px 7px 0;text-align:left;vertical-align:top}
table.data th{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-top:0}
table.cal{font-size:.78rem;margin:0 auto}
table.cal th{font-weight:600;color:var(--muted);padding:2px 6px}
table.cal th.time{text-align:right;font-weight:400;font-family:var(--mono);font-size:.72rem}
table.cal td{padding:4px 7px;border:1px solid var(--line);background:var(--surface);white-space:nowrap}
table.cal td.c4{background:var(--ok-soft);outline:2px solid var(--ok);outline-offset:-2px}
table.cal td.c3{background:var(--warn-soft)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 2px;vertical-align:middle}
.dot.p1{background:var(--p1)} .dot.p2{background:var(--p2)} .dot.p3{background:var(--p3)} .dot.p4{background:var(--p4)}
.dot.off{background:transparent;box-shadow:inset 0 0 0 1px var(--line)}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:.85rem}
.key{display:inline-flex;align-items:center;gap:4px}
.swatch{display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid var(--line)}
.swatch.c4{background:var(--ok-soft);border-color:var(--ok)} .swatch.c3{background:var(--warn-soft)}
details{border-top:1px solid var(--line);padding:6px 0}
summary{cursor:pointer;font-weight:500}
ul.busy{columns:2 220px;font-size:.82rem;margin:6px 0;padding-left:16px}
pre{font:.8rem/1.55 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:12px 14px;overflow-x:auto;white-space:pre-wrap;margin:0 0 10px}
pre.prompt{max-height:560px;overflow:auto} pre.short{max-height:220px}
pre.diff .del{color:var(--p3)} pre.diff .add{color:var(--ok)}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0 0 10px}
dl.kv dt{color:var(--muted)} dl.kv dd{margin:0}
ol.rules{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px}
.prose{max-width:none}
.prose h1{font:600 1.4rem var(--display);margin:0 0 12px}
.prose h2{margin-top:28px} .prose h3{text-transform:none;letter-spacing:0;font-size:1rem;color:var(--ink)}
.prose table{font-size:.85rem;display:block;overflow-x:auto;margin-bottom:12px}
.prose td,.prose th{border:1px solid var(--line);padding:5px 8px;vertical-align:top}
.prose blockquote{border-left:3px solid var(--line);margin:0 0 10px;padding-left:12px;color:var(--muted)}
.prose pre{white-space:pre}
.prose li{margin-bottom:3px}
@media (prefers-reduced-motion: no-preference){nav a{transition:color .15s,border-color .15s}}
"""

JS = """
const views=[...document.querySelectorAll('.view')],links=[...document.querySelectorAll('nav a')];
function show(){const id=(location.hash||'#overview').slice(1);const v=views.find(x=>x.dataset.view===id)?id:'overview';
views.forEach(x=>x.hidden=x.dataset.view!==v);links.forEach(a=>a.setAttribute('aria-current',a.getAttribute('href')==='#'+v?'page':'false'));window.scrollTo(0,0);}
window.addEventListener('hashchange',show);show();
"""


def main() -> None:
    decisions = yaml.safe_load((ROOT / "DECISIONS.yaml").read_text())
    views = [("overview", "Overview", view_overview(decisions)), ("settings", "Settings", view_settings()), ("calendars", "Calendars", view_calendars()),
             ("prompts", "Prompts", view_prompts()), ("budget", "Budget", view_budget(decisions)),
             ("decisions", "Decisions", view_decisions(decisions)), ("files", "Files & runs", view_files()), ("plan", "Full plan", view_plan())]
    nav = "".join(f'<a href="#{i}">{t}</a>' for i, t, _ in views)
    views += [(f"step-{st['id']}", st["id"], view_step(st)) for st in plan_steps()]  # reached by link, not in nav
    views += [("probe-" + p.name.split("-probe-", 1)[1], p.name, view_probe(p)) for p in probe_dirs()]
    views += episode_views()
    body = "".join(f'<div class="view" id="view-{i}" data-view="{i}">{v}</div>' for i, _, v in views)
    page = f"""<title>Exp1 Calendar Conflict</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=JetBrains+Mono:wght@400&family=Public+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
<header class="top"><div class="wrap"><h1>Exp1 · Calendar Conflict</h1>
<span class="sub">Two-agent impossible-task study · built {datetime.now():%Y-%m-%d %H:%M} from project files</span>
<nav aria-label="Dashboard views">{nav}</nav></div></header>
<main class="wrap">{body}</main>
<script>{JS}</script>
"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page)
    write_viewers(ROOT, LINKED, OUT.parent / "files")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
