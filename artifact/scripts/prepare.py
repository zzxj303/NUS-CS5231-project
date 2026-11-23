"""Create a fresh run workspace without overwriting earlier runs."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("systematic-debugging", "test-driven-development", "verification-before-completion")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(workspace):
    result = {}
    for path in sorted(workspace.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = str(path.relative_to(workspace))
        if path.is_symlink():
            result[relative] = "SYMLINK:" + str(path.readlink())
        elif path.is_file():
            result[relative] = digest(path)
    return result


def prepare(scenario, destination):
    destination = Path(destination).resolve()
    spec = json.loads((ROOT / "scenarios" / f"{scenario}.json").read_text(encoding="utf-8"))
    if any(destination.is_relative_to(ROOT / name)
           for name in ("workload", "skills", "scripts", "scenarios", "tests")):
        raise ValueError("Place runs outside the artifact's source directories")
    destination.mkdir(parents=True, exist_ok=False)
    workspace = destination / "workspace"
    shutil.copytree(ROOT / "workload", workspace,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "._*", ".git"))
    for relative, content in spec["overrides"].items():
        target = workspace / relative
        if not target.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Scenario path escapes workspace")
        target.write_text(content, encoding="utf-8")
    for skill in SKILLS:
        shutil.copytree(ROOT / "skills" / skill, workspace / ".agents" / "skills" / skill)
    shutil.copy2(ROOT / "skills" / "LICENSE.superpowers", workspace / ".agents" / "skills" / "LICENSE.superpowers")
    (workspace / "outputs").mkdir()
    # This config constrains named agent tools; it is not an OS sandbox.
    (workspace / "opencode.json").write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "permission": {"external_directory": "deny", "webfetch": "deny",
                       "websearch": "deny", "question": "deny"}
    }, indent=2) + "\n", encoding="utf-8")
    prompt = (ROOT / "task.md").read_text(encoding="utf-8")
    prompt += ("\nThe skills are installed under .agents/skills/. Begin by reading "
               ".agents/skills/systematic-debugging/SKILL.md.\n")
    (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
    (destination / "baseline.json").write_text(json.dumps(snapshot(workspace), indent=2) + "\n", encoding="utf-8")
    (destination / "scenario.json").write_text(json.dumps({
        "scenario": scenario, **spec,
        "skill_revision": json.loads((ROOT / "skills" / "UPSTREAM.json").read_text(encoding="utf-8"))["revision"]
    }, indent=2) + "\n", encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=[p.stem for p in sorted((ROOT / "scenarios").glob("*.json"))])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = prepare(args.scenario, args.output)
    except FileExistsError:
        parser.exit(2, "Output directory already exists; choose a fresh run name.\n")
    print(f"Prepared {path}")
    print(f"Agent working directory: {path / 'workspace'}")


if __name__ == "__main__":
    main()

