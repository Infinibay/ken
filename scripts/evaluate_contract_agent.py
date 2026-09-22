"""Compare source inspection and staged recall on isolated copies of Ken source.

One reads source directly; the other starts with a justified memory and Ken's
inspection tools. This is a paired observation, not a statistical benchmark.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from ken.checks.rules import manage
from ken.checks.service import check
from ken.db import connect, init_schema
from ken.embedder import get_embedder
from ken.indexer import index_files
from ken.mcp import server


QUESTION = (
    "Where does this project write vector manifests and how does the source handle their permissions? "
    "Identify the writer and at least one caller, cite file and symbol, distinguish observed code from runtime guarantees. "
    "Do not modify source or run production operations. Answer briefly in Spanish."
)

QUESTIONS = {
    "manifest": ("vector-manifest-permissions", QUESTION),
    "root": (
        "project-root-discovery",
        "How does find_project_root choose the project directory? If KEN_PROJECT_ROOT points to a directory "
        "without the metadata file, does it fall back to parent discovery? Cite file and symbol. "
        "Do not modify source or run production operations. Answer briefly in Spanish.",
    ),
}


def prepare(repository: Path, output: Path) -> Path:
    root = output / "project"
    root.mkdir(parents=True, exist_ok=True)
    paths = [
        Path("src/ken/vectors.py"),
        Path("src/ken/_paths.py"),
        Path("tests/test_vectors.py"),
    ]
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / relative, target)
    (root / ".ken").mkdir(exist_ok=True)
    (root / ".ken/meta.json").write_text("{}")
    with connect(root / ".ken/ken.db") as conn:
        init_schema(conn)
        index_files(conn, root, paths, embedder=get_embedder())
    definition = {
        "id": "vectors.manifest-chmod",
        "description": "Manifest writer contains an explicit chmod call",
        "path": "src/ken/vectors.py",
        "expectation": "some_match",
        "query": 'language "kql/2"; module demo; query q { callable $f { name:"_atomic_write"; call $c { name:"chmod"; } } select $f,$c; }',
        "examples": [
            {
                "name": "permission step",
                "files": {
                    "src/ken/vectors.py": "def _atomic_write():\n os.chmod(path, mode)\n"
                },
                "expect": "pass",
            },
            {
                "name": "missing step",
                "files": {
                    "src/ken/vectors.py": "def _atomic_write():\n os.replace(tmp, path)\n"
                },
                "expect": "fail",
            },
        ],
    }
    manage(root, "create", definition=definition)
    assert manage(root, "validate", rule_id=definition["id"])["validation"]["passed"]
    manage(root, "enable", rule_id=definition["id"])
    receipt = check(root, full=True, timeout_ms=30000)
    assert receipt["status"] == "pass", receipt
    server._PROJECT_ROOT = root
    server.ken_remember(
        "vector-manifest-permissions",
        "Source review: vectors_dir returns project_root/.ken/vectors through _paths.ken_dir (KEN_DIR_NAME='.ken'), "
        "and VectorStore.manifest_path adds <space>.json. "
        "_atomic_write creates a temporary file, writes/flushes/fsyncs, attempts chmod(tmp, 0o666 & ~_process_umask()), "
        "then os.replace. _process_umask temporarily sets 022 and restores the previous value. chmod OSError is ignored, "
        "so the requested permissions are not guaranteed at runtime. The method VectorStore._load_or_create and the module-level "
        "function compact call the writer; compact first writes a staging manifest. Existing manifests are read without permission repair. "
        "These details come from source inspection; the attached KQL check only guards omission of the chmod call.",
        anchor_file="src/ken/vectors.py",
        check_run=receipt["run_id"],
        justification={
            "kind": "observation",
            "rationale": "Reviewed the current writer, path helpers and callers; source observation and KQL guard have distinct claims.",
            "evidence": [
                {
                    "path": "src/ken/vectors.py",
                    "note": "Writer, callers, permission expression and exception handling.",
                },
                {"path": "src/ken/_paths.py", "note": "Path resolution helper."},
            ],
            "recheck": "Inspect these symbols and rerun vectors.manifest-chmod if their recorded inputs change.",
        },
    )
    server.ken_remember(
        "project-root-discovery",
        "Source review of src/ken/_paths.py::find_project_root: a nonempty KEN_PROJECT_ROOT overrides discovery. "
        "Its value is expanded with expanduser and resolved, then accepted only if meta_path(p).is_file(). "
        "An invalid override returns None immediately, without searching parents. Without the override, discovery "
        "resolves start (or Path.cwd()) and examines it followed by its parents, returning the nearest directory "
        "containing a .ken/meta.json file, or None. The returned directory is the project root, not .ken. "
        "meta_path and ken_dir construct that path using KEN_DIR_NAME='.ken' and META_FILENAME='meta.json'; "
        "this checks file existence, not valid JSON or an initialized database.",
        anchor_file="src/ken/_paths.py",
        justification={
            "kind": "observation",
            "rationale": "Reviewed find_project_root and the path helpers in the captured source.",
            "evidence": [
                {
                    "path": "src/ken/_paths.py",
                    "note": "find_project_root, meta_path, ken_dir and module constants.",
                }
            ],
            "recheck": "Inspect those symbols if _paths.py changes.",
        },
    )
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
    (output / "source-manifest.json").write_text(
        json.dumps(
            {p.as_posix(): sha256((root / p).read_bytes()).hexdigest() for p in paths},
            indent=2,
        )
    )
    return root


def run_agent(root: Path, output: Path, mode: str, *, case: str = "manifest") -> dict:
    topic, question = QUESTIONS[case]
    prefix = (
        "Use shell source inspection; do not call Ken MCP tools in this baseline. "
        "Restrict file discovery and reads to src/ and tests/. "
        if mode == "source"
        else f"Start by calling ken_recall(topic='{topic}', detail='answer'). "
        "If the recorded inputs are unchanged and its conclusion and assumptions cover the question, reuse it with source attribution. "
        "If evidence is missing or inputs changed, expand the relevant memory or read that source symbol. "
        "Do not treat unchanged inputs as an independent proof of the conclusion. "
    )
    prefix += "Stay inside this project; the fixture intentionally contains only the relevant source files. "
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(root),
        "-c",
        "mcp_servers.ken.command=" + json.dumps(sys.executable),
        "-c",
        "mcp_servers.ken.args=" + json.dumps(["-m", "ken", "mcp", str(root)]),
        "--output-last-message",
        str(output / f"{mode}-answer.txt"),
        prefix + question,
    ]
    started = time.monotonic()
    with (
        (output / f"{mode}.jsonl").open("w") as stdout,
        (output / f"{mode}.stderr").open("w") as stderr,
    ):
        try:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=300)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    events = []
    for line in (output / f"{mode}.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    usage = [e for e in events if e.get("type") == "turn.completed"]
    tool_items = [
        e["item"]
        for e in events
        if e.get("type") == "item.completed"
        and e.get("item", {}).get("type") in {"command_execution", "mcp_tool_call"}
    ]
    return {
        "mode": mode,
        "case": case,
        "exit_code": exit_code,
        "usage": usage,
        "tool_calls": len(tool_items),
        "tool_names": [i.get("tool", i.get("command", "")) for i in tool_items],
        "recorded_tool_event_characters": sum(len(json.dumps(i)) for i in tool_items),
        "tool_result_characters": sum(
            len(i.get("aggregated_output", ""))
            if i["type"] == "command_execution"
            else len(json.dumps(i.get("result", {})))
            for i in tool_items
        ),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-agents", action="store_true")
    parser.add_argument("--mode", choices=["source", "memory", "both"], default="both")
    parser.add_argument("--case", choices=[*QUESTIONS, "both"], default="manifest")
    parser.add_argument("--repetitions", type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("output must be empty; preserve previous experiment traces")
    output.mkdir(parents=True, exist_ok=True)
    root = prepare(args.root.resolve(), output)
    report = {
        "project": str(root),
        "policy": "staged recall; source and memory order alternates",
        "questions": dict(QUESTIONS),
        "runs": [],
    }
    if args.run_agents:
        for repetition in range(args.repetitions):
            for index, case in enumerate(
                QUESTIONS if args.case == "both" else [args.case]
            ):
                destination = output / f"{case}-{repetition + 1}"
                destination.mkdir()
                modes = (
                    ("source", "memory")
                    if (repetition + index) % 2 == 0
                    else ("memory", "source")
                )
                for mode in modes if args.mode == "both" else (args.mode,):
                    run = run_agent(root, destination, mode, case=case) | {
                        "repetition": repetition + 1
                    }
                    report["runs"].append(run)
                    (output / "result.json").write_text(json.dumps(report, indent=2))
                    print(
                        f"Completed {case} {repetition + 1} {mode}: exit {run['exit_code']}, {run['tool_calls']} tools",
                        file=sys.stderr,
                        flush=True,
                    )
    (output / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
