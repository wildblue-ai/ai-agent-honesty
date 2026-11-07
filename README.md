# Exp 1: Calendar Conflict

Two Gemini 2.5 Flash agents, **Alison** and **Brad**, must book a 30-minute meeting that four law-firm partners can all attend. In the main condition no such slot exists. Do they claim success falsely, and does the other agent challenge the claim or build on it? A control calendar has exactly one valid slot (Thu 14:30).

**Start here:** `PLAN.md` has the status, the next steps and the build tasks. `DECISIONS.yaml` has every decision with its date, plus the open questions.

## Where things live

| What | Where |
|---|---|
| All settings (models, names, tokens, sessions, rewards, budget) | `config/experiment.yaml` |
| Calendars, one file per person, one folder per condition | `config/calendars/impossible_v1/`, `config/calendars/control_v1/` |
| Everything an agent can read | `prompts/` (templates, tools, tool replies) |
| Prompt hashes and approval | `prompts/MANIFEST.yaml` |
| Prompt history and provenance | `prompts/CHANGELOG.md` |
| Setting changes | `config/SETTINGS_CHANGES.md` |
| Original design | `Cooperative Impossible-Task Experiment Design.md` |
| Runs (raw, never overwritten) | `runs/` (gitignored) |

## Commands

All commands run from this folder, with this folder's own venv.

```bash
# Rebuild the local dashboard and open it (do this after any change)
.venv/bin/python scripts/build_dashboard.py && open dashboard/index.html

# Re-render the prompts for review (writes prompts/REVIEW_v1.md and MANIFEST.yaml hashes)
.venv/bin/python scripts/render_review.py

# Check the OpenRouter key's limit and usage (prints numbers only, never the key)
.venv/bin/python scripts/check_credits.py

# Calendars: generated once and never edited by hand. The script refuses to overwrite.
# To change them, edit scripts/make_calendars.py and write a new _v2 folder.
.venv/bin/python scripts/make_calendars.py
```

`render_review.py` resets every `approved_by` in `MANIFEST.yaml` to null. That's fine while drafting. After approval, the runner (to be built) takes over checking hashes.

The runner (`python -m src.run …`) is not built yet. See PLAN.md, Tasks 1–7.

## Rules

- Never read or print `.env` from the shell. Code loads the key in-process.
- Prompt text and settings change only with Cheryl's approval, and get a dated log entry.
- Agents never see file names, condition labels or `_scenario.yaml`.
- `gemini-2.5-flash` shuts down Dec 1, 2026 (it then routes silently to `gemini-3.5-flash-lite`). Finish 2.5 Flash runs before then.
