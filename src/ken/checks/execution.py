"""A bounded KQL runner; timeouts never become successful empty searches."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def run(
    root: Path,
    query: str,
    *,
    path: str = ".",
    libraries: dict | None = None,
    timeout_ms: int = 10000,
    max_rows: int = 100,
    cache_mb: int = 100,
) -> dict:
    if not 1 <= timeout_ms <= 120000 or not 1 <= max_rows <= 1000:
        raise ValueError("timeout_ms must be 1..120000; max_rows must be 1..1000")
    request = dict(
        root=str(root.resolve()),
        query=query,
        path=path,
        libraries=libraries,
        timeout_ms=timeout_ms,
        max_rows=max_rows,
        cache_mb=cache_mb,
    )
    return _invoke(request, timeout_ms)


def run_batch(
    root: Path,
    queries: dict[str, str],
    *,
    path: str = ".",
    timeout_ms: int = 10000,
    max_rows: int = 1000,
    seeds: list[str] | None = None,
    incoming: bool = False,
    focus: dict | None = None,
) -> dict:
    """Evaluate related observations in one worker against checked source inputs."""
    if not 1 <= timeout_ms <= 120000 or not 1 <= max_rows <= 1000:
        raise ValueError("invalid execution budget")
    if not 1 <= len(queries) <= 8:
        raise ValueError("a batch requires 1..8 queries")
    result = _invoke(
        dict(
            root=str(root.resolve()),
            queries=queries,
            path=path,
            timeout_ms=timeout_ms,
            max_rows=max_rows,
            seeds=seeds,
            incoming=incoming,
            focus=focus,
        ),
        timeout_ms,
    )
    if "results" not in result:
        return {"results": {name: dict(result) for name in queries}}
    return result


def _invoke(request: dict, timeout_ms: int) -> dict:
    # Preserve the exact implementation even when Ken is launched from a checkout.
    source = str(Path(__file__).resolve().parents[2])
    bootstrap = "import sys; sys.path.insert(0, sys.argv[1]); from ken.checks.worker import main; main()"
    try:
        # -I excludes project cwd/PYTHONPATH/sitecustomize. Only the trusted Ken
        # package is added explicitly: analyzing a repository must not import it.
        process = subprocess.run(
            [sys.executable, "-I", "-c", bootstrap, source],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            cwd=source,
            timeout=timeout_ms / 1000,
        )
        if process.returncode:
            raise ValueError(
                f"query worker exited {process.returncode}: {process.stderr[-500:]}"
            )
        return json.loads(process.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        reason = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        return {
            "rows": [],
            "complete": False,
            "coverage_complete": False,
            "unknown_candidates": 0,
            "reason": reason,
        }
