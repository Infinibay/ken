"""Public syntax-search lifecycle: compile, acquire revisions, explore, report."""

from __future__ import annotations

import time
from hashlib import sha256
from pathlib import Path

from ken._paths import resolve_project_path
from ken.gitignore_filter import iter_files
from ken.structural.frontend import LANGUAGES, parser_for
from ken.structural.service import _configuration, _parser_versions
from ken.structural_store.acquisition import AcquisitionLock

from ..catalog import with_packaged_libraries
from ..compiler import compile as compile_program
from ..execution_control import ExecutionBudget, ExecutionStopped
from ..syntax import parse
from .cache import SyntaxCache
from .compiler import compile_plan
from .execution import execute
from .storage_codec import flatten


def frontend_fingerprint():
    directory = Path(__file__).parent
    return sha256(
        b"syntax-exploration/1"
        + _parser_versions().encode()
        + (directory / "storage_codec.py").read_bytes()
        + (directory / "ast.fbs").read_bytes()
    ).hexdigest()


def search(
    root,
    source,
    *,
    query_name=None,
    path=".",
    cache_mb=None,
    timeout_ms=None,
    max_states=None,
    max_rows=None,
    max_file_bytes=2_000_000,
    reference=False,
    libraries=None,
    profile=False,
    cache_directory=None,
    cancelled=None,
):
    from .. import request

    request.phase("compile")
    started = time.monotonic()
    ExecutionBudget(timeout_ms, max_states, max_rows)
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    root = Path(root).resolve()
    libraries = with_packaged_libraries(source, libraries)
    program = compile_program(
        parse(source),
        query_name,
        libraries={name: parse(text, name) for name, text in libraries.items()},
    )
    plan = compile_plan(program)  # Unsupported capabilities fail before cache/file I/O.
    from ..diagnostics import diagnose

    diagnostics = diagnose(program)
    compile_ms = (time.monotonic() - started) * 1000
    target = resolve_project_path(root, path)
    if not target.exists():
        raise ValueError(f"path does not exist: {path}")
    directory = target.is_dir()
    scope_path = target.relative_to(root)
    retention_bytes = int(_configuration(root, cache_mb) * 1_000_000)
    enabled = retention_bytes >= 512_000
    database = (
        Path(cache_directory) if cache_directory else root / ".ken/structural/v2"
    ) / "syntax.sqlite"
    frontend = frontend_fingerprint()
    request.phase("acquisition", query=program.name, columns=[
        e.value or f"column_{i + 1}" for i, e in enumerate(program.projection)
    ], diagnostics=diagnostics)
    acquisition = AcquisitionLock(database, enabled=enabled)
    cache = None
    skipped, units, manifest = [], [], []
    parsed = reused = 0
    phases = {"read_ms": 0.0, "parse_ms": 0.0, "projection_ms": 0.0, "persist_ms": 0.0}

    def check():
        if cancelled and cancelled():
            raise ExecutionStopped("cancelled")

    try:
        cache = SyntaxCache(database if enabled else None, root)
        paths = sorted(iter_files(root, path=path)) if directory else [scope_path]
        for relative in paths:
            request.phase("source", current_path=relative.as_posix(), parsed_units=parsed, reused_units=reused)
            check()
            try:
                if directory and not relative.is_relative_to(scope_path):
                    continue
                language = LANGUAGES.get(relative.suffix.lower())
                if language is None:
                    if relative.suffix.lower() in {
                        ".c",
                        ".h",
                        ".kt",
                        ".swift",
                        ".scala",
                        ".dart",
                        ".php",
                    }:
                        skipped.append(
                            {
                                "path": relative.as_posix(),
                                "reason": "unsupported_frontend",
                            }
                        )
                    continue
                absolute = resolve_project_path(root, relative)
                if directory and not absolute.is_relative_to(target):
                    continue
                phase = time.monotonic()
                with absolute.open("rb") as stream:
                    content = stream.read(max_file_bytes + 1)
                phases["read_ms"] += (time.monotonic() - phase) * 1000
                if len(content) > max_file_bytes:
                    skipped.append(
                        {"path": relative.as_posix(), "reason": "max_file_bytes"}
                    )
                    continue
            except (OSError, ValueError) as exc:
                skipped.append({"path": relative.as_posix(), "reason": str(exc)})
                continue
            name = relative.as_posix()
            source_hash = sha256(content).hexdigest()
            manifest.append((name, source_hash))
            found = cache.find(name, source_hash, frontend)
            if found is not None:
                unit, errors = found
                reused += 1
            else:
                phase = time.monotonic()
                try:
                    request.phase("parse")
                    tree = parser_for(language, name).parse(content)
                except (ImportError, ValueError, RuntimeError) as exc:
                    skipped.append(
                        {
                            "path": name,
                            "reason": f"frontend_error: {type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                phases["parse_ms"] += (time.monotonic() - phase) * 1000
                phase = time.monotonic()
                request.phase("projection")
                columns = flatten(tree, cache.dictionary, check)
                phases["projection_ms"] += (time.monotonic() - phase) * 1000
                check()
                phase = time.monotonic()
                request.phase("persist")
                unit, errors = cache.put(
                    name, language, source_hash, frontend, content, columns
                )
                phases["persist_ms"] += (time.monotonic() - phase) * 1000
                parsed += 1
                del tree, columns
            if errors:
                skipped.append({"path": name, "reason": "parse_error"})
            units.append(unit)
        scope = scope_path.as_posix()
        cache.snapshot(units, scope="" if scope == "." else scope)
        acquisition.close()  # Read transaction now owns a consistent snapshot.
        build_ms = (time.monotonic() - started) * 1000 - compile_ms
        request.phase("query", parsed_units=parsed, reused_units=reused, execution_phase="query")
        outcome = execute(
            plan,
            cache,
            coverage=not skipped,
            timeout_ms=request.remaining(
                None if timeout_ms is None else max(0, timeout_ms - (time.monotonic() - started) * 1000)
            ),
            max_states=max_states,
            max_rows=max_rows,
            reference=reference,
            cancelled=cancelled,
            profile=profile,
        )
        metrics = outcome.pop("metrics")
        request.phase("report", result={
            "language": "kql/2", "query": program.name,
            "columns": [e.value or f"column_{i + 1}" for i, e in enumerate(program.projection)],
            "coverage_complete": not skipped, **outcome,
        })
        if enabled:
            cache.db.rollback()
            acquisition = AcquisitionLock(database, enabled=True)
            evicted = cache.trim(retention_bytes)
        else:
            evicted = 0
        return {
            "language": "kql/2",
            "capability": "syntax-exploration/1",
            "query": program.name,
            "columns": [
                e.value or f"column_{i + 1}" for i, e in enumerate(program.projection)
            ],
            "coverage_complete": not skipped,
            **outcome,
            **({"diagnostics": diagnostics} if diagnostics else {}),
            "analysis": {
                "backend": "flatbuffers_exploration",
                "semantic_resolution": "not_requested",
                "manifest": manifest,
                "skipped": skipped,
                "parsed_units": parsed,
                "reused_units": reused,
                "result_cache": "disabled",
                "ephemeral": not enabled,
                "retention_budget_bytes": retention_bytes,
                "evicted_units": evicted,
                "allocated_bytes": cache.allocated_bytes,
                "compile_ms": compile_ms,
                "build_ms": build_ms,
                "phase_ms": phases,
                **metrics,
                "total_ms": (time.monotonic() - started) * 1000,
            },
        }
    finally:
        if cache is not None:
            cache.close()
        acquisition.close()
