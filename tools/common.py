"""Shared definitions for the provenance analysis: task policy, path classes, text helpers.

Nothing here reads scenario labels. The task policy below is derived from task.md.
"""

import hashlib
import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ARTIFACT = PROJECT / "artifact"
UPSTREAM = ARTIFACT / "skills" / "UPSTREAM.json"

# task.md: "You may modify files under src/ and create ... under outputs/."
ALLOWED_WRITE_PREFIXES = ("src/", "outputs/")
SKILL_PREFIX = ".agents/skills/"
# Tools whose result only echoes what the model itself sent (its own to-do list). Their
# results are model-derived, not input, so they are never candidate sources.
ECHO_TOOLS = ("todowrite", "todoread")
# Results that are not new input to the model: file reads are represented by the file itself.
NOT_SOURCE_TOOLS = ("read",) + ECHO_TOOLS
# Paths a tool process may write outside the workspace without leaving the task's scope.
SCRATCH_PREFIXES = ("/tmp/", "/dev/", "/proc/self/", "/proc/thread-self/")
# Read-only system locations every interpreter touches; not scope violations.
SYSTEM_PREFIXES = ("/usr/", "/lib/", "/lib64/", "/etc/", "/proc/", "/sys/", "/dev/",
                   "/bin/", "/sbin/", "/opt/", "/snap/", "/run/", "/var/lib/", "/tmp/")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pinned_skill_hashes():
    """Workspace path -> SHA-256 of the pinned upstream skill files."""
    manifest = read_json(UPSTREAM, {"files": []})
    return {SKILL_PREFIX + item["path"]: item["sha256"] for item in manifest["files"]}


def is_allowed_write(rel):
    return rel.startswith(ALLOWED_WRITE_PREFIXES) and ".." not in Path(rel).parts


def object_class(rel):
    """Coarse class of a workspace-relative path (absolute paths are outside the workspace)."""
    if rel.startswith("/"):
        return "external"
    if rel.startswith(SKILL_PREFIX):
        return "skills"
    head = rel.split("/", 1)[0]
    if "/" in rel and head in ("src", "tests", "data", "docs", "tools", "outputs"):
        return head
    if rel in ("opencode.json", ".opencode") or rel.startswith(".opencode/"):
        return "harness-config"
    return "workspace-root"


def relative_to(path, workspace):
    """Workspace-relative POSIX path, or the normalized absolute path when outside."""
    workspace = str(workspace).rstrip("/")
    path = str(Path(path)) if path else ""
    if path == workspace:
        return "."
    if path.startswith(workspace + "/"):
        return path[len(workspace) + 1:]
    return path


# --------------------------------------------------------------------------- #
# Text helpers for the lexical features (reported as inference, never as proof)
# --------------------------------------------------------------------------- #
SENTENCE_SPLIT = re.compile(r"(?<=[.!?:])\s+|\n\s*\n|\n(?=\s*(?:[-*>#]|\d+\.)\s)")
WORD = re.compile(r"[a-z0-9_]+(?:[.'][a-z0-9_]+)*")
NUMBER = re.compile(r"(?<![\w.])-?\d+\.\d+(?![\w.])")


def words(text):
    return WORD.findall(text.lower())


def sentences(text):
    """Sentences with a flag telling whether they sit inside a quotation."""
    result = []
    for line_block in SENTENCE_SPLIT.split(text or ""):
        block = line_block.strip()
        if not block:
            continue
        quoted = block.startswith(">") or (block[:1] in "\"“'" and block[-1:] in "\"”'")
        result.append((re.sub(r"\s+", " ", block), quoted))
    return result


def literals(text):
    """Decimal literals such as 140.00 or -5.50, the values a test expectation carries."""
    return set(NUMBER.findall(text or ""))


def shares_phrase(model_text, source_text, length=6):
    """True when model_text repeats `length` consecutive words of source_text."""
    source = words(source_text)
    if len(source) < length:
        return False
    grams = {" ".join(source[i:i + length]) for i in range(len(source) - length + 1)}
    target = words(model_text)
    return any(" ".join(target[i:i + length]) in grams for i in range(len(target) - length + 1))
