"""Live-worktree analysis, content invalidation, and directory composition."""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ken._paths import resolve_project_path
from ken.gitignore_filter import iter_files

from .cache import DEFAULT_CACHE_MB, IRCache
from .catalog import detect_patterns
from .effects import evaluate_bugs
from .frontend import LANGUAGES, lower_source
from .model import IR, IR_VERSION, FactIndex
from .query import QueryBudget, evaluate_pattern
from .semantic import link_project


def _configuration(root: Path, override: float | None) -> float:
    config_path = root / ".ken" / "structural.json"
    value: Any = DEFAULT_CACHE_MB
    if config_path.exists():
        config = json.loads(config_path.read_text())
        value = config.get("cache", {}).get("max_mb", value)
        if not config.get("cache", {}).get("enabled", True):
            value = 0
    if "KEN_STRUCTURAL_CACHE_MB" in os.environ:
        value = os.environ["KEN_STRUCTURAL_CACHE_MB"]
    if override is not None:
        value = override
    result = float(value)
    if result < 0 or not __import__("math").isfinite(result):
        raise ValueError("cache max_mb must be finite and nonnegative")
    return result


def _parser_versions() -> str:
    packages = ["tree-sitter", "tree-sitter-language-pack", "tree-sitter-python", "tree-sitter-javascript",
                "tree-sitter-typescript", "tree-sitter-java", "tree-sitter-go", "tree-sitter-rust"]
    result = []
    for package in packages:
        try:
            result.append(package + "=" + version(package))
        except PackageNotFoundError:
            result.append(package + "=unavailable")
    return ";".join(result)


def _cached_ir(cache: IRCache, key: str) -> IR | None:
    cached = cache.get(key)
    if cached is None:
        return None
    try:
        return IR.from_dict(cached)
    except (KeyError, ValueError, TypeError):
        cache.hits -= 1
        cache.misses += 1
        cache.error = "invalid cached IR; rebuilding"
        return None


def build_project(root: Path, *, path: str = ".", cache_mb: float | None = None,
                  max_files: int = 2000, max_file_bytes: int = 2_000_000) -> tuple[IR, dict[str, Any]]:
    root = root.resolve()
    target = resolve_project_path(root, path)
    if not target.exists():
        raise ValueError(f"path does not exist: {path}")
    if max_files <= 0 or max_file_bytes <= 0:
        raise ValueError("scan limits must be positive")
    started = time.monotonic()
    cache = IRCache(root / ".ken" / "structural-cache.sqlite", _configuration(root, cache_mb))
    versions = _parser_versions()
    manifest: list[tuple[str, str, bytes]] = []
    skipped: list[dict[str, str]] = []
    considered = sorted(iter_files(root)) if target.is_dir() else [target.relative_to(root)]
    try:
        for relative in considered:
            try:
                absolute = resolve_project_path(root, relative)
            except ValueError:
                skipped.append({"path": relative.as_posix(), "reason": "symlink escapes project"})
                continue
            if target.is_dir() and not absolute.is_relative_to(target):
                continue
            language = LANGUAGES.get(relative.suffix.lower())
            if language is None:
                if relative.suffix.lower() in {".c", ".h", ".rb", ".kt", ".dart", ".php", ".swift", ".scala"}:
                    skipped.append({"path": relative.as_posix(), "reason": "no structural frontend"})
                continue
            if len(manifest) >= max_files:
                skipped.append({"path": relative.as_posix(), "reason": "max_files"})
                continue
            if absolute.stat().st_size > max_file_bytes:
                skipped.append({"path": relative.as_posix(), "reason": "max_file_bytes"})
                continue
            try:
                content = absolute.read_bytes()
            except OSError as exc:
                skipped.append({"path": relative.as_posix(), "reason": str(exc)})
                continue
            key = cache.key("unit", IR_VERSION, versions, relative.as_posix(), language, content)
            manifest.append((relative.as_posix(), key, content))
        graph_key = cache.key("project", IR_VERSION, versions, *(key for _, key, _ in manifest))
        graph = _cached_ir(cache, graph_key)
        failed: set[str] = set()
        if graph is None:
            units = []
            for relative_name, key, content in manifest:
                unit = _cached_ir(cache, key)
                if unit is None:
                    try:
                        unit = lower_source(content, LANGUAGES[Path(relative_name).suffix.lower()], relative_name)
                    except Exception as exc:
                        # One file the frontend cannot lower (an unloadable grammar,
                        # a construct that trips the lowerer) must not abort the
                        # scan of every other file: it is reported as skipped, the
                        # coverage flag goes false, and the caller decides.
                        failed.add(relative_name)
                        skipped.append({"path": relative_name,
                                        "reason": f"frontend error: {type(exc).__name__}: {exc}"})
                        continue
                    cache.put(key, unit.to_dict())
                units.append(unit)
            graph = link_project(units)
            if not failed:
                # A graph built without some of its files must not be cached under
                # the key of the complete manifest, or the next run would read a
                # partial result and report it as whole.
                cache.put(graph_key, graph.to_dict())
        resolved = {f.subject for f in graph.facts if f.relation in {"TARGET", "ALLOCATES_TYPE"}}
        unresolved = {f.object for f in graph.facts if f.relation == "HAS_CALL"} - resolved
        return graph, {"resolution": {"resolved_calls": len(resolved), "unresolved_calls": len(unresolved)},
                       "files": [path for path, _, _ in manifest if path not in failed], "skipped": skipped,
                       "coverage_complete": not skipped and not graph.diagnostics,
                       "diagnostics": graph.diagnostics, "cache": cache.stats(),
                       "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}
    finally:
        cache.close()


def directory_summary(findings: list[dict[str, Any]], files: list[str]) -> list[dict[str, Any]]:
    """Count distinct matching files; multiple roles/variants never inflate density."""
    directories: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for file in files:
        directories[str(Path(file).parent)].add(file)
    for match in findings:
        file = match["path"]
        counts[str(Path(file).parent)][match["id"]].add(file)
    return [{"directory": directory, "analyzed_files": len(paths),
             "patterns": [{"id": pattern, "matching_files": len(matches),
                           "share": round(len(matches) / len(paths), 3), "files": sorted(matches)}
                          for pattern, matches in sorted(counts[directory].items(), key=lambda x: (-len(x[1]), x[0]))]}
            for directory, paths in sorted(directories.items())]


def search(root: Path, query: str = "", *, path: str = ".", cache_mb: float | None = None,
           budget: QueryBudget | None = None, rule_ids: list[str] | None = None,
           collections: list[str] | None = None, tags: list[str] | None = None,
           rule_files: list[str] | None = None, evidence_mode: str = "strict") -> dict[str, Any]:
    from .rules import SavedRule, execute_rules, load_rules, select_rules
    if evidence_mode not in {"strict", "possible"}:
        raise ValueError("evidence_mode must be strict or possible")
    selecting = bool(rule_ids or collections or tags)
    if query and selecting:
        raise ValueError("choose an inline query or saved rule selectors, not both")
    if not query and not selecting:
        raise ValueError("provide a query, rule, collection, tag, or rule file")
    registry = load_rules(root, rule_files)
    ordinary_ids = {r.id for r in registry}
    named_ids = [name for name in rule_ids or [] if name not in ordinary_ids]
    if named_ids and (collections or tags):
        raise ValueError("named variant selection cannot be combined with collection/tag filters")
    if named_ids:
        from .rules import named_rule
        selected = [named_rule(name, registry) if name in named_ids else next(r for r in registry if r.id == name) for name in rule_ids or []]
    else:
        selected = (select_rules(registry, rule_ids, collections, tags) if selecting else [SavedRule("query", query)])
    # Fail before scanning or creating cache files.
    compiled: dict[str, Any] = {}
    for rule in selected:
        rule._validate(compiled)
    if any(rule.query.lstrip().startswith("query ") for rule in selected):
        from .kenql import Engine
        from .rules import query_registry, _parsed_query
        queries = query_registry(registry, _parsed=compiled)
        validator = Engine(FactIndex(IR("", "")), queries, budget)
        for rule in selected:
            if rule.query.lstrip().startswith("query "):
                validator.validate(_parsed_query(rule.query, compiled))
    graph, analysis = build_project(root, path=path, cache_mb=cache_mb)
    result = execute_rules(graph, selected, budget, registry=registry, evidence_mode=evidence_mode, _parsed=compiled)
    summaries = directory_summary(result["matches"], analysis["files"])
    for summary in summaries:
        summary["rules"] = summary.pop("patterns")
    response = {"ok": True, **result, "analysis": analysis, "directories": summaries,
                "rules": [r.to_dict() for r in selected]}
    if query:
        # Keep the existing single-query response's statistics and uncertainty.
        response.update(result["outcomes"]["query"])
    return response


def patterns(root: Path, names: list[str] | None = None, *, path: str = ".",
             cache_mb: float | None = None, budget: QueryBudget | None = None) -> dict[str, Any]:
    graph, analysis = build_project(root, path=path, cache_mb=cache_mb)
    result = detect_patterns(FactIndex(graph), names, budget)
    return {"ok": True, **result, "directories": directory_summary(result["findings"], analysis["files"]),
            "analysis": analysis}


def bugs(root: Path, *, path: str = ".", cache_mb: float | None = None,
         budget: QueryBudget | None = None) -> dict[str, Any]:
    graph, analysis = build_project(root, path=path, cache_mb=cache_mb)
    return {"ok": True, **evaluate_bugs(graph, budget), "analysis": analysis}
