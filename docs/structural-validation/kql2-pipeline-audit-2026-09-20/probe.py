"""Read-only code/manifest probes; no changes to the production engine.

Run from the Ken checkout with PYTHONPATH=.:src, after the catalogue benchmark.
The scoped walker is a diagnostic prototype, not a replacement shipped to users.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
import tomllib
from pathlib import Path
from unittest.mock import patch

from ken.gitignore_filter import GitignoreMatcher, iter_files
from ken.kql2 import catalog
from ken.kql2.compilation import implementation_fingerprint
from ken.kql2.syntax import parse
from ken.structural import service
from ken.structural.rules import builtin_rules, query_registry


def scoped_files(root: Path, target: Path):
    """Walk only target, keeping repository-root ignore rules and path identities."""
    root, target = root.resolve(), target.resolve()
    matcher = GitignoreMatcher(root)
    relative = target.relative_to(root)
    ancestor = Path()
    for part in relative.parts:
        ancestor /= part
        if matcher.is_ignored(ancestor, is_dir=True):
            return
    stack = [target]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            relative = entry.relative_to(root)
            is_dir = entry.is_dir()
            if matcher.is_ignored(relative, is_dir=is_dir):
                continue
            if is_dir:
                stack.append(entry)
            elif entry.is_file():
                yield relative


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scope", default="sdk/typescript")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    root = args.root.resolve()
    target = (root / args.scope).resolve()
    snapshot = catalog.sources()
    queries = []
    for path, text in snapshot:
        rule = tomllib.loads(text)
        for entry in (rule, *rule.get("variants", []), *rule.get("operations", [])):
            source = entry.get("query", "")
            if source.lstrip().startswith('language "kql/2"'):
                queries.append((path, source))
    parse_times = []
    for _ in range(args.repeats):
        start = time.perf_counter()
        trees = [parse(source, path) for path, source in queries]
        parse_times.append(time.perf_counter() - start)
        assert len(trees) == len(queries)

    catalog._COMPILED.clear()
    catalog._libraries.cache_clear()
    catalog._snapshot_key.cache_clear()
    compilation = []
    for repeat in range(args.repeats):
        before = catalog._COMPILED.stats()
        start = time.perf_counter()
        registry = builtin_rules()
        plans = query_registry(registry)
        elapsed = time.perf_counter() - start
        after = catalog._COMPILED.stats()
        compilation.append({
            "repeat": repeat, "seconds": elapsed, "named_entries": len(plans),
            "cache_delta": {k: after[k] - before[k] for k in ("hits", "misses", "evictions")},
            "cache": after,
        })

    versions = service._parser_versions()
    manifests = []
    baseline = None
    for repeat in range(args.repeats):
        # Alternate order to reduce one-sided filesystem warming effects.
        names = ("current", "scoped") if repeat % 2 == 0 else ("scoped", "current")
        for name in names:
            yielded = 0

            def walker(project):
                nonlocal yielded
                source = iter_files(project) if name == "current" else scoped_files(project, target)
                for item in source:
                    yielded += 1
                    yield item

            start = time.perf_counter()
            with patch.object(service, "iter_files", walker):
                result = service.source_manifest(root, target, versions, None, 2_000_000)
            elapsed = time.perf_counter() - start
            if baseline is None:
                baseline = result
            assert result == baseline, "Scoped traversal changed manifest or skipped-file evidence"
            units, skipped = result
            manifests.append({
                "repeat": repeat, "variant": name, "seconds": elapsed,
                "files_yielded": yielded, "supported_files": len(units),
                "skipped": skipped,
            })
    assert baseline is not None
    report = {
        "python": platform.python_version(), "platform": platform.platform(),
        "ken_head": git(Path.cwd(), "rev-parse", "HEAD"),
        "source_head": git(root, "rev-parse", "HEAD"),
        "source_scope_status": git(root, "status", "--short", "--", args.scope),
        "root": str(root), "scope": args.scope,
        "implementation_fingerprint": implementation_fingerprint(),
        "catalogue_source_sha256": hashlib.sha256(repr(snapshot).encode()).hexdigest(),
        "manifest_sha256": hashlib.sha256(repr([(p, k) for p, k, _ in baseline[0]]).encode()).hexdigest(),
        "parse": {"queries": len(queries), "seconds": parse_times,
                  "median_seconds": statistics.median(parse_times)},
        "compilation": compilation,
        "manifest": manifests,
        "manifest_equal_including_content_and_skips": True,
        "limitations": [
            "Scoped traversal equivalence checked only on the recorded scope.",
            "No cold OS cache, no production changes, no universal speedup claim.",
            "Catalogue compilation is measured separately from query execution.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
