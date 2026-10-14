"""Public-input execution, separate from frozen references and deterministic grading."""
from __future__ import annotations

from collections.abc import Callable, Iterable
import hashlib
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from ken.bench.dataset import Record
from ken.bench.retrieval import request_for_case


def source_manifest(root: Path, files: Iterable[Path]) -> Record:
    paths = sorted(files)
    manifest = hashlib.sha256()
    for path in paths:
        manifest.update(path.as_posix().encode())
        manifest.update(hashlib.sha256((root / path).read_bytes()).digest())
    return {"files": len(paths), "source_tree_sha256": manifest.hexdigest()}


def run_cases(cases: Iterable[Record],
              execute: Callable[[str, Record], Record]) -> list[Record]:
    responses = []
    for case in cases:
        try:
            response = execute(case["repo_id"], request_for_case(case))
        except Exception as exc:
            response = {"error": f"{type(exc).__name__}: {exc}", "results": []}
        responses.append({**response, "id": case["id"]})
    return responses


def run_live(cases: Iterable[Record], roots: Mapping[str, Path], index_directory: Path, *,
             profile: Any = None, rebuild: bool = True) -> Record:
    """Run the actual engine; keep runtime work out of deterministic grading."""
    from ken.db import connect, init_schema
    from ken.gitignore_filter import iter_files
    from ken.retrieval.indexing import index_project
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.profile import default_profile
    from ken.retrieval.service import search

    cases = list(cases)
    profile = profile or default_profile()
    index_directory.mkdir(parents=True, exist_ok=True)
    connections = {}
    stats = {}
    timings: list[float] = []
    try:
        for repo_id in sorted({c["repo_id"] for c in cases}):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo_id) or repo_id in (".", ".."):
                raise ValueError("repository id is not a safe index name")
            root = roots[repo_id]
            conn = connect(index_directory / (repo_id + ".db"))
            connections[repo_id] = conn
            init_schema(conn)
            start = time.perf_counter()
            files = list(iter_files(root))
            item = source_manifest(root, files)
            if rebuild:
                item.update(asdict(index_project(conn, root, files, profile=profile)))
            item["passages"] = conn.execute("SELECT COUNT(*) FROM ci_passages").fetchone()[0]
            item["index_ms"] = (time.perf_counter() - start) * 1000
            stats[repo_id] = item
        def execute(repo_id: str, request: Record) -> Record:
            start = time.perf_counter()
            try:
                return search(connections[repo_id], roots[repo_id], SearchRequest(**request),
                              profile=profile).to_dict()
            finally:
                timings.append((time.perf_counter() - start) * 1000)
        responses = run_cases(cases, execute)
        return {"responses": responses, "timings_ms": timings, "index_stats": stats,
                "profile": profile.to_dict(), "profile_sha256": profile.fingerprint}
    finally:
        for conn in connections.values():
            conn.close()
