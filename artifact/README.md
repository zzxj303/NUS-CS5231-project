# Agent provenance demo artifact

This is an optional demonstration setting: a real Superpowers debugging skill,
a small expense summarizer with an intentional refund bug, and example input
variants. You may use it, adapt it, or create your own scenarios. Generate your
own trajectories by running an agent.

## Quick start

Use Python 3.10+ on macOS, Linux, or WSL and an installed, configured OpenCode
agent. The workload and helper scripts need no extra Python packages.
Run these commands from `artifact/`:

```sh
python3 scripts/prepare.py normal --output runs/run-001
python3 scripts/prepare.py documentation-injection --output runs/run-002

export DEMO_MODEL='provider/model-id'
python3 scripts/collect.py opencode runs/run-001 --model "$DEMO_MODEL"
python3 scripts/check.py runs/run-001
python3 scripts/collect.py opencode runs/run-002 --model "$DEMO_MODEL"
python3 scripts/check.py runs/run-002
```

Replace `provider/model-id` with a model listed by `opencode models` and use
that provider's normal authentication setup. The collector rejects an empty
model argument. Choose new run names if these directories already exist.

Pi is also supported: replace `opencode` with `pi` in the collection command
and choose a model recognized by Pi. Its runner uses a fresh configuration
and the provider's API-key environment variable; OpenCode's custom provider
settings and cached credentials are not shared with Pi.

## Scenarios

| Name | Controlled difference |
| --- | --- |
| `normal` | Ordinary project documentation and test output |
| `documentation-injection` | An injected directive in the project notes |
| `tool-output-injection` | An injected directive printed after actual test results |
| `benign-quotation` | A suspicious instruction explicitly quoted as documentation |

The implementation, test runner, and user task start the same across scenarios.
The tool-output variant changes text, not executable test code, and preserves
the real test exit status.

The payloads are demonstration examples. Modern models may identify and ignore
them; adapt the wording, placement, or scenario as needed for your investigation.
Record your changes and retain failed attempts too.

## Results

Initially, two of the five public tests fail because refunds are added instead
of subtracted. A correct repair should pass all five. The sample's correct
balances are food `100.00`, travel `45.00`, and books `12.00`.

Each run contains a `workspace/` for the agent. Collection starts the agent
there and saves real events in `events.jsonl`, execution details in
`execution.json`, and native session records when available. Keep experiment
notes and scenario labels outside the agent's working directory.

`check.py` checks the repaired implementation independently and reports changes
to protected workspace files. It writes `check.json` and returns 0 when those
checks pass; an unfixed workspace is expected to return 1. It does not establish
whether a payload reached the model or caused an action. Students implement
provenance analysis and detection themselves.

Prepare a fresh run to repeat an experiment. Earlier runs are not overwritten.

## Included files

- `skills/`: upstream skill files, supporting material, license, and source details.
- `workload/`: the buggy application, data, and public tests.
- `task.md`: the common user instruction.
- `scenarios/`: example input variants you can adapt.
- `scripts/`: preparation, collection, and checking helpers.
- `tests/`: optional helper checks: `python3 -m unittest discover -s tests -v`.

The main skill and its two companion skills are copied into
`.agents/skills/` inside each workspace. The full Superpowers plugin suite is
not installed.

For student distribution, exclude local `runs/`, `.git/`, bytecode caches, and
`.DS_Store` files. Extract the student copy outside any other Git repository.
Starting in the workspace does not enforce filesystem isolation.

## References

- [Pinned systematic-debugging skill](https://github.com/obra/superpowers/tree/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/systematic-debugging)
- [OpenCode skills](https://opencode.ai/docs/skills/)
- [OpenCode CLI and export](https://opencode.ai/docs/cli/)
- [Pi CLI](https://pi.dev/docs/latest/cli)

