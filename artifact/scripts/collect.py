"""Run an installed agent and save its real event stream; no prerecorded trajectories."""

import argparse
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def build_command(agent, model, run):
    prompt = (run / "prompt.txt").read_text(encoding="utf-8")
    if agent == "opencode":
        return [agent, "run", "--dir", str(run / "workspace"),
                "--format", "json", "--model", model,
                "--title", "Expense summarizer", prompt]
    command = [agent, "--mode", "json", "--model", model,
               "--session-dir", str(run / "native-sessions"),
               "--no-extensions", "--no-mcp", "--no-context-files",
               "--no-prompt-templates", "--no-themes",
               "--tools", "read,bash,edit,write"]
    for name in ("systematic-debugging", "test-driven-development", "verification-before-completion"):
        command.extend(["--skill", str(run / "workspace" / ".agents" / "skills" / name)])
    return command + ["--", prompt]


def event_summary(path):
    valid = malformed = 0
    session_ids = []
    errors = []
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                malformed += 1
                continue
            valid += 1
            if not isinstance(event, dict):
                continue
            if event.get("type") == "error":
                errors.append(event)
            session = event.get("sessionID")
            if not session and isinstance(event.get("part"), dict):
                session = event["part"].get("sessionID")
            if session and session not in session_ids:
                session_ids.append(session)
    return {"json_records": valid, "non_json_lines": malformed,
            "session_ids": session_ids, "error_events": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", choices=("opencode", "pi"))
    parser.add_argument("run", type=Path)
    parser.add_argument("--model", required=True, help="Explicit provider/model supported by the chosen agent")
    parser.add_argument("--timeout", type=int, default=600, help="Maximum elapsed seconds")
    args = parser.parse_args()
    args.model = args.model.strip()
    if not args.model:
        parser.error("--model must not be empty; set DEMO_MODEL to your chosen provider/model ID")
    run = args.run.resolve()
    if not (run / "baseline.json").is_file() or not (run / "workspace").is_dir():
        parser.error("Run prepare.py first")
    if (run / "execution.json").exists() or (run / "events.jsonl").exists():
        parser.error("This run already has collection records; prepare a fresh run")
    if args.timeout <= 0:
        parser.error("Timeout must be positive")
    if not shutil.which(args.agent):
        parser.error(f"{args.agent} is not installed or is not on PATH")
    command = build_command(args.agent, args.model, run)
    env = os.environ.copy()
    env["PWD"] = str(run / "workspace")
    env["INIT_CWD"] = str(run / "workspace")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.agent == "pi":
        config = run / "runtime" / "pi"
        config.mkdir(parents=True)
        env["PI_CODING_AGENT_DIR"] = str(config)
        env["PI_TELEMETRY"] = "0"
    version = subprocess.run([args.agent, "--version"], capture_output=True,
                             text=True, timeout=20, env=env, cwd=run / "workspace")
    metadata = {"agent": args.agent, "model": args.model,
                "agent_version": version.stdout.strip(),
                "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "timeout_seconds": args.timeout, "status": "running",
                "cwd": str(run / "workspace"), "command": command,
                "configuration_note": "Pi uses a fresh config and environment credentials; OpenCode uses its existing user configuration."}
    record = run / "execution.json"
    record.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Collecting {args.agent} events in {run}; timeout {args.timeout}s", flush=True)
    with (run / "events.jsonl").open("w", encoding="utf-8") as stdout, \
            (run / "stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=run / "workspace", stdout=stdout,
                                   stderr=stderr, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
            metadata["status"] = "exited"
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = 124 if isinstance(error, subprocess.TimeoutExpired) else 130
            metadata["status"] = "timed_out" if code == 124 else "interrupted"
    metadata["exit_code"] = code
    metadata["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata["event_summary"] = event_summary(run / "events.jsonl")
    if args.agent == "opencode":
        sessions = metadata["event_summary"]["session_ids"]
        if len(sessions) == 1:
            try:
                with (run / "session.json").open("w", encoding="utf-8") as output, \
                        (run / "export.stderr.log").open("w", encoding="utf-8") as errors:
                    export = subprocess.run([args.agent, "export", sessions[0]],
                                            cwd=run / "workspace", stdout=output,
                                            stderr=errors, env=env, timeout=30)
                metadata["native_export_exit_code"] = export.returncode
                if export.returncode == 0:
                    try:
                        json.loads((run / "session.json").read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        metadata["native_export_error"] = "Export did not contain valid JSON; raw output retained"
            except subprocess.TimeoutExpired:
                metadata["native_export_error"] = "Export timed out; event stream is retained"
        else:
            metadata["native_export_note"] = "No unique session ID; inspect events and export the intended session manually"
    if metadata["event_summary"]["error_events"] and code == 0:
        metadata["status"] = "error_events_recorded"
        code = 1
    if metadata["event_summary"]["json_records"] == 0 and code == 0:
        metadata["status"] = "no_json_events_recorded"
        code = 1
    metadata["collector_exit_code"] = code
    record.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Collection status: {metadata['status']}; {metadata['event_summary']['json_records']} JSON records")
    print("Run check.py next. Agent exit status does not establish task success.")
    sys.exit(code)


if __name__ == "__main__":
    main()

