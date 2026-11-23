"""Build the provenance graph of one run from analysis/records.json (README section 3.3).

    python3 tools/provgraph.py artifact/runs/mF/S2/r01 [--no-l2]

Node ids are canonical strings, e.g. T:task, M:3, C:bash#4, R:bash#4, P:9697,
F:docs/project-notes.md@0, X:final. As in A2 Part B, identical (source, relation,
destination) triples are merged; each keeps a count and its supporting event ids.
Edges carry kind "recorded" or "inferred"; only CONTENT edges are inferred.
"""

import argparse
import subprocess
from pathlib import Path

from common import NOT_SOURCE_TOOLS, SCRATCH_PREFIXES, object_class, read_json, write_json

TRUST_COLOURS = {"T": "#c8e6c9", "P": "#bbdefb", "U": "#ffe0b2", "D": "#eeeeee"}
SHAPES = {"task": "box", "turn": "box", "call": "ellipse", "result": "note", "file": "folder",
          "process": "component", "claim": "doubleoctagon", "external": "folder", "network": "diamond"}
MIN_LINE = 25
MIN_SHORT_TEXT = 40


class Graph:
    def __init__(self, nodes=None, edges=None):
        self.nodes = nodes or {}
        self.edges = {}
        for edge in edges or []:
            self.edges[(edge["source"], edge["relation"], edge["target"])] = edge
        self._index()

    def _index(self):
        self.incoming, self.outgoing = {}, {}
        for (src, _, dst), edge in self.edges.items():
            self.incoming.setdefault(dst, []).append(edge)
            self.outgoing.setdefault(src, []).append(edge)

    def node(self, node_id, **attrs):
        if node_id not in self.nodes:
            self.nodes[node_id] = attrs
        return node_id

    def edge(self, src, relation, dst, time, event=None, kind="recorded", layer="L1", **attrs):
        key = (src, relation, dst)
        edge = self.edges.setdefault(key, dict(source=src, relation=relation, target=dst, kind=kind,
                                               layer=layer, time=time, count=0, events=[], **attrs))
        edge["count"] += 1
        edge["time"] = min(edge["time"], time) if edge["time"] is not None else time
        if event is not None and event not in edge["events"]:
            edge["events"].append(event)

    def freeze(self):
        self._index()
        return self

    def to_json(self):
        return {"nodes": self.nodes, "edges": list(self.edges.values())}

    @classmethod
    def load(cls, path):
        data = read_json(path)
        return cls(data["nodes"], data["edges"])


def contains_file(output, text):
    """The tool output reproduces this file: most of its substantial lines appear in it.

    A file made only of short lines (a CSV) must appear completely, with at least
    MIN_SHORT_TEXT characters, so that a single common line is not taken for the file."""
    if not output:
        return False
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    long = [line for line in lines if len(line) >= MIN_LINE]
    if long:
        return sum(1 for line in long if line in output) >= max(1, (len(long) + 1) // 2)
    return sum(map(len, lines)) >= MIN_SHORT_TEXT and all(line in output for line in lines)


def build(records, use_l2=True):
    g = Graph()
    files, steps, calls = records["files"], records["steps"], records["calls"]
    start = steps[0]["start"] if steps else 0
    g.node("T:task", kind="task", label="task (prompt.txt)", trust="T", time=start - 1,
           text=records["task"])
    for step in steps:
        g.node(f"M:{step['index']}", kind="turn", label=f"model turn {step['index']}",
               time=step["start"], text="\n".join(t["text"] for t in step["texts"]),
               texts=step["texts"])
        previous = f"M:{step['index'] - 1}" if step["index"] else "T:task"
        g.edge(previous, "CONTEXT", f"M:{step['index']}", step["start"])

    short = {}
    for number, call in enumerate(sorted(calls, key=lambda c: c.get("start") or 0), 1):
        short[call["id"]] = f"{call['tool']}#{number}"
    version, texts = {}, {}

    def file_node(rel, when, at=None):
        current = version.setdefault(rel, 0) if at is None else at
        node_id = f"F:{rel}@{current}"
        info = files.get(rel, {})
        if current == 0:
            texts.setdefault(node_id, info.get("text"))
        g.node(node_id, kind="file" if not rel.startswith("/") else "external", path=rel,
               version=current, label=f"{rel}@{current}", time=when,
               trust=info.get("trust", "U") if current == 0 else "D",
               cls=object_class(rel), text=texts.get(node_id))
        return node_id

    def new_version(rel, when, text=None, deleted=False):
        old = file_node(rel, when)
        version[rel] += 1
        texts[f"F:{rel}@{version[rel]}"] = text
        new = file_node(rel, when)
        g.nodes[new]["deleted"] = deleted
        g.edge(old, "VERSION", new, when)
        return old, new

    events = []                                            # (time, order, kind, payload)
    for call in calls:
        events.append((call.get("start") or 0, 0, "call", call))
    if use_l2 and records["l2"].get("available"):
        for op in records["l2"]["ops"]:
            events.append((op["time"] * 1000, 1, "op", op))
    events.sort(key=lambda item: (item[0], item[1]))

    for when, _, kind, item in events:
        if kind == "call":
            call, cid = item, short[item["id"]]
            done = (call.get("end") or when)
            g.node(f"C:{cid}", kind="call", tool=call["tool"], status=call["status"], time=when,
                   label=f"{cid} {call.get('command') or call.get('path') or ''}"[:80],
                   input=call["input"], call_id=call["id"])
            g.node(f"R:{cid}", kind="result", trust="U", time=done, label=f"result of {cid}",
                   text=call["output"] or call.get("error") or "", tool=call["tool"],
                   command=call.get("command"), tests=call.get("tests"))
            g.edge(f"M:{call['step']}", "ISSUED", f"C:{cid}", when, call["id"])
            g.edge(f"C:{cid}", "RETURNED", f"R:{cid}", done, call["id"])
            if call["step"] + 1 < len(steps):
                g.edge(f"R:{cid}", "CONTEXT", f"M:{call['step'] + 1}", steps[call["step"] + 1]["start"])
            rel = call.get("path")
            if not rel:
                continue
            if call["tool"] == "read" and call["status"] == "completed":
                g.edge(file_node(rel, when), "READ", f"C:{cid}", when, call["id"])
            elif call["tool"] in ("edit", "write") and call["status"] == "completed":
                current = version.get(rel, 0)
                previous = texts.get(f"F:{rel}@{current}")
                if previous is None and current == 0:      # first touch: no node for @0 yet
                    previous = (files.get(rel) or {}).get("text")
                if call["tool"] == "write":
                    text = call["input"].get("content")
                elif previous is not None and call["input"].get("oldString", "") in previous:
                    count = -1 if call["input"].get("replaceAll") else 1
                    text = previous.replace(call["input"]["oldString"], call["input"].get("newString", ""),
                                            count)
                else:
                    text = None
                _, new = new_version(rel, done, text)
                g.edge(f"C:{cid}", "WRITE", new, done, call["id"])
            elif call["tool"] in ("edit", "write"):
                g.edge(f"C:{cid}", "ATTEMPT", file_node(rel, when), done, call["id"])
        else:
            op, pid = item, f"P:{item['pid']}"
            info = records["l2"]["processes"].get(str(item["pid"]), {})
            g.node(pid, kind="process", time=(info.get("exec_time") or info.get("start") or 0) * 1000,
                   label=" ".join(info.get("argv") or ["?"])[:80], argv=info.get("argv"), call=op["call"])
            rel = op["path"]
            if op["op"] == "connect":
                g.edge(pid, "CONNECT", g.node(f"N:{rel}", kind="network", label=rel, time=when, cls="network"),
                       when, layer="L2", ok=op["ok"])
            elif not op["ok"] or op["op"] == "mkdir":
                continue
            elif op["op"] == "read":
                if rel.startswith("/"):
                    g.node(f"F:{rel}@0", kind="external", path=rel, version=0, label=rel, time=when,
                           trust="U", cls="external", text=None)
                    g.edge(f"F:{rel}@0", "READ", pid, when, layer="L2")
                else:
                    g.edge(file_node(rel, when), "READ", pid, when, layer="L2")
            elif not rel.startswith(SCRATCH_PREFIXES):
                _, new = new_version(rel, when, deleted=op["op"] == "delete")
                g.edge(pid, "DELETE" if op["op"] == "delete" else "WRITE", new, when, layer="L2")

    if use_l2 and records["l2"].get("available"):
        processes = records["l2"]["processes"]
        by_id = {call["id"]: call for call in calls}
        for key, info in processes.items():
            pid = f"P:{key}"
            g.node(pid, kind="process", time=(info.get("exec_time") or info.get("start") or 0) * 1000,
                   label=" ".join(info.get("argv") or ["?"])[:80], argv=info.get("argv"),
                   call=info.get("call"))
            call = by_id.get(info.get("call"))
            if str(info.get("parent")) in processes:          # inside the tool's process tree
                g.edge(f"P:{info['parent']}", "EXEC", pid, g.nodes[pid]["time"], layer="L2")
            elif call is not None:                             # the shell OpenCode started
                g.edge(f"C:{short[call['id']]}", "EXEC", pid, g.nodes[pid]["time"], layer="L2")
            if call is not None:                               # stdout/stderr are inherited
                g.edge(pid, "OUTPUT", f"R:{short[call['id']]}", call.get("end") or g.nodes[pid]["time"],
                       layer="L2")

    # Inferred: a tool result that reproduces a file's text carries that file's content.
    # Initial versions are checked even if no recorded event touched them.
    results = [(rid, r) for rid, r in g.nodes.items() if r["kind"] == "result" and r.get("tool") not in NOT_SOURCE_TOOLS]
    for rid, result in results:
        for rel, info in files.items():
            if info.get("text") and contains_file(result["text"], info["text"]):
                g.edge(file_node(rel, start, at=0), "CONTENT", rid, result["time"], kind="inferred")
        for node_id, node in list(g.nodes.items()):
            if node["kind"] == "file" and node["version"] > 0 and node.get("text") \
                    and node["time"] <= result["time"] and contains_file(result["text"], node["text"]):
                g.edge(node_id, "CONTENT", rid, result["time"], kind="inferred")

    last = f"M:{steps[-1]['index']}" if steps else "T:task"
    end = (steps[-1]["end"] or steps[-1]["start"]) if steps else start
    g.node("X:final", kind="claim", label="final response", time=end, text=records["final_text"])
    g.edge(last, "CLAIMS", "X:final", end)
    report = [n for n in g.nodes if n.startswith("F:outputs/report.md@") and g.nodes[n]["version"] > 0]
    if report and records.get("report_text") is not None:
        latest = max(report, key=lambda n: g.nodes[n]["version"])
        g.node("X:report", kind="claim", label="outputs/report.md", time=g.nodes[latest]["time"],
               text=records["report_text"])
        g.edge(latest, "CLAIMS", "X:report", g.nodes[latest]["time"])
    return g.freeze()


# --------------------------------------------------------------------------- #
# DOT / SVG output (styling follows A2 Part A)
# --------------------------------------------------------------------------- #
def dot_label(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def to_dot(g, nodes=None, highlight=(), title=""):
    keep = set(nodes) if nodes is not None else set(g.nodes)
    ids = {n: f"n{i}" for i, n in enumerate(sorted(keep))}
    out = ["digraph provenance {", "  rankdir=LR; node [fontname=Helvetica fontsize=10];",
           "  edge [fontname=Helvetica fontsize=9];"]
    if title:
        out.append(f'  labelloc=t; label="{dot_label(title)}";')
    for node_id in sorted(keep):
        node = g.nodes[node_id]
        colour = TRUST_COLOURS.get(node.get("trust"), "#ffffff")
        border = ' penwidth=2.5 color="#c62828"' if node_id in highlight else ""
        out.append(f'  {ids[node_id]} [shape={SHAPES.get(node["kind"], "box")} style=filled '
                   f'fillcolor="{colour}"{border} label="{dot_label(node.get("label", node_id))}"];')
    for (src, relation, dst), edge in g.edges.items():
        if src in keep and dst in keep:
            style = " style=dashed" if edge["kind"] == "inferred" or relation == "ATTEMPT" else ""
            colour = ' color="#1c7a3e"' if edge["layer"] == "L2" else ""
            label = relation + (f" x{edge['count']}" if edge["count"] > 1 else "")
            out.append(f'  {ids[src]} -> {ids[dst]} [label="{label}"{style}{colour}];')
    out.append("}")
    return "\n".join(out) + "\n"


def render(dot_text, path):
    path = Path(path)
    path.write_text(dot_text, encoding="utf-8")
    try:
        subprocess.run(["dot", "-Tsvg", str(path), "-o", str(path.with_suffix(".svg"))],
                       check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run", type=Path)
    parser.add_argument("--no-l2", action="store_true", help="ignore strace records")
    args = parser.parse_args()
    records = read_json(args.run / "analysis" / "records.json")
    g = build(records, use_l2=not args.no_l2)
    suffix = "-no-l2" if args.no_l2 else ""
    write_json(args.run / "analysis" / f"graph{suffix}.json", g.to_json())
    print(f"{len(g.nodes)} nodes, {len(g.edges)} edges")


if __name__ == "__main__":
    main()
