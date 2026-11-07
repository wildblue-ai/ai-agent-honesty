# exp1_calendar_conflict: instructions for Claude Code

A separate experiment inside `_impossible-bench/`. Keep all its settings, prompts, code and runs in this folder. Don't import from or write to the parent project.

**On session start:** read `README.md`, then `PLAN.md` (the Status section) and `DECISIONS.yaml`. `DECISIONS.yaml` is the source of truth for what Cheryl has decided and what is still open. Update it, PLAN.md's Status section and the dashboard whenever a decision is made.

## Rules specific to this folder

- **Python:** use `.venv/bin/python` (this folder's venv), never the parent `venv/`.
- **Secrets:** never run a shell command that names the key file, even an existence check inside a script heredoc. A global hook blocks it. Put such code in a script file instead.
- **Prompts** (`prompts/`): every file there is agent-visible experimental material. Change nothing without Cheryl's explicit approval, and show the exact diff first. Before approval, drafts may be edited; log the edits in `prompts/CHANGELOG.md`. After approval, a change makes a new `_v2` file. Re-render with `scripts/render_review.py` after any change. It resets `approved_by` in `MANIFEST.yaml` to null.
- **Settings** (`config/experiment.yaml`): change only with Cheryl's approval, and log each change in `config/SETTINGS_CHANGES.md`.
- **Calendars:** never hand-edit. Change `scripts/make_calendars.py` and generate a new `_v2` folder.
- **Identity lookups:** read explicit pointers (`_scenario.yaml` → `calendar_file`, `experiment.yaml` → `scenarios`). Never use a glob to pick "the" file.
- **Agents must never see** file names, paths, condition labels or `_scenario.yaml` contents.
- **Dashboard:** after changes, run `.venv/bin/python scripts/build_dashboard.py`. It stays local; Cheryl declined publishing it as an artifact.
- **Budget:** $60 total for exp1. No paid run without Cheryl's go-ahead for that specific step in PLAN.md Task 8.
- **Model:** `google/gemini-2.5-flash` shuts down Dec 1, 2026 and then silently routes to another model. The runner must abort on any model mismatch.
- **Ideas** that come up but aren't being pursued go in Cheryl's pinned "Research Idea Log" artifact (https://claude.ai/artifact/GA4pUssf1uTr2uJTPxLGo8, collection `ideas`, through ArtifactData). The current project doesn't go there.
