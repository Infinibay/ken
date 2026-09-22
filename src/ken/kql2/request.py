"""Enforce a wall-clock budget around the entire search, including preparation.

Native parsers, SQLite locks and graph construction may not yield. A supervised
worker provides the deadline boundary; progress reports explain where it stopped.
The unlimited in-process API keeps its existing caches and calling semantics.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path

_ACTIVE: ContextVar[Progress | None] = ContextVar("kql2_request", default=None)


class Progress:
    """One request's deadline and last observable preparation phase."""

    def __init__(self, destination: Path | None, deadline: float):
        self.destination = destination
        self.deadline = deadline
        self.last_write = 0.0
        self.state: dict = {"phase": "startup"}

    def update(self, phase: str, **details) -> None:
        changed = phase != self.state["phase"]
        self.state.update(details, phase=phase)
        if self.destination is None:
            return
        now = time.monotonic()
        if changed or now - self.last_write >= 0.05 or "result" in details:
            temporary = self.destination.with_suffix(".next")
            temporary.write_text(json.dumps(self.state), encoding="utf-8")
            temporary.replace(self.destination)
            self.last_write = now


def active() -> bool:
    return _ACTIVE.get() is not None


@contextmanager
def supervised(timeout_ms: float):
    """Share the deadline of an existing worker (checks/inspection batches)."""
    token = _ACTIVE.set(Progress(None, time.monotonic() + timeout_ms / 1000))
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def phase(name: str, **details) -> None:
    progress = _ACTIVE.get()
    if progress is not None:
        progress.update(name, **details)


def remaining(timeout_ms: float | None) -> float | None:
    progress = _ACTIVE.get()
    if progress is None:
        return timeout_ms
    # Leave a small reporting window for execution's partial rows to reach the
    # supervisor. It still enforces the absolute deadline during serialization.
    remaining_ms = max(0.0, (progress.deadline - time.monotonic()) * 1000 - 30)
    return (
        remaining_ms if timeout_ms is None else max(0.0, min(timeout_ms, remaining_ms))
    )


def _failure(progress: Path, options: dict, started: float) -> dict:
    try:
        state = json.loads(progress.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"phase": "startup"}
    # The worker has been reaped, so its exact lease is no longer protecting a
    # reader. Releasing it avoids a five-minute cache stall after cancellation.
    # Never remove leases belonging to other processes.
    if state.get("lease_id") and state.get("database"):
        try:
            cleanup = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    (
                        "import sqlite3,sys; "
                        "db=sqlite3.connect(sys.argv[1],uri=True,timeout=0.02); "
                        "db.execute('DELETE FROM k2_leases WHERE lease_id=?',(sys.argv[2],)); "
                        "db.commit(); db.close()"
                    ),
                    Path(state["database"]).as_uri() + "?mode=rw",
                    state["lease_id"],
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.1,
                check=False,
            )
            if cleanup.returncode:
                state["lease_cleanup"] = "deferred"
        except (OSError, subprocess.TimeoutExpired):
            state["lease_cleanup"] = "deferred"
    result = state.get(
        "result",
        {
            "language": "kql/2",
            "query": state.get("query", options.get("query_name")),
            "columns": state.get("columns", []),
            "rows": [],
            "coverage_complete": False,
            "unknown_candidates": 0,
            "results_truncated": False,
        },
    )
    result.update(
        complete=False,
        reason="timeout" if options.get("backend") == "exploration" else "timeout_ms",
    )
    if state.get("diagnostics"):
        result["diagnostics"] = state["diagnostics"]
    result.setdefault("analysis", {}).update(
        total_ms=(time.monotonic() - started) * 1000,
        timeout_ms=options["timeout_ms"],
        stopped_phase=state["phase"],
        **{
            key: state[key]
            for key in ("parsed_units", "reused_units", "current_path", "lease_cleanup")
            if key in state
        },
    )
    return result


def bounded_search(root: Path, source: str, options: dict) -> dict:
    """Run trusted Ken code in isolation, reap on timeout, preserve diagnostics."""
    started = time.monotonic()
    deadline = started + options["timeout_ms"] / 1000
    source_directory = Path(__file__).resolve().parents[2]
    bootstrap = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from ken.kql2.request import worker; worker()"
    )
    payload = dict(options)
    if payload.get("cache_directory") is not None:
        payload["cache_directory"] = str(payload["cache_directory"])
    if payload.get("libraries") is not None:
        payload["libraries"] = dict(payload["libraries"])
    with tempfile.TemporaryDirectory(prefix="ken-kql2-request-") as directory:
        progress = Path(directory) / "progress.json"
        request = json.dumps(
            {
                "root": str(root.resolve()),
                "source": source,
                "options": payload,
                "deadline": deadline,
                "progress": str(progress),
            }
        )
        if time.monotonic() >= deadline:
            return _failure(progress, options, started)
        with subprocess.Popen(
            [sys.executable, "-I", "-c", bootstrap, str(source_directory)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=source_directory,
        ) as process:
            try:
                stdout, stderr = process.communicate(
                    request, timeout=max(0, deadline - time.monotonic())
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return _failure(progress, options, started)
        if process.returncode:
            raise RuntimeError(
                f"KQL2 worker failed ({process.returncode}): {stderr[-2000:]}"
            )
        response = json.loads(stdout)
        if "error" in response:
            error = response["error"]
            if "span" in error:
                from .compiler import CompileError
                from .syntax import ParseError, Span

                exception = (
                    CompileError if error["kind"] == "CompileError" else ParseError
                )
                raise exception(error["message"], Span(**error["span"]), error["code"])
            if error.get("value_error"):
                raise ValueError(error["message"])
            raise RuntimeError(error["message"])
        result = response["result"]
        analysis = result.setdefault("analysis", {})
        analysis.update(
            total_ms=(time.monotonic() - started) * 1000,
            timeout_ms=options["timeout_ms"],
        )
        return result


def worker() -> None:
    """JSON protocol used only by the trusted supervisor, never project imports."""
    request = json.load(sys.stdin)
    options = request["options"]
    if options.get("cache_directory") is not None:
        options["cache_directory"] = Path(options["cache_directory"])
    progress = Progress(Path(request["progress"]), request["deadline"])
    token = _ACTIVE.set(progress)
    try:
        from .service import search

        result = search(Path(request["root"]), request["source"], **options)
        if result.get("reason") in {"timeout", "timeout_ms"}:
            result.setdefault("analysis", {})["stopped_phase"] = progress.state.get(
                "execution_phase", progress.state["phase"]
            )
        response = {"result": result}
    except Exception as exc:  # noqa: BLE001 — serialize the worker boundary's failure
        from .syntax import ParseError

        error: dict = {
            "kind": type(exc).__name__,
            "message": str(exc),
            "value_error": isinstance(exc, ValueError),
        }
        if isinstance(exc, ParseError):
            error.update(message=exc.message, span=asdict(exc.span), code=exc.code)
        response = {"error": error}
    finally:
        _ACTIVE.reset(token)
    print(json.dumps(response))
