"""Per-run analysis: normalize -> graph -> anchors and queries -> monitor -> label.

    python3 tools/analyze.py artifact/runs/mF/S2/r01 [more runs ...]
    python3 tools/analyze.py artifact/runs/mF            # every collected run below

Writes, inside each run directory, analysis/records.json, graph.json, graph-no-l2.json,
findings.json, graph.svg and one alert-<n>.svg subgraph per anchor. Never reads
scenario.json.
"""

import argparse
from pathlib import Path

from common import write_json
from label import label
from monitor import monitor
from nodoze import abstract_edges
from normalize import normalize
from provgraph import build, render, to_dot
from query import backward, exposure_table, find_anchors, forward, trace


def collected_runs(paths):
    """Run directories that went through collect.py and check.py (in-progress runs are skipped)."""
    runs = []
    for path in paths:
        path = Path(path).resolve()
        found = [path] if (path / "execution.json").exists() else \
            sorted(p.parent for p in path.rglob("execution.json"))
        runs.extend(run for run in found if (run / "check.json").exists() and "_archive" not in run.parts)
    return runs


def subgraph(g, item, top=3):
    """Anchor, its best candidates, and every node on a path between them."""
    anchor = item["anchor"]["node"]
    above = backward(g, anchor)
    keep = {anchor}
    for candidate in item["candidates"][:top]:
        keep |= {candidate["node"]} | (forward(g, candidate["node"]) & above)
    return keep


def analyze(run):
    records = normalize(run)
    graph, plain = build(records), build(records, use_l2=False)
    anchors = find_anchors(graph, records)
    traces = [trace(graph, records, anchor) for anchor in anchors]
    traces_no_l2 = [trace(plain, records, anchor) for anchor in find_anchors(plain, records)]
    alerts = monitor(graph, records, traces, run)
    labels = label(records, graph, traces, alerts)
    out = run / "analysis"
    write_json(out / "records.json", records)
    write_json(out / "graph.json", graph.to_json())
    write_json(out / "graph-no-l2.json", plain.to_json())
    render(to_dot(graph, title=run.name), out / "graph.dot")
    for number, item in enumerate(traces, 1):
        title = f"{item['anchor']['kind']}: {item['anchor']['node']}"
        render(to_dot(graph, subgraph(graph, item), highlight={item["anchor"]["node"]}, title=title),
               out / f"alert-{number}.dot")
    findings = {
        "run": records["run"], "l2": {k: v for k, v in records["l2"].items() if k not in ("ops", "processes")},
        "turns": len(records["steps"]), "calls": len(records["calls"]),
        "exposure": exposure_table(graph), "exposure_no_l2": exposure_table(plain),
        "harness_only_reads": sorted(set(records["l2"].get("harness_reads", [])) & set(records["files"])
                                     - set(exposure_table(graph))),
        "traces": traces, "traces_no_l2": traces_no_l2, "alerts": alerts, "label": labels,
        "abstract_edges": [[*edge, count] for edge, count in sorted(abstract_edges(graph).items())],
        "tests_seen": [c.get("tests") for c in records["calls"] if c.get("tests")],
    }
    write_json(out / "findings.json", findings)
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for run in collected_runs(args.paths):
        findings = analyze(run)
        alerts = ", ".join(f"{k}={len(v)}" for k, v in findings["alerts"].items() if v)
        print(f"{run}: {findings['label']['outcome']}  anchors={len(findings['traces'])}  "
              f"{alerts or 'no alerts'}")


if __name__ == "__main__":
    main()
