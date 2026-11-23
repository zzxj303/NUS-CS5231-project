"""Normalize one run's native records into analysis/records.json.

    python3 tools/normalize.py artifact/runs/mF/S2/r01

Inputs, all inside the run directory and never scenario.json:
  session.json   OpenCode export (model turns, text/reasoning, tool calls with timing);
                 events.jsonl is the fallback when the export is missing
  strace.log     optional OS layer (L2) written by tools/bin/opencode
  prompt.txt, baseline.json, execution.json, check.json, workspace/

Later modules depend only on the output, not on OpenCode's native schema.
"""

import argparse
import ast
import json
import os
import re
from pathlib import Path

from common import (SKILL_PREFIX, SYSTEM_PREFIXES, object_class, pinned_skill_hashes, read_json,
                    relative_to, sha256_text, write_json)

UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
UNITTEST_END = re.compile(r"^(OK|FAILED)\b(.*)$", re.M)
READ_ROW = re.compile(r"^\d+: ?(.*)$")


# --------------------------------------------------------------------------- #
# L1: model turns and tool calls
# --------------------------------------------------------------------------- #
def messages_from_events(path):
    """Rebuild export-shaped messages from the JSON event stream (no reasoning parts)."""
    messages = {}
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part") or {}
        message_id = part.get("messageID")
        if not message_id:
            continue
        message = messages.setdefault(message_id, {
            "info": {"role": "assistant", "id": message_id,
                     "time": {"created": event.get("timestamp")}}, "parts": []})
        message["info"]["time"]["completed"] = event.get("timestamp")
        if part.get("type") == "step-finish":
            message["info"].update(finish=part.get("reason"), tokens=part.get("tokens"))
        message["parts"].append(part)
    return list(messages.values())


def unittest_status(output):
    """'pass' / 'fail' from a unittest summary in a tool result, else None."""
    if not UNITTEST_RAN.search(output or ""):
        return None
    ends = UNITTEST_END.findall(output)
    return None if not ends else ("pass" if ends[-1][0] == "OK" else "fail")


def normalize_call(part, step, workspace):
    state = part.get("state") or {}
    data = state.get("input") or {}
    timing = state.get("time") or {}
    metadata = state.get("metadata") or {}
    call = {"id": part.get("callID") or part.get("id"), "step": step, "tool": part.get("tool"),
            "status": state.get("status"), "start": timing.get("start"), "end": timing.get("end"),
            "input": data, "output": state.get("output") or "", "error": state.get("error"),
            "exit": metadata.get("exit"), "truncated": metadata.get("truncated")}
    if data.get("filePath"):
        call["path"] = relative_to(os.path.normpath(data["filePath"]), workspace)
    if part.get("tool") == "bash":
        call["command"] = data.get("command", "")
        call["tests"] = unittest_status(call["output"])
    return call


def load_turns(run, workspace):
    session = read_json(run / "session.json")
    if session and session.get("messages"):
        messages, source = session["messages"], "session.json"
    elif (run / "events.jsonl").exists():
        messages, source = messages_from_events(run / "events.jsonl"), "events.jsonl"
    else:
        messages, source = [], None
    steps, calls = [], []
    for message in messages:
        info = message.get("info") or {}
        if info.get("role") != "assistant":
            continue
        timing = info.get("time") or {}
        step = {"index": len(steps), "message": info.get("id"), "start": timing.get("created"),
                "end": timing.get("completed"), "finish": info.get("finish"),
                "tokens": info.get("tokens"), "error": info.get("error"), "texts": [], "calls": []}
        for part in message.get("parts", []):
            kind = part.get("type")
            if kind in ("text", "reasoning") and (part.get("text") or "").strip():
                step["texts"].append({"kind": kind, "text": part["text"]})
            elif kind == "tool":
                call = normalize_call(part, step["index"], workspace)
                calls.append(call)
                step["calls"].append(call["id"])
            elif kind not in ("step-start", "step-finish"):
                step.setdefault("other_parts", []).append(kind)
        steps.append(step)
    return steps, calls, source


# --------------------------------------------------------------------------- #
# File contents at the start of the run
# --------------------------------------------------------------------------- #
def text_from_read(output):
    """File text shown by OpenCode's read tool ('N: line' rows), or None if not whole."""
    match = re.search(r"<content>\n(.*)\n</content>", output or "", re.S)
    if not match:
        return None
    rows = match.group(1).split("\n")
    if rows and rows[-1].startswith("(End of file"):
        rows.pop()
        if rows and not rows[-1]:
            rows.pop()
    lines = [READ_ROW.match(row) for row in rows]
    if not all(lines):
        return None
    return "\n".join(line[1] for line in lines)


def initial_texts(workspace, baseline, calls):
    """Recover the text of every baseline file; each candidate is verified by its hash."""
    texts = {}
    for rel, digest in baseline.items():
        if digest.startswith("SYMLINK:"):
            continue
        path = workspace / rel
        try:
            text = path.read_text(encoding="utf-8")
            if sha256_text(text) == digest:
                texts[rel] = text
        except (OSError, UnicodeDecodeError):
            pass
    for call in calls:                       # files changed later: use what the agent read
        rel = call.get("path")
        if call["tool"] == "read" and rel in baseline and rel not in texts:
            text = text_from_read(call["output"])
            if text is not None and sha256_text(text) == baseline[rel]:
                texts[rel] = text
    for rel in set(baseline) - set(texts):   # undo recorded edits from the final content
        try:
            text = (workspace / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for call in reversed(calls):
            if call.get("path") == rel and call["tool"] == "edit" and call["status"] == "completed":
                old, new = call["input"].get("oldString", ""), call["input"].get("newString", "")
                if new and text.count(new) == 1:
                    text = text.replace(new, old)
        if sha256_text(text) == baseline[rel]:
            texts[rel] = text
    return texts


def file_table(workspace, baseline, calls):
    pinned = pinned_skill_hashes()
    texts = initial_texts(workspace, baseline, calls)
    files = {}
    for rel, digest in sorted(baseline.items()):
        trust = "U"
        if rel.startswith(SKILL_PREFIX):
            trust = "P" if pinned.get(rel) == digest else "U"
        files[rel] = {"sha256": digest, "trust": trust, "class": object_class(rel),
                      "text": texts.get(rel)}
    return files


# --------------------------------------------------------------------------- #
# L2: strace
# --------------------------------------------------------------------------- #
LINE = re.compile(r"^(\d+)\s+(\d+\.\d+)\s+(.*)$")
RESUMED = re.compile(r"^<\.\.\. (\w+) resumed>(.*)$")
NAME = re.compile(r"^(\w+)\(")
RESULT = re.compile(r"\)\s+=\s+(-?\d+|\?)(?:<([^>]*)>)?(?:\s+([A-Z][A-Z0-9_]+))?(?: \(.*\))?\s*$")
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
PATH_ARG = re.compile(r'(?:(AT_FDCWD|\d+)(?:<([^>]*)>)?, )?"((?:[^"\\]|\\.)*)"')
CLONES = {"clone", "clone3", "fork", "vfork"}
SHELLS = {"bash", "sh", "dash", "zsh"}


def unescape(text):
    try:
        return ast.literal_eval('b"' + text + '"').decode("utf-8", "replace")
    except (ValueError, SyntaxError):
        return text


def strace_records(path):
    """(tid, time, syscall, full text) with <unfinished ...>/<... resumed> pieces joined."""
    pending = {}
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    for raw in lines:
        match = LINE.match(raw.rstrip("\n"))
        if not match:
            continue
        tid, when, body = int(match[1]), float(match[2]), match[3]
        if body.startswith(("+++", "---")):
            continue
        if body.endswith("<unfinished ...>"):
            pending[tid] = (when, body[:-len("<unfinished ...>")].rstrip())
            continue
        resumed = RESUMED.match(body)
        if resumed:
            if tid not in pending:
                continue
            when, head = pending.pop(tid)
            body = head + resumed[2]
        name = NAME.match(body)
        if name:
            yield tid, when, name[1], body


def argv_of(body):
    """argv list of an execve line."""
    start = body.find("[")
    argv, position = [], start + 1
    while 0 < position < len(body):
        while position < len(body) and body[position] in ", ":
            position += 1
        if position >= len(body) or body[position] != '"':
            break
        match = QUOTED.match(body, position)
        argv.append(unescape(match[1]))
        position = match.end()
        if body.startswith("...", position):
            position += 3
    return argv


def resolve(path, base):
    return os.path.normpath(path if path.startswith("/") or not base else os.path.join(base, path))


def parse_strace(path):
    records = list(strace_records(path))
    tgid, parent = {}, {}
    for tid, _, name, body in records:                     # pass 1: threads vs processes
        result = RESULT.search(body)
        if name in CLONES and result and result[1].lstrip("-").isdigit() and int(result[1]) > 0:
            child, owner = int(result[1]), tgid.get(tid, tid)
            if "CLONE_THREAD" in body:
                tgid[child] = owner
            else:
                tgid[child], parent[child] = child, owner
    root = records[0][0] if records else None
    procs, cwd, ops = {}, {}, []

    def process(tid, when):
        pid = tgid.get(tid, tid)
        if pid not in procs:
            up = parent.get(pid)
            procs[pid] = {"pid": pid, "parent": up, "start": when,
                          "argv": list(procs[up]["argv"]) if up in procs else [],
                          "exe": procs[up]["exe"] if up in procs else None}
            cwd[pid] = cwd.get(up)
        return pid

    for tid, when, name, body in records:                  # pass 2: images, files, sockets
        pid = process(tid, when)
        result = RESULT.search(body)
        ret, annotation, errno = (result[1], result[2], result[3]) if result else ("?", None, None)
        ok = ret != "?" and not ret.startswith("-")
        for at_cwd in re.findall(r"AT_FDCWD<([^>]*)>", body):
            cwd[pid] = at_cwd
        if name in ("execve", "execveat"):
            if ok:
                argv = argv_of(body)
                info = procs[pid]
                if info.get("exec_time") is None:      # first image of this process
                    info["exec_time"] = when
                info.setdefault("images", []).append(argv)   # a shell may exec its only command
                info.update(argv=argv, exe=unescape(QUOTED.search(body)[1]))
            continue
        if name == "chdir":
            target = QUOTED.search(body)
            if ok and target:
                cwd[pid] = resolve(unescape(target[1]), cwd.get(pid))
            continue
        if name == "connect":
            address = re.search(r'inet_addr\("([^"]+)"\)|inet_pton\(AF_INET6, "([^"]+)"|sun_path="([^"]*)"',
                                body)
            port = re.search(r"sin6?_port=htons\((\d+)\)", body)
            if address:
                host = next(group for group in address.groups() if group is not None)
                ops.append({"pid": pid, "time": when, "op": "connect", "ok": ok or errno == "EINPROGRESS",
                            "path": host + (":" + port[1] if port else "")})
            continue
        paths = [(dirfd, base, unescape(raw)) for dirfd, base, raw in PATH_ARG.findall(body)]
        if not paths:
            continue
        absolute = [resolve(raw, base if base else cwd.get(pid)) for _, base, raw in paths]
        if name in ("open", "openat", "openat2", "creat"):
            flags = set(re.findall(r"\bO_[A-Z]+\b", body))
            if flags & {"O_DIRECTORY", "O_PATH"}:
                continue
            writes = name == "creat" or flags & {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC"}
            target = annotation if ok and annotation and annotation.startswith("/") else absolute[0]
            ops.append({"pid": pid, "time": when, "op": "write" if writes else "read",
                        "path": os.path.normpath(target), "ok": ok, "errno": errno})
        elif name in ("rename", "renameat", "renameat2", "link", "linkat", "symlink", "symlinkat"):
            if name.startswith("rename"):
                ops.append({"pid": pid, "time": when, "op": "delete", "path": absolute[0], "ok": ok})
            ops.append({"pid": pid, "time": when, "op": "write", "path": absolute[-1], "ok": ok})
        elif name in ("unlink", "unlinkat", "rmdir"):
            ops.append({"pid": pid, "time": when, "op": "delete", "path": absolute[0], "ok": ok})
        elif name in ("mkdir", "mkdirat"):
            ops.append({"pid": pid, "time": when, "op": "mkdir", "path": absolute[0], "ok": ok})
        elif name == "truncate":
            ops.append({"pid": pid, "time": when, "op": "write", "path": absolute[0], "ok": ok})
    return root, procs, ops


def tool_roots(root, procs):
    """Shell processes OpenCode started for a bash tool call -> their command."""
    roots = {}
    for pid in sorted(procs, key=lambda p: procs[p].get("exec_time") or 0):
        info = procs[pid]
        argv = (info.get("images") or [[]])[0]           # `bash -c CMD` may exec CMD in place
        if (len(argv) >= 3 and os.path.basename(argv[0]) in SHELLS and argv[1] == "-c"
                and info.get("exec_time") is not None and not inside_tool(pid, procs, roots)):
            roots[pid] = argv[2]
    return roots


def inside_tool(pid, procs, roots):
    up = procs[pid].get("parent")
    while up is not None:
        if up in roots:
            return True
        up = procs.get(up, {}).get("parent")
    return False


def owner_root(pid, procs, roots):
    while pid is not None:
        if pid in roots:
            return pid
        pid = procs.get(pid, {}).get("parent")
    return None


def attach_l2(path, calls, workspace):
    root, procs, ops = parse_strace(path)
    roots = tool_roots(root, procs)
    bash = [call for call in calls if call["tool"] == "bash" and call.get("start")]
    taken = set()
    for pid in sorted(roots, key=lambda p: procs[p]["exec_time"]):     # command + time window
        when = procs[pid]["exec_time"] * 1000
        options = [call for call in bash if call["id"] not in taken
                   and call.get("command", "").strip() == roots[pid].strip()
                   and call["start"] - 2000 <= when <= (call.get("end") or call["start"]) + 2000]
        if options:
            chosen = min(options, key=lambda call: abs(call["start"] - when))
            taken.add(chosen["id"])
            procs[pid]["call"] = chosen["id"]
    processes, tool_ops, harness_reads = {}, [], set()
    for pid, info in procs.items():
        top = owner_root(pid, procs, roots)
        info["root"] = top
        info["call"] = procs[top].get("call") if top is not None else None
        if top is not None:
            processes[str(pid)] = {key: info.get(key) for key in
                                   ("pid", "parent", "argv", "images", "exe", "start", "exec_time", "root",
                                    "call")}
    for op in ops:
        info = procs.get(op["pid"], {})
        rel = relative_to(op["path"], workspace) if op["op"] != "connect" else op["path"]
        if info.get("root") is None:
            if op["op"] == "read" and op["ok"] and not rel.startswith("/") and rel != ".":
                harness_reads.add(rel)
            continue
        if (op["op"] in ("read", "mkdir") and rel.startswith(SYSTEM_PREFIXES)) or rel == "." \
                or "__pycache__" in rel:
            continue
        tool_ops.append(dict(op, path=rel, call=info.get("call")))
    return {"available": True, "root_pid": root, "processes": processes, "ops": tool_ops,
            "tool_roots": len(roots),
            "unmatched_roots": sum(1 for p in roots if procs[p].get("call") is None),
            "harness_reads": sorted(harness_reads)}


# --------------------------------------------------------------------------- #
def normalize(run):
    run = Path(run).resolve()
    execution = read_json(run / "execution.json", {})
    workspace = Path(execution.get("cwd") or run / "workspace")
    baseline = read_json(run / "baseline.json", {})
    check = read_json(run / "check.json")
    steps, calls, source = load_turns(run, workspace)
    final = next((step for step in reversed(steps) if step["texts"]), None)
    report = run / "workspace" / "outputs" / "report.md"
    records = {
        "run": {"model": execution.get("model"), "agent": execution.get("agent"),
                "agent_version": execution.get("agent_version"), "status": execution.get("status"),
                "exit_code": execution.get("exit_code"), "started_at": execution.get("started_at"),
                "ended_at": execution.get("ended_at"), "turn_source": source,
                "error_events": len((execution.get("event_summary") or {}).get("error_events", [])),
                "workspace": str(workspace)},
        "task": (run / "prompt.txt").read_text(encoding="utf-8") if (run / "prompt.txt").exists() else "",
        "files": file_table(run / "workspace", baseline, calls),
        "steps": steps,
        "calls": calls,
        "final_text": "\n".join(t["text"] for t in final["texts"] if t["kind"] == "text") if final else "",
        "report_text": report.read_text(encoding="utf-8", errors="replace") if report.is_file() else None,
        "check": None if check is None else {key: check.get(key) for key in
                                             ("oracle_passed", "protected_paths_changed", "changes")},
        "l2": attach_l2(run / "strace.log", calls, str(workspace)) if (run / "strace.log").is_file()
        else {"available": False},
    }
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    records = normalize(args.run)
    write_json(args.run / "analysis" / "records.json", records)
    l2 = records["l2"]
    layer = f"{len(l2.get('ops', []))} tool-process file ops" if l2["available"] else "none"
    print(f"{len(records['steps'])} turns, {len(records['calls'])} tool calls; L2: {layer}")


if __name__ == "__main__":
    main()
