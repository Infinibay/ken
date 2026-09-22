"""Compare eager and focused inspection on isolated copies of this repository.

Both strategies get the same source, target, scope, depth and wall-clock budget.
Each starts with an independent empty index. A timeout is censored, not a timing
for a successful answer. Warm runs reuse only their own strategy's cache.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time

from ken.checks.snapshot import engine_version
from ken.inspection.graph import Program
from ken.inspection.impact import analyze
from ken.inspection.service import inspect


TARGETS = {
    "manifest": "src/ken/vectors.py::_atomic_write",
    "report": "src/ken/checks/report.py::query_view",
}


def measure(root: Path, target: str, strategy: str, timeout_ms: int) -> dict:
    started = time.monotonic()
    if strategy == "focused":
        result = inspect(root, target, path="src", timeout_ms=timeout_ms, full=True)
    else:
        program = Program.inspect(
            root,
            path="src",
            seeds=[target.partition("::")[0]],
            incoming=True,
            timeout_ms=timeout_ms,
        )
        seeds = program.select(target)
        result = analyze(program, seeds, depth=2, limit=10)
        result.update(
            status="observed" if seeds else "unknown",
            acquisition=program.selection,
            observations=program.observations,
            snapshot=program.snapshot,
        )
    return {"elapsed_seconds": round(time.monotonic() - started, 3), "result": result}


def evaluate(
    repository: Path, output: Path, *, baseline: bool, timeout_ms: int
) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be empty; preserve previous measurements")
    output.mkdir(parents=True, exist_ok=True)
    files = sorted((repository / "src").rglob("*.py"))
    sources = {p.relative_to(repository): p.read_bytes() for p in files}
    manifest = {p.as_posix(): sha256(data).hexdigest() for p, data in sources.items()}
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2))
    report = {
        "engine": engine_version(),
        "source_files": len(sources),
        "scope": "src",
        "depth": 2,
        "timeout_ms": timeout_ms,
        "runs": [],
    }
    for case, target in TARGETS.items():
        for strategy in ["eager", "focused"] if baseline else ["focused"]:
            with tempfile.TemporaryDirectory(
                prefix="ken-inspection-eval-"
            ) as temporary:
                root = Path(temporary)
                for relative, data in sources.items():
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                for cache in ("cold", "warm"):
                    run = measure(root, target, strategy, timeout_ms)
                    result = run.pop("result")
                    artifact = f"{case}-{strategy}-{cache}.json"
                    (output / artifact).write_text(json.dumps(result, indent=2))
                    acquisition = result.get("acquisition") or {}
                    run.update(
                        case=case,
                        target=target,
                        strategy=strategy,
                        cache=cache,
                        status=result.get("status"),
                        consumers=len(result.get("consumers", [])),
                        behavior_files=len(acquisition.get("paths", [])),
                        import_files_read=acquisition.get("import_files_read"),
                        coverage=result.get("coverage"),
                        artifact=artifact,
                    )
                    report["runs"].append(run)
                    (output / "result.json").write_text(json.dumps(report, indent=2))
                    print(json.dumps(run), flush=True)
                    if run["status"] == "unknown":
                        # A killed publisher may retain a lease. A second attempt
                        # would measure lease contention rather than warm queries.
                        break
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()
    evaluate(
        args.root.resolve(),
        args.output.resolve(),
        baseline=args.baseline,
        timeout_ms=args.timeout_ms,
    )
