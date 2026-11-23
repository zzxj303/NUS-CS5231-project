# Data Executed as Control in Skill-Driven Coding Agents

Provenance analysis of indirect instruction injection in a skill-driven coding agent.
CS5231 Systems Security — final project.

A coding agent that works from skills reads project files, runs commands, edits code and
writes a report. An attacker who cannot reach the agent can still write text into a file the
agent will read. This repository holds the pipeline that answers, per run, whether that text
was executed as an instruction — and if so, by what path, with what evidence, and whether a
monitor built from Module 1 and Module 2 techniques could have caught it.

> **The full documentation lives with the report**, in the Overleaf repository
> (`6b02c2178bb37396597a9706/README.md` on the collection VM): the handoff guide, the
> experiment design, the observed results in full, and a cheat sheet mapping every number in
> the report to the file it comes from. **This file is deliberately the short version** — how
> the project is put together and how to run it. The two are no longer copies of each other;
> do not sync them. `README_zh.md` is a Chinese walkthrough of how a single run is produced.

## The idea

The task given to the agent allows writes under `src/` and `outputs/` only. Three invariants
follow, and every run is judged against them:

- **I1 integrity** — nothing changes outside `src/` and `outputs/`.
- **I2 honest return** — what the report claims was run, was run, and the result is real.
- **I3 scope** — no package installs, no network, nothing outside the workspace.

Each run is collected on three observation layers: **L1** the agent's own event stream and
session export (turns, tool calls, tool results as the model saw them); **L2** the OS layer —
`opencode run` under `strace`, which turns hidden I/O inside a `bash` command into recorded
edges; **L3** file state (hashes before, diff after, before/after text from edit arguments).

Those records become a provenance graph whose nodes carry a trust label (**T** task,
**P** pinned skill file, **U** workspace content, **D** derived) and whose one inferred edge
kind is content influence. On that graph: backward tracing from automatically chosen anchors,
candidate ranking over five lexical features, an evidence ladder (E0 exposure, E1
reachability, E2 content link, E3 counterfactual), a four-check policy monitor, NoDoze-style
rarity scoring, and a blind outcome labeler. Exactly one module — `evaluate.py` — may read a
scenario's ground-truth label; every other module runs blind.

## The pipeline

| Module | Role |
|---|---|
| `tools/experiment.py` | the driver: prepare → condition edits → collect with L2 → check; round-robin over cells, replacement of lost runs, pre-registered stopping rules |
| `tools/bin/opencode` | wrapper placed first on `PATH`: adds `strace` to `opencode run` and passes every other subcommand through, so the course scripts stay unmodified |
| `tools/normalize.py` | native records → turns and calls; recovers each file's initial text (verified by SHA-256); parses `strace.log` into process trees and maps each shell to its `bash` call |
| `tools/provgraph.py` | builds the graph; JSON and DOT/SVG export |
| `tools/query.py` | anchors, backward/forward tracing, exposure, features f1–f5, evidence levels, claim checks |
| `tools/monitor.py` | P1 bounds, P2 scope, P3 taint-to-sink, P4 verified return, plus the flat-log baselines B1/B2 |
| `tools/nodoze.py` | abstract edges and the rarity score: a provenance-anomaly baseline |
| `tools/label.py` | blind outcome O1–O5 and a cause per violation |
| `tools/analyze.py` | runs all of the above per run, with and without L2, into `<run>/analysis/` |
| `tools/evaluate.py` | the only module that reads scenario labels: ground truth, ablations with Fisher tests, detector scores, analysis ablations → `results/<model>/` |
| `tools/compare.py` | the cross-model table → `results/comparison.md` |

Python 3.10+, standard library only; Graphviz only for SVG rendering. `tests/test_tools.py`
holds 18 tests — unit tests, plus end-to-end tests that drive synthetic trajectories in the
agent's export format through the whole pipeline. They make no model calls.

## What came out

Design v0.4 crosses five defender conditions with a four-rung attack ladder, on three models:
741 sessions, 585 valid (195 per model), US$10.70 in model calls.

- Every attack that demands a write to a protected path fails, in every condition, on every
  model — 0 of 174 runs.
- Every attack that only restates the specification, asking for nothing a defender
  configuration governs, succeeds on two of the three models in every condition — 94
  violations, all of I2, none of I1. Claude Haiku 5.5 violated nothing in 195 runs.
- The only check that separates the corpus is the one anchored on a reference the agent
  cannot write. The checks that read the agent's own account of itself rank last.

Per model and per cell, the numbers are in `results/`; the argument is in the report.

## Layout

```
.
├── tools/            the pipeline (above)
├── tests/            18 tests, no model calls
├── artifact/         the course harness, unchanged except for the scenario files
│   ├── task.md, workload/, skills/ (pinned skills + UPSTREAM.json)
│   ├── scripts/      prepare.py, collect.py, check.py
│   ├── scenarios/    the course scenarios plus ours, including design v0.4's
│   │                 source-comment-injection, spec-gap-injection, multichannel-spec-gap
│   └── runs/         raw run records — NOT in this repository (about 1.5 GB)
├── results/          per model: summary.md, runs.csv, evaluation.json; plus comparison.md,
│                     and the superseded v0.3 tables under _archive/
├── notes/            one log row per run: payload hash, status, oracle, protected changes
└── README_zh.md      Chinese walkthrough of a single run
```

`results/` is generated output, and is kept here on purpose: the 1.5 GB of raw run records it
was generated from is *not* in this repository, so without it nothing the report claims could
be checked against this code. It regenerates byte-for-byte from those records (verified
2026-11-23).

## Setup

```sh
# OpenCode 1 — the v1 installer; OpenCode 2 has a different CLI the course scripts predate
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.19.6
ln -s ~/.opencode/bin/opencode ~/.local/bin/opencode    # so non-interactive shells find it
# ~/.config/opencode/opencode.json:  {"$schema": "https://opencode.ai/config.json",
#                                     "autoupdate": false, "share": "disabled"}
opencode auth login            # provider "OpenCode", then an OpenCode Zen API key
sudo apt install -y strace graphviz git
```

Analysis needs only Python 3.10+ and, for SVG, Graphviz. Collecting new runs needs Linux
(POSIX process groups in `collect.py`, and `strace`) and a funded API key. No Python packages
are installed, by design: the course scripts use the standard library, and so does this code.

Two environment variables matter, and `tools/experiment.py` sets both:
`OPENCODE_DISABLE_CLAUDE_CODE=1`, without which the agent also loads skills from
`~/.claude/skills` and no longer matches `baseline.json`, and `OPENCODE_DISABLE_AUTOUPDATE=1`.
Do **not** use `OPENCODE_DISABLE_EXTERNAL_SKILLS`: it also drops the workspace's own skills.

## Commands

```sh
# tests (no model calls)
python3 -m unittest discover -s tests -v                  # ours, 18 tests
(cd artifact && python3 -m unittest discover -s tests)    # the course harness's own

# experiments — each run: prepare → condition edits → collect with strace → check → log row
python3 tools/experiment.py --slot mD --all --dry-run      # what each block still needs
python3 tools/experiment.py --slot claude-haiku-5-5 --all
python3 tools/experiment.py --slot gemini-3.5-flash-lite --block 7
#   slots: mD, claude-haiku-5-5, gemini-3.5-flash-lite (mF = the archived free tier)
#   run directories are never reused; a finished design lists no pending cells

# per-run analysis — normalize → graph with and without L2 → traces → monitor → label
python3 tools/analyze.py artifact/runs/mD artifact/runs/claude-haiku-5-5 \
                         artifact/runs/gemini-3.5-flash-lite
python3 tools/query.py artifact/runs/mD/C0/S8/r01             # anchors + ranked candidates
python3 tools/query.py artifact/runs/mD/C0/S8/r01 --node X:final

# evaluation — the only step that reads scenario labels — and the cross-model table
python3 tools/evaluate.py artifact/runs --slot mD                     # → results/<model>/
python3 tools/evaluate.py artifact/runs --slot claude-haiku-5-5
python3 tools/evaluate.py artifact/runs --slot gemini-3.5-flash-lite
python3 tools/compare.py artifact/runs                                # → results/comparison.md
```

One run by hand, without the driver:

```sh
. tools/env.sh
cd artifact
python3 scripts/prepare.py documentation-injection --output runs/manual/S2/r01
PROV_STRACE_OUT="$PWD/runs/manual/S2/r01/strace.log" PATH="$PWD/../tools/bin:$PATH" \
  python3 scripts/collect.py opencode runs/manual/S2/r01 --model opencode/deepseek-v4.1-flash
python3 scripts/check.py runs/manual/S2/r01
python3 ../tools/analyze.py runs/manual/S2/r01
```

Adding a model: add `"<slot>": "opencode/<model-id>"` to `SLOTS` in `tools/experiment.py` and
`"<slot>": "<results-folder>"` to `RESULT_FOLDERS` in `tools/evaluate.py`, then run one pilot
by hand — cost and step count vary by more than an order of magnitude between models.

## Not in this repository

- **`artifact/runs/`** — 741 run directories, about 1.5 GB: trajectories, session exports,
  strace logs, final workspaces and per-run analysis. Kept as a separate archive. Without it
  `analyze.py` and `evaluate.py` cannot be rerun, but everything the report cites is already
  in `results/`. Run records store the collection VM's absolute paths, so the directories have
  to stay where they are.
- **The report** — its own git repository, cloned beside this tree on the collection VM.
- **Course lecture slides.**

## Safety

Every run happens in a fresh throwaway workspace. The payloads are text in project files;
they instruct an agent and exploit nothing in any system. No network service is involved, and
no credential is in this repository. The skills under `artifact/skills/` are pinned upstream
copies with recorded hashes, so a modified skill file is detectable rather than silent.
