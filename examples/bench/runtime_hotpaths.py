"""Repeatable microbenchmark for Ken's runtime hot-path optimizations.

Run from the repository root with::

    uv run python examples/bench/runtime_hotpaths.py

The benchmark compares the current implementations with local equivalents of
prior behavior. It uses deterministic fake embeddings so it measures removed
work rather than model or hardware variance.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from ken import _paths
from ken.daemon.server import _handle_prompt
from ken.db import connect
from ken.embedder import get_embedder, vec_to_blob
from ken.search import (
    _filter_live_rows,
    _fuse_literal,
    _identifier_query,
    _query_vec,
    _score_rows,
    _scored_from_store,
    search_files,
)


def _percentiles(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)

    def value(percentile: float) -> float:
        index = round((len(ordered) - 1) * percentile)
        return ordered[index]

    return {
        "p50": value(0.50),
        "p95": value(0.95),
        "p99": value(0.99),
        "mean": statistics.fmean(ordered),
    }


def _measure(operation: Callable[[], Any], repeats: int) -> tuple[list[float], Any]:
    operation()
    samples: list[float] = []
    expected: Any = None
    for _ in range(repeats):
        started = time.perf_counter_ns()
        result = operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
        if expected is None:
            expected = result
        elif result != expected:
            raise AssertionError("benchmark operation returned non-deterministic output")
    return samples, expected


def _legacy_search_files(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Previous search_files outline hydration, retained only as a baseline."""
    q = _query_vec(query)
    scored = _scored_from_store(
        conn,
        "ci_files",
        q,
        "SELECT vec_slot, id, path, language FROM ci_files "
        "WHERE vec_slot IN ({placeholders})",
        "path",
        None,
    )
    if scored is None:
        rows = conn.execute(
            "SELECT id, path, language, embedding FROM ci_files WHERE embedding IS NOT NULL"
        ).fetchall()
        scored = _score_rows(q, _filter_live_rows(rows, "path", None))
    ranked = _fuse_literal(
        scored,
        _identifier_query(query),
        lambda row: (Path(row["path"]).stem, Path(row["path"]).name, row["path"]),
        limit,
    )

    output: list[dict[str, Any]] = []
    for score, row, tier in ranked:
        outline_rows = conn.execute(
            "SELECT kind, name, line_start FROM ci_symbols "
            "WHERE file_id = ? ORDER BY line_start LIMIT 8",
            (int(row["id"]),),
        ).fetchall()
        output.append(
            {
                "path": row["path"],
                "language": row["language"] or "text",
                "score": round(float(score), 3),
                **({"match": {1: "tokens", 2: "qualified", 3: "exact"}[tier]} if tier else {}),
                "symbols": [
                    {"kind": item["kind"], "name": item["name"], "line": int(item["line_start"])}
                    for item in outline_rows
                ],
            }
        )
    return output


def _search_database(path: Path, files: int, symbols_per_file: int) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE ci_files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            language TEXT,
            embedding BLOB,
            vec_slot INTEGER
        );
        CREATE TABLE ci_symbols (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            line_start INTEGER NOT NULL
        );
        CREATE INDEX idx_symbols_file ON ci_symbols(file_id);
        """
    )
    for file_index in range(files):
        angle = file_index / max(files, 1)
        embedding = np.zeros(1_024, dtype=np.float32)
        embedding[0] = 1.0 - angle
        embedding[1] = angle
        cursor = conn.execute(
            "INSERT INTO ci_files(path, language, embedding) VALUES (?, 'python', ?)",
            (f"src/module_{file_index:05d}.py", vec_to_blob(embedding)),
        )
        file_id = int(cursor.lastrowid or 0)
        conn.executemany(
            "INSERT INTO ci_symbols(file_id, kind, name, line_start) VALUES (?, 'function', ?, ?)",
            [
                (file_id, f"function_{file_index}_{symbol_index}", symbol_index * 3 + 1)
                for symbol_index in range(symbols_per_file)
            ],
        )
    conn.commit()
    return conn


def _count_outline_queries(conn: sqlite3.Connection, operation: Callable[[], Any]) -> int:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        operation()
    finally:
        conn.set_trace_callback(None)
    return sum("FROM ci_symbols" in statement for statement in statements)


class _SleepingEmbedder:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def embed_query(self, _content: str) -> np.ndarray:
        self.calls += 1
        time.sleep(self.delay_seconds)
        return np.array([1.0, 0.0], dtype=np.float32)


class _PromptState:
    def __init__(self, embedder: _SleepingEmbedder) -> None:
        self.embedder = embedder
        self.lock = threading.Lock()
        self.sessions = {"agent": {"iter": 1}}
        self.conn = object()
        self.project_root = Path(".")
        self.stored_embeddings: list[bytes | None] = []

    def record_context(
        self,
        _agent_id: str,
        _kind: str,
        content: str,
        *,
        embed: bool = False,
        embedding: np.ndarray | None = None,
    ) -> int:
        vector = embedding
        if vector is None and embed and content.strip():
            vector = self.embedder.embed_query(content)
        self.stored_embeddings.append(None if vector is None else vec_to_blob(vector))
        return len(self.stored_embeddings)


def _legacy_handle_prompt(state: _PromptState, agent_id: str, content: str) -> str:
    """Previous prompt embedding flow, retained only as a baseline."""
    from ken.embedder import get_embedder
    from ken.ranker import rank
    from ken.ranker.output import render_block

    state.record_context(agent_id, "user_prompt", content, embed=True)
    if not content.strip():
        return ""
    prompt_vector = get_embedder().embed_query(content)
    result = rank(
        state.conn,
        agent_id=agent_id,
        current_iteration=1,
        prompt=content,
        prompt_embedding=prompt_vector,
        project_root=state.project_root,
    )
    return render_block(state.conn, result, verbose=0, max_chars=12_000)


def _benchmark_search(args: argparse.Namespace, database_path: Path) -> None:
    conn = _search_database(database_path, args.files, args.symbols_per_file)
    query_vector = np.zeros(1_024, dtype=np.float32)
    query_vector[0] = 1.0
    candidate_rows = conn.execute(
        "SELECT id, path, language FROM ci_files ORDER BY id LIMIT ?",
        (args.limit,),
    ).fetchall()
    scored_candidates = [
        (1.0 - index / max(len(candidate_rows), 1), row)
        for index, row in enumerate(candidate_rows)
    ]
    current = lambda: search_files(conn, "semantic prose query", limit=args.limit)
    legacy = lambda: _legacy_search_files(conn, "semantic prose query", limit=args.limit)

    with ExitStack() as stack:
        stack.enter_context(patch("ken.search._query_vec", return_value=query_vector))
        stack.enter_context(patch(f"{__name__}._query_vec", return_value=query_vector))
        stack.enter_context(
            patch("ken.search._scored_from_store", return_value=scored_candidates)
        )
        stack.enter_context(
            patch(f"{__name__}._scored_from_store", return_value=scored_candidates)
        )
        current_queries = _count_outline_queries(conn, current)
        legacy_queries = _count_outline_queries(conn, legacy)
        current_samples, current_output = _measure(current, args.repeats)
        legacy_samples, legacy_output = _measure(legacy, args.repeats)

    conn.close()
    if current_output != legacy_output:
        raise AssertionError("search_files output differs from the legacy baseline")
    print("search_files (warm, identical mapped-store candidates)")
    print(f"  exact output equivalence: yes ({len(current_output)} hits)")
    print(f"  outline SQL statements: legacy={legacy_queries}, current={current_queries}")
    _print_latency(legacy_samples, current_samples)


def _benchmark_prompt(args: argparse.Namespace) -> None:
    prompt = "find the parser implementation and its tests"

    def run(operation: Callable[[_PromptState, str, str], str]) -> tuple[str, bytes | None, int]:
        embedder = _SleepingEmbedder(args.embedding_ms / 1000)
        state = _PromptState(embedder)
        with ExitStack() as stack:
            stack.enter_context(patch("ken.embedder.get_embedder", return_value=embedder))
            stack.enter_context(patch("ken.ranker.rank", return_value={"ranked": True}))
            stack.enter_context(patch("ken.ranker.output.render_block", return_value="<context-rank/>"))
            output = operation(state, "agent", prompt)
        return output, state.stored_embeddings[-1], embedder.calls

    legacy_calls = run(_legacy_handle_prompt)[2]
    current_calls = run(_handle_prompt)[2]
    legacy_samples, legacy_output = _measure(lambda: run(_legacy_handle_prompt), args.repeats)
    current_samples, current_output = _measure(lambda: run(_handle_prompt), args.repeats)
    if legacy_output[:2] != current_output[:2]:
        raise AssertionError("prompt output or persisted embedding differs from legacy baseline")
    print("_handle_prompt (warm, controlled embedding cost)")
    print("  exact output and stored-vector equivalence: yes")
    print(f"  embedding inferences: legacy={legacy_calls}, current={current_calls}")
    _print_latency(legacy_samples, current_samples)


def _print_latency(legacy: list[float], current: list[float]) -> None:
    old = _percentiles(legacy)
    new = _percentiles(current)
    print("  latency ms          legacy    current    change")
    for key in ("p50", "p95", "p99", "mean"):
        change = ((new[key] / old[key]) - 1.0) * 100 if old[key] else 0.0
        print(f"  {key:4}              {old[key]:8.3f}  {new[key]:8.3f}  {change:+7.1f}%")


def _timed_call(
    label: str,
    operation: Callable[..., Any],
    samples: dict[str, list[float]],
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter_ns()
        try:
            return operation(*args, **kwargs)
        finally:
            samples[label].append((time.perf_counter_ns() - started) / 1_000_000)

    return wrapped


def _rank_signature(result: Any) -> tuple[Any, ...]:
    """Compare rank identity/order while allowing time-decayed score drift."""
    return (
        tuple(item.target for item in result.files),
        tuple(item.target for item in result.symbols),
        tuple(item.topic for item in result.findings),
    )


def _print_profile(samples: dict[str, list[float]]) -> None:
    print("  phase                         calls    p50 ms    p95 ms    p99 ms   mean ms")
    for label, values in sorted(
        samples.items(), key=lambda item: statistics.fmean(item[1]), reverse=True
    ):
        summary = _percentiles(values)
        print(
            f"  {label:28} {len(values):5d}  {summary['p50']:8.3f}"
            f"  {summary['p95']:8.3f}  {summary['p99']:8.3f}  {summary['mean']:8.3f}"
        )


def _benchmark_runtime_profile(args: argparse.Namespace, project_root: Path) -> None:
    """Attribute warm runtime cost on an already indexed real project."""
    from ken import vectors
    from ken.mcp import server as mcp_server
    from ken.ranker import boosts, channels, ppr
    from ken.ranker import rank as run_rank

    root = project_root.resolve()
    database_path = _paths.db_path(root)
    if not database_path.is_file():
        raise FileNotFoundError(f"no Ken database at {database_path}")

    setup_samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(args.profile_repeats):
        started = time.perf_counter_ns()
        opened = connect(database_path)
        opened.close()
        setup_samples["sqlite.connect+close"].append(
            (time.perf_counter_ns() - started) / 1_000_000
        )

    # Exercise MCP's real per-tool setup rather than approximating it with a
    # direct connect call.  Patching the root keeps this opt-in benchmark from
    # mutating server process state.
    with patch.object(mcp_server, "_PROJECT_ROOT", root):
        for _ in range(args.profile_repeats):
            started = time.perf_counter_ns()
            opened = mcp_server._conn()
            opened.close()
            setup_samples["mcp._conn+close"].append(
                (time.perf_counter_ns() - started) / 1_000_000
            )

    conn = connect(database_path)
    prompt = args.profile_query
    prompt_vector = get_embedder().embed_query(prompt)
    phase_samples: dict[str, list[float]] = defaultdict(list)
    channel_names = (
        "similar_past_sessions",
        "explicit_mentions",
        "reactive_scores",
        "predictive_scores",
        "fuzzy_scores",
        "doc_intent_scores",
        "literal_content_scores",
        "lexical_scores",
        "finding_scores",
    )
    boost_names = (
        "apply_symbol_file_affinity",
        "apply_freshness",
        "apply_cooc",
        "apply_test_affinity",
        "apply_import_affinity",
        "apply_dismissal_penalty",
        "apply_implementation_intent",
        "apply_documentation_intent",
        "apply_language_intent",
    )

    expected: Any = None
    with ExitStack() as stack:
        for name in channel_names:
            original = getattr(channels, name)
            stack.enter_context(
                patch.object(channels, name, _timed_call(f"channel.{name}", original, phase_samples))
            )
        for name in boost_names:
            original = getattr(boosts, name)
            stack.enter_context(
                patch.object(boosts, name, _timed_call(f"boost.{name}", original, phase_samples))
            )
        original_ppr = ppr.apply_ppr
        stack.enter_context(
            patch.object(ppr, "apply_ppr", _timed_call("boost.apply_ppr", original_ppr, phase_samples))
        )

        run_rank(
            conn,
            agent_id="runtime-profile",
            current_iteration=1,
            prompt=prompt,
            prompt_embedding=prompt_vector,
            project_root=root,
        )
        phase_samples.clear()
        for _ in range(args.profile_repeats):
            started = time.perf_counter_ns()
            result = run_rank(
                conn,
                agent_id="runtime-profile",
                current_iteration=1,
                prompt=prompt,
                prompt_embedding=prompt_vector,
                project_root=root,
            )
            phase_samples["rank.e2e"].append(
                (time.perf_counter_ns() - started) / 1_000_000
            )
            signature = _rank_signature(result)
            if expected is None:
                expected = signature
            elif signature != expected:
                raise AssertionError("rank profile returned non-deterministic identity/order")

    store_samples: dict[str, list[float]] = defaultdict(list)
    for space in ("files", "symbols", "intent"):
        for _ in range(args.profile_repeats):
            started = time.perf_counter_ns()
            vectors.live_scores(conn, space, prompt_vector)
            store_samples[f"vector_store.{space}"].append(
                (time.perf_counter_ns() - started) / 1_000_000
            )
    conn.close()

    print(f"runtime profile ({root}, warm, {args.profile_repeats} repeats)")
    print("  stable rank identity/order: yes")
    _print_profile(setup_samples)
    _print_profile(store_samples)
    _print_profile(phase_samples)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--files", type=int, default=2_000)
    parser.add_argument("--symbols-per-file", type=int, default=12)
    parser.add_argument("--limit", type=int, default=32)
    parser.add_argument("--embedding-ms", type=float, default=2.0)
    parser.add_argument(
        "--profile-project",
        type=Path,
        help="also profile warm rank phases against this indexed project",
    )
    parser.add_argument("--profile-repeats", type=int, default=30)
    parser.add_argument(
        "--profile-query",
        default="find the search implementation and its tests",
    )
    args = parser.parse_args()
    if min(args.repeats, args.files, args.symbols_per_file, args.limit) <= 0:
        parser.error("repeats, files, symbols-per-file, and limit must be positive")
    if args.embedding_ms < 0:
        parser.error("embedding-ms must not be negative")
    if args.profile_repeats <= 0:
        parser.error("profile-repeats must be positive")

    with tempfile.TemporaryDirectory(prefix="ken-runtime-bench-") as directory:
        _benchmark_search(args, Path(directory) / "search.db")
    print()
    _benchmark_prompt(args)
    if args.profile_project is not None:
        print()
        _benchmark_runtime_profile(args, args.profile_project)


if __name__ == "__main__":
    main()
