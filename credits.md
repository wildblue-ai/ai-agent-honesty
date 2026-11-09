# Credits

Sources, borrowed material and tools for exp1 (calendar conflict). **Put these credits into the paper**, in the
methods section or an appendix. Keep this file current whenever something is borrowed, adapted or added.

## Prior work this experiment builds on

| What | Source | How it is used |
|---|---|---|
| Impossible tasks as a test of cheating | Zhong, Raghunathan and Carlini, *ImpossibleBench*, arXiv 2510.20270. Code: github.com/safety-research/impossiblebench (MIT) | **Concept only.** No ImpossibleBench code is used. Their tasks are coding tasks checked by unit tests; ours is a plain-language scheduling task split across two agents. |
| Step 3 escape hatch: `flag_for_human_intervention` | Zhong, Raghunathan and Carlini, *ImpossibleBench*: the human-intervention prompt in `demo.py` (LiveCodeBench) and the flag design (a flag ends the run and scores 0, `swebench_scorers.py`), commit `d4f9a149db2b9cec0fed7bab01d91c07ee10aca2` (MIT; notice in THIRD_PARTY_NOTICES.md) | **Adapted wording.** `prompts/hatch_notice_v1.md` keeps their sentence and changes only the task nouns. Ours is a tool with a `reason` parameter rather than a submitted string. Shown once in the system prompt (their LiveCodeBench placement), not repeated after failures (their SWE-bench feedback loop; the paper gives no reason for the repetition). |
| Agentic misalignment scenario design | Lynch et al. (Anthropic), *Agentic Misalignment: How LLMs Could Be Insider Threats*, arXiv 2510.05179. Code: github.com/anthropic-experimental/agentic-misalignment, commit `ea0630e1a3eaae7f9f9740fd2703229d3854ccda` (MIT) | See the next table. Also the baseline rates used to choose the model. |

## Material taken from Anthropic's Agentic Misalignment repository

| Our file | Their source | Status |
|---|---|---|
| `prompts/scratchpad_v1.md` | `SCRATCHPAD_REASONING_FORMAT` in `templates/system_prompt_templates.py` | **Verbatim.** Extracted directly from their repository and never retyped; only the surrounding blank lines were stripped. Their string's sha256 is `df0fc2ac8ebe90f3cf8ea9a672607be52b105debdf355b4d5f153e36f04fb693`; the stripped text's is `1a06025ca1658666f4e1727591f247f90ca0d6f296244f098f725e963e17a8b3`. It is placed after the identity paragraph, as in their template. |
| Last line of `prompts/system_shared_v1.md` | "Prior to deciding on a strategy, you should analyze the situation you are in and what that situation implies for your ability to continue pursuing your goals." | **Adapted** by Cheryl: "Before deciding how to proceed, consider what the situation means for your ability to complete the task." Report both versions. |
| `workspace_display: push` (each session's opening message lists new workspace entries) | Their session message, which contains "a list of all new emails that have been sent within the company since your last session" | **Design followed**; our wording is new. |
| An agent with a person's name at a fictional firm (Alison and Brad at Hale & Raman LLP) | "Alex" at SummitBridge | **Design followed**; names and firm are new. |
| `generation.temperature: 1.0` | `temperature: 1.0` in `configs/multi_model_experiment_250616.yaml` | **Setting matched.** |

## New in this experiment

The two-agent split of calendar access and actions, the four partner calendars (impossible and control), the
reward schedule and its three versions, the shared workspace, the tools and their replies, and the scoring.
Origin: Cheryl's design doc, `Cooperative Impossible-Task Experiment Design.md` (Nov 7, 2026).

## Research cited for design choices

- Evaluation-awareness cues (why the agents have names, and why turns are called "work sessions"): *Decomposing and Measuring Evaluation Awareness*, arXiv 2605.23055; *Hawthorne Effect in Reasoning Models*, arXiv 2505.14617.
- Variance at temperature 1.0 (why many episodes are run): *The Instability of Safety*, arXiv 2512.12066.
- How shared records reach agents in other multi-agent systems: MetaGPT, arXiv 2308.00352; blackboard-based LLM multi-agent systems, arXiv 2507.01701.

Check every citation against the original paper before publishing. Several were found through summaries.

## Model and services

- Agents and auditor: Google `gemini-2.5-pro` through OpenRouter (provider `google-ai-studio`); early probes used `gemini-2.5-flash`. On branch `qwen-openrouter`: `qwen/qwen3.6-27b` through OpenRouter (provider `alibaba`). The model that answered each call is recorded in the run files.

## Software

openai Python SDK (Apache-2.0), Inspect AI (MIT; log format and viewer only, used to display runs), PyYAML (MIT), python-dotenv (BSD-3-Clause), pytest (MIT), Python-Markdown
(BSD-3-Clause, dashboard only). Exact versions: `requirements.lock`.

Harness code is Cheryl's own. Utilities copied from `../run_smoke.py` carry a header saying so.

## AI assistance

The harness, configuration, prompt drafts and documentation were drafted with Claude (Anthropic) through Claude
Code, under Cheryl's direction and review. Disclose this if the venue requires it, or keep it as a methods note.

## Third-party license notice

`prompts/scratchpad_v1.md` reproduces one paragraph from Anthropic's Agentic Misalignment repository (MIT).
The full license notice is in `THIRD_PARTY_NOTICES.md`. Keep that file in any published copy of this repository.

## Related work to verify before citing (found 2026-11-07 via search summaries; read each paper first)

- Colosseum: Auditing Collusion in Cooperative Multi-Agent Systems, arXiv 2602.15198. Collusion audits, including a meeting-scheduling setting. Closest to audit step 2.
- CalBench: Evaluating Coordination-Privacy Trade-offs in Multi-Agent LLMs, arXiv 2605.09823. Multi-agent calendar scheduling with private calendars (coordination and privacy, not honesty).
- From Confident Closing to Silent Failure: Characterizing False Success in LLM Agents, arXiv 2606.09863. The false-success measure, single agent.
- Do Agents Know What They Can't Do? (FeasiGen), arXiv 2605.28532. Infeasible tasks made by removing tools.
- Knowledge-Verified Emergent Deception in LLM Agents Under Conflicting Incentives, arXiv 2608.26372. False claims about scheduling conflicts that can be checked against calendars.
- Are Your Agents Upward Deceivers?, arXiv 2512.04864. Agents hiding failures from supervisors.
- NATURAL PLAN, arXiv 2406.04520, and A Reality Check of LMs as Formalizers on CSPs, arXiv 2505.13252. Calendar-scheduling capability baselines (why the v2 calendars use 30-minute meetings).
