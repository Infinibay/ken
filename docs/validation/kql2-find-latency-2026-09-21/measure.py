"""Measure the public CLI on fixed copies of Ken source and independent caches."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def query(body: str) -> str:
    return 'language "kql/2"; module measurement; query q { ' + body + " }"


QUERIES = {
    "definition": query('callable $f { name:"_atomic_write"; } select $f;'),
    "chmod": query('callable $f { call $c { name:"chmod"; } } select $f,$c;'),
    "callers": query(
        'callable $target { name:"_atomic_write"; } edge TARGET($site,$target); edge HAS_CALL($owner,$site); select $owner,$site;'
    ),
    "mutable-default": query(
        'edge HAS_HAZARD($site,"mutable-default-argument"); select $site;'
    ),
    "result-usages": query(
        "callable $target {} callable $owner { body { let $value=call $target {} as $site; } } usages of $value as $use {} select $owner,$target,$site,$use;"
    ),
}


def run(
    root: Path,
    output: Path,
    scope: str,
    name: str,
    number: int,
    source: str,
    cache_mb: int | None,
) -> dict:
    command = [
        sys.executable,
        "-m",
        "ken",
        "tools",
        "--path",
        str(root),
        "find",
        source,
        "--scope",
        "structure",
        "--query-language",
        "kql/2",
        "--path",
        scope,
        "--limit",
        "100",
        "--timeout-ms",
        "10000",
        "--full",
    ]
    if cache_mb is not None:
        command.extend(["--cache-mb", str(cache_mb)])
    artifact = f"{scope.replace('/', '_')}-{name}-{number}"
    start = time.monotonic()
    with (
        (output / f"{artifact}.json").open("w") as stdout,
        (output / f"{artifact}.stderr").open("w") as stderr,
    ):
        try:
            process = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=90)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    elapsed = time.monotonic() - start
    try:
        result = json.loads((output / f"{artifact}.json").read_text())
    except ValueError:
        result = {}
    analysis = result.get("analysis", {})
    record = {
        "scope": scope,
        "case": name,
        "repetition": number,
        "seconds": round(elapsed, 4),
        "exit_code": exit_code,
        "rows": len(result.get("rows", [])),
        "result": {
            k: result[k]
            for k in (
                "complete",
                "coverage_complete",
                "unknown_candidates",
                "results_truncated",
                "reason",
            )
            if k in result
        },
        "analysis": {
            k: analysis[k]
            for k in (
                "parsed_units",
                "reused_units",
                "build_ms",
                "query_ms",
                "compile_ms",
                "total_ms",
                "result_cache",
                "ephemeral",
                "states",
                "scanned_nodes",
                "allocated_bytes",
                "cache_mb",
            )
            if k in analysis
        },
        "artifact": f"{artifact}.json",
        "query": source,
    }
    print(json.dumps(record), flush=True)
    return record


def main(
    repository: Path, output: Path, scopes: list[str], cache_mb: int | None
) -> None:
    from ken.checks.snapshot import engine_version

    sources = {
        p.relative_to(repository): p.read_bytes()
        for p in sorted((repository / "src").rglob("*.py"))
    }
    manifest = {
        p.as_posix(): hashlib.sha256(data).hexdigest() for p, data in sources.items()
    }
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2))
    report = {
        "engine": engine_version(),
        "source_files": len(sources),
        "query_timeout_ms": 10000,
        "wall_timeout_seconds": 90,
        "limit": 100,
        "cache_mb": cache_mb or "default",
        "runs": [],
    }
    for scope in scopes:
        with tempfile.TemporaryDirectory(prefix="ken-find-benchmark-") as temporary:
            root = Path(temporary)
            for relative, data in sources.items():
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
            (root / ".ken").mkdir()
            (root / ".ken/meta.json").write_text("{}")
            cases = (
                dict(QUERIES)
                if scope == "src"
                else {"definition": QUERIES["definition"]}
            )
            if scope == "src/ken/checks":
                cases["definition"] = query(
                    'callable $f { name:"query_view"; } select $f;'
                )
            for name, source in cases.items():
                for number in range(3):
                    record = run(root, output, scope, name, number, source, cache_mb)
                    report["runs"].append(record)
                    (output / "result.json").write_text(json.dumps(report, indent=2))
                    if record["exit_code"] or (
                        number >= 1 and record["analysis"].get("ephemeral")
                    ):
                        break
                if record["exit_code"] or record["analysis"].get("ephemeral"):
                    break
    report["engine_unchanged"] = report["engine"] == engine_version()
    report["sources_unchanged"] = all(
        hashlib.sha256((repository / p).read_bytes()).hexdigest() == h
        for p, h in manifest.items()
    )
    (output / "result.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scope",
        action="append",
        choices=["src/ken/vectors.py", "src/ken/checks", "src"],
    )
    parser.add_argument("--cache-mb", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "result.json").exists():
        parser.error("output already contains measurements")
    main(
        args.root.resolve(),
        args.output.resolve(),
        args.scope or ["src/ken/vectors.py", "src/ken/checks", "src"],
        args.cache_mb,
    )
