"""Explicit KQL2 entry point, isolated from the existing KQL1 catalogue."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ken._paths import resolve_project_path
from ken.gitignore_filter import iter_files
from ken.structural.frontend import LANGUAGES, lower_source
from ken.structural.model import IR_VERSION
from ken.structural.service import _configuration, _parser_versions
from ken.structural_store import Store
from ken.structural_store.acquisition import AcquisitionLock
from ken.structural_store.artifacts import read as read_artifact
from ken.structural_store.artifacts import touch_many
from ken.structural_store.artifacts import write as write_artifact
from ken.structural_store.leases import collect
from ken.structural_store.store import MIN_PERSISTENT_MB, fingerprint

from .codec import CODEC, encode
from .compilation import artifact_key, compile_query, implementation_fingerprint
from .execution import execute


def frontend_fingerprint() -> str:
    # Include implementation bytes, not just a manually incremented IR version.
    directory = Path(__file__).resolve().parents[1] / "structural"
    digest = sha256()
    for file in sorted(
        [*directory.glob("*.py"), *(directory.parent / "common_ast").glob("*.py")]
    ):
        digest.update(file.name.encode())
        digest.update(sha256(file.read_bytes()).digest())
    return fingerprint(
        "kql2-source-adapter/2", IR_VERSION, _parser_versions(), digest.hexdigest()
    )


def search(
    root: Path,
    source: str,
    *,
    query_name: str | None = None,
    path: str = ".",
    cache_mb: float | None = None,
    timeout_ms: float | None = None,
    max_states: int | None = None,
    max_rows: int | None = None,
    max_file_bytes: int = 2_000_000,
    reference: bool = False,
    libraries: Mapping[str, str] | None = None,
    profile: bool = False,
    backend: str = "indexed",
    cache_directory: Path | None = None,
    source_paths: list[str] | None = None,
    include_entities: bool = False,
) -> dict[str, Any]:
    from . import request

    if timeout_ms is not None and (not math.isfinite(timeout_ms) or timeout_ms < 0):
        raise ValueError("invalid execution budget")
    if timeout_ms is not None and not request.active():
        return request.bounded_search(root, source, dict(
            query_name=query_name, path=path, cache_mb=cache_mb,
            timeout_ms=timeout_ms, max_states=max_states, max_rows=max_rows,
            max_file_bytes=max_file_bytes, reference=reference,
            libraries=libraries, profile=profile, backend=backend,
            cache_directory=cache_directory, source_paths=source_paths,
            include_entities=include_entities,
        ))
    request.phase("compile")
    if backend == "exploration":
        if source_paths is not None or include_entities:
            raise ValueError("explicit source inventory requires the indexed backend")
        from .exploration.service import search as explore

        return explore(
            root,
            source,
            query_name=query_name,
            path=path,
            cache_mb=cache_mb,
            timeout_ms=timeout_ms,
            max_states=max_states,
            max_rows=max_rows,
            max_file_bytes=max_file_bytes,
            reference=reference,
            libraries=libraries,
            profile=profile,
            cache_directory=cache_directory,
        )
    if backend != "indexed" or cache_directory is not None:
        raise ValueError(
            "invalid backend or cache directory (custom directory requires exploration)"
        )
    start = time.monotonic()
    if (
        timeout_ms is not None
        and (not math.isfinite(timeout_ms) or timeout_ms < 0)
        or max_states is not None
        and max_states < 1
        or max_rows is not None
        and max_rows < 1
    ):
        raise ValueError("invalid execution budget")
    root = root.resolve()
    from .catalog import with_packaged_libraries

    libraries = with_packaged_libraries(source, libraries)
    budget = _configuration(root, cache_mb)
    prepared, compile_state, compilation_cache = compile_query(
        root,
        source,
        query_name,
        budget_bytes=int(budget * 1_000_000),
        reference=reference,
        libraries=libraries,
    )
    program = prepared.program
    from .diagnostics import diagnose
    from . import local_hazards

    diagnostics = diagnose(program)
    hazard_only = local_hazards.supports(program) and not reference
    request.phase("acquisition", query=program.name, columns=[
        expr.value or f"column_{i + 1}" for i, expr in enumerate(program.projection)
    ], diagnostics=diagnostics)
    compile_ms = (time.monotonic() - start) * 1000
    target = resolve_project_path(root, path)
    if not target.exists():
        raise ValueError(f"path does not exist: {path}")
    if source_paths is not None:
        if len(source_paths) > 4000:
            raise ValueError("explicit source inventory exceeds 4000 files")
        for item in source_paths:
            selected = resolve_project_path(root, item)
            if not selected.is_file() or (target.is_dir() and not selected.is_relative_to(target)) or (target.is_file() and selected != target):
                raise ValueError("explicit source files must exist inside the analysis scope")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    frontend = frontend_fingerprint()
    if hazard_only:
        frontend = fingerprint(frontend, "local-hazards/1", sha256(Path(local_hazards.__file__).read_bytes()).hexdigest())
    database = root / ".ken/structural/v2/store.sqlite"
    disk_budget = max(0, budget - compilation_cache["capacity_bytes"] / 1_000_000)
    acquisition = AcquisitionLock(database, enabled=disk_budget >= MIN_PERSISTENT_MB)
    try:
        store = Store(database, cache_mb=disk_budget)
    except BaseException:
        acquisition.close()
        raise
    parsed, reused = 0, 0
    request.phase("prepare", lease_id=store.lease_id, database=str(database))
    skipped: list[dict[str, str]] = []
    units: list[int] = []
    manifest: list[tuple[str, str]] = []
    ephemeral = store.path is None
    build_start = time.monotonic()
    try:
        from ken.structural_store.maintenance import trim

        quota_reclamation = trim(store)
        compile_key = artifact_key(source, query_name, reference, libraries)
        touched: set[str] = set()
        if compile_state == "disk_hit":
            touched.add(compile_key)
        elif compile_state == "miss":
            write_artifact(store, compile_key, "compiled", CODEC, encode(prepared))
        parent = store.current
        paths = [Path(p) for p in sorted(set(source_paths))] if source_paths is not None else (
            sorted(iter_files(root, path=path)) if target.is_dir() else [target.relative_to(root)]
        )
        for relative in paths:
            request.phase("source", current_path=relative.as_posix(),
                          parsed_units=parsed, reused_units=reused)
            try:
                absolute = resolve_project_path(root, relative)
                if target.is_dir() and not absolute.is_relative_to(target):
                    continue
                language = LANGUAGES.get(relative.suffix.lower())
                if not language:
                    # Known source extensions without a frontend are visible gaps.
                    if relative.suffix.lower() in {
                        ".c",
                        ".h",
                        ".kt",
                        ".swift",
                        ".scala",
                        ".dart",
                    }:
                        skipped.append(
                            {
                                "path": relative.as_posix(),
                                "reason": "unsupported_frontend",
                            }
                        )
                    continue
                with absolute.open("rb") as handle:
                    content = handle.read(max_file_bytes + 1)
                if len(content) > max_file_bytes:
                    skipped.append(
                        {"path": relative.as_posix(), "reason": "max_file_bytes"}
                    )
                    continue
            except (OSError, ValueError) as exc:
                skipped.append({"path": relative.as_posix(), "reason": str(exc)})
                continue
            source_hash = sha256(content).hexdigest()
            key = fingerprint(relative.as_posix(), language, source_hash, frontend)
            manifest.append((relative.as_posix(), source_hash))
            unit = store.find_unit(key)
            if unit is not None:
                reused += 1
            else:
                try:
                    request.phase("parse")
                    lower = local_hazards.lower if hazard_only else lower_source
                    ir = lower(content, language, relative.as_posix())
                except Exception as exc:
                    skipped.append(
                        {
                            "path": relative.as_posix(),
                            "reason": f"frontend_error: {type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                parsed += 1
                try:
                    request.phase("persist", parsed_units=parsed, reused_units=reused)
                    from .retention import retain_unit

                    unit = retain_unit(store, key, ir, source_hash, frontend, reclaim=not hazard_only)
                    parent = store.current
                except MemoryError:
                    # Preserve source revisions already captured, without reparsing
                    # or evicting facts still needed by this request.
                    temporary = Store(cache_mb=0)
                    try:
                        translated = []
                        for old_id in units:
                            row = store.db.execute(
                                "SELECT unit_key,source_hash,frontend_hash FROM k2_units WHERE unit_id=?",
                                (old_id,),
                            ).fetchone()
                            translated.append(
                                temporary.put_unit(
                                    row[0], store.load_unit(old_id), row[1], row[2]
                                )
                            )
                        new_unit = temporary.put_unit(key, ir, source_hash, frontend)
                    except BaseException:
                        temporary.close()
                        raise
                    store.close()
                    store, units, unit = temporary, translated, new_unit
                    parent, ephemeral = None, True
                if ir.diagnostics:
                    skipped.append(
                        {
                            "path": relative.as_posix(),
                            "reason": "; ".join(ir.diagnostics),
                        }
                    )
            units.append(unit)
        try:
            request.phase("snapshot", parsed_units=parsed, reused_units=reused)
            snapshot = store.publish(
                units, expected_parent=parent, profile=frontend, complete=not skipped
            )
        except MemoryError:
            temporary = Store(cache_mb=0)
            try:
                translated = []
                for old_id in units:
                    row = store.db.execute(
                        "SELECT unit_key,source_hash,frontend_hash FROM k2_units WHERE unit_id=?",
                        (old_id,),
                    ).fetchone()
                    translated.append(
                        temporary.put_unit(
                            row[0], store.load_unit(old_id), row[1], row[2]
                        )
                    )
                snapshot = temporary.publish(
                    translated,
                    expected_parent=None,
                    profile=frontend,
                    complete=not skipped,
                )
            except BaseException:
                temporary.close()
                raise
            store.close()
            store, ephemeral = temporary, True
        gc = (
            collect(store)
            if not ephemeral
            else {"deferred": False, "snapshots": 0, "units": 0}
        )
        acquisition.close()
        build_ms = (time.monotonic() - build_start) * 1000
        result_key = fingerprint(
            "query-result/1",
            implementation_fingerprint(),
            program.fingerprint,
            str(snapshot),
        )
        lookup_start = time.monotonic()
        cached = (
            read_artifact(
                store.db,
                result_key,
                "query-result-json/1",
                max_bytes=int(disk_budget * 1_000_000),
            )
            if not reference and not ephemeral and not profile
            else None
        )
        cached_result = None
        if cached is not None:
            import json

            try:
                candidate = json.loads(cached)
                if valid_cached_result(
                    candidate, program.name, len(program.projection), max_rows
                ):
                    cached_result = candidate
                    touched.add(result_key)
            except (ValueError, TypeError):
                pass
        lookup_ms = (time.monotonic() - lookup_start) * 1000
        request.phase("query", parsed_units=parsed, reused_units=reused, execution_phase="query")
        outcome = (
            None
            if cached_result
            else execute(
                program,
                store,
                snapshot,
                timeout_ms=request.remaining(
                    None if timeout_ms is None else max(0, timeout_ms - (time.monotonic() - start) * 1000)
                ),
                max_states=max_states,
                max_rows=max_rows,
                reference=reference,
                prepared_plans=dict(prepared.plans),
                profile=profile,
            )
        )
        coverage = bool(
            store.db.execute(
                "SELECT coverage FROM k2_snapshots WHERE snapshot_id=?", (snapshot,)
            ).fetchone()[0]
        )
        if cached_result is not None:
            response = cached_result
            query_ms: float | None = None
            scanned_nodes = states = 0
        else:
            assert outcome is not None
            response = {
                "language": "kql/2",
                "capability": "structural-source/1",
                "query": program.name,
                "columns": [
                    expr.value or f"column_{i + 1}"
                    for i, expr in enumerate(program.projection)
                ],
                "rows": [[serialize_value(v) for v in row] for row in outcome.rows],
                "complete": outcome.complete,
                "coverage_complete": coverage,
                "unknown_candidates": outcome.unknown_candidates,
                "reason": outcome.reason,
                "results_truncated": outcome.results_truncated,
                "plan": outcome.plan,
                "optional_evidence": outcome.optional_evidence,
            }
            query_ms = outcome.elapsed_ms
            scanned_nodes, states = outcome.scanned_nodes, outcome.states
            request.phase("report", result=response)
            if (
                outcome.complete
                and coverage
                and not reference
                and not ephemeral
                and not profile
            ):
                import json

                write_artifact(
                    store,
                    result_key,
                    "result",
                    "query-result-json/1",
                    json.dumps(response, separators=(",", ":")).encode(),
                    snapshot=snapshot,
                )
        if source_paths is not None:
            response["source_scope"] = {"kind": "explicit_files", "paths": sorted(set(source_paths))}
        # Authoring advice is recomputed from the prepared program on cache hits;
        # the execution-result artifact retains its exact, validated schema.
        if diagnostics:
            response["diagnostics"] = diagnostics
        touch_many(store, touched)
        response["analysis"] = {
            "snapshot": snapshot,
            "manifest": manifest,
            "frontend": frontend,
            "freshness": "captured_snapshot",
            "source_profile": "local_hazards" if hazard_only else "full",
            "skipped": skipped,
            "parsed_units": parsed,
            "reused_units": reused,
            "cache_mb": budget,
            "disk_budget_mb": disk_budget,
            "compilation_cache": {**compilation_cache, "status": compile_state},
            "result_cache": "disk_hit" if cached_result else "miss",
            "ephemeral": ephemeral,
            "allocated_bytes": store.allocated_bytes,
            "gc": gc,
            "quota_reclamation": quota_reclamation,
            "scanned_nodes": scanned_nodes,
            "states": states,
            "compile_ms": compile_ms,
            "build_ms": build_ms,
            "query_ms": query_ms,
            "result_lookup_ms": lookup_ms,
            "total_ms": (time.monotonic() - start) * 1000,
        }
        if include_entities:
            from ken.structural_store.node_locations import locations

            identities = {
                value if isinstance(value, str) else value.get("local_id", "")
                for row in response["rows"]
                for value in row
                if isinstance(value, (str, dict))
            }
            response["entities"] = locations(store, snapshot, identities)
        if profile:
            assert outcome is not None
            response["analysis"]["operator_profile"] = outcome.profile
        request.phase("report", result=response)
        return response
    finally:
        acquisition.close()
        store.close()


def serialize_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return serialize_value(asdict(value))
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {key: serialize_value(v) for key, v in value.items()}
    return value


def valid_cached_result(
    value: Any, query: str, columns: int, max_rows: int | None
) -> bool:
    expected = {
        "language",
        "capability",
        "query",
        "columns",
        "rows",
        "complete",
        "coverage_complete",
        "unknown_candidates",
        "reason",
        "results_truncated",
        "plan",
        "optional_evidence",
    }
    return (
        isinstance(value, dict)
        and set(value) == expected
        and value["language"] == "kql/2"
        and value["query"] == query
        and value["complete"] is True
        and value["coverage_complete"] is True
        and value["reason"] is None
        and type(value["unknown_candidates"]) is int
        and value["unknown_candidates"] >= 0
        and type(value["results_truncated"]) is bool
        and isinstance(value["plan"], list)
        and isinstance(value["columns"], list)
        and isinstance(value["optional_evidence"], list)
        and len(value["columns"]) == columns
        and isinstance(value["rows"], list)
        and (max_rows is None or len(value["rows"]) <= max_rows)
        and all(isinstance(row, list) and len(row) == columns for row in value["rows"])
    )
