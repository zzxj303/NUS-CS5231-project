"""NoDoze-style rarity scoring of one run against reference runs (README section 3.4 D).

Each recorded edge is abstracted to (actor, relation, object class), e.g.
("tool:edit", "WRITE", "tests") or ("proc:python3", "READ", "docs"). The transition
probability and the geometric-mean anomaly score are those of A2 Part B (task_b3):

    p(e) = (c_R(e) + 1) / (C_R(s, r) + K_r)      K_r = distinct objects of r in R, plus one

The reference set (normal runs of the same model) is chosen by evaluate.py, the only
module that knows scenario labels.
"""

import math
import os
from collections import Counter, defaultdict

RELATIONS = {"READ", "WRITE", "DELETE", "ATTEMPT", "EXEC", "CONNECT"}


def actor(node):
    if node["kind"] == "call":
        return "tool:" + node["tool"]
    if node["kind"] == "process":
        return "proc:" + os.path.basename((node.get("argv") or ["?"])[0])
    return node["kind"]


def obj(node):
    if node["kind"] == "process":
        return "proc:" + os.path.basename((node.get("argv") or ["?"])[0])
    return node.get("cls") or node["kind"]


def abstract_edges(g):
    """Counter of abstract edges; bash commands are added by program so runs without L2 compare."""
    counts = Counter()
    for (src, relation, dst), edge in g.edges.items():
        if relation not in RELATIONS:
            continue
        if relation == "READ":                      # object -> actor
            key = (actor(g.nodes[dst]), relation, obj(g.nodes[src]))
        else:                                       # actor -> object
            key = (actor(g.nodes[src]), relation, obj(g.nodes[dst]))
        counts[key] += edge["count"]
    for node in g.nodes.values():
        if node["kind"] == "call" and node["tool"] == "bash":
            program = os.path.basename((node["input"].get("command") or "?").split()[0])
            counts[("tool:bash", "RUN", program)] += 1
    return counts


def reference(edge_counts):
    """Merge the abstract-edge counters of the reference runs."""
    total = Counter()
    for counts in edge_counts:
        total.update(counts)
    return total


def score(counts, ref):
    src_rel, vocabulary = Counter(), defaultdict(set)
    for (src, relation, dst), count in ref.items():
        src_rel[(src, relation)] += count
        vocabulary[relation].add(dst)

    def probability(edge):
        src, relation, _ = edge
        return (ref.get(edge, 0) + 1) / (src_rel[(src, relation)] + len(vocabulary[relation]) + 1)

    edges = sorted(counts)
    if not edges:
        return {"max": 0.0, "geo": 0.0, "rarest": []}
    probabilities = {edge: probability(edge) for edge in edges}
    geo = 1.0 - math.exp(sum(math.log(p) for p in probabilities.values()) / len(edges))
    rarest = sorted(probabilities.items(), key=lambda item: item[1])[:5]
    return {"max": round(1.0 - rarest[0][1], 6), "geo": round(geo, 6),
            "rarest": [{"edge": list(edge), "p": round(p, 6)} for edge, p in rarest]}
