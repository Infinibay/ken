"""Retrieve responsibility candidates, assess current evidence, and expose uncertainty."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from ken.embedder import (
    configure_for_project,
    cosine_against,
    embed_intent_text,
    get_embedder,
)

from .model import Reasoner
from .reasoners import (
    CallsReasoner,
    DocumentationReasoner,
    NameReasoner,
    terms,
)
from .source import SourceReader
from .retrieval import retrieve
from .assessment import assess_symbol, present

DEFAULT_REASONERS: tuple[Reasoner, ...] = (
    DocumentationReasoner(),
    NameReasoner(),
    CallsReasoner(),
)


def who(
    conn: sqlite3.Connection,
    root: Path,
    question: str,
    *,
    path: str = ".",
    hypotheses: list[str] | None = None,
    limit: int = 3,
    include_tests: bool = False,
    reasoners: tuple[Reasoner, ...] = DEFAULT_REASONERS,
) -> dict:
    """Find evidence for who owns an operation, without asserting semantic proof."""
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("question must be 1..2000 characters")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be 1..10")
    hypotheses = [] if hypotheses is None else hypotheses
    if (
        not isinstance(hypotheses, list)
        or len(hypotheses) > 3
        or any(
            not isinstance(h, str) or not h.strip() or len(h) > 500 for h in hypotheses
        )
    ):
        raise ValueError(
            "hypotheses must contain at most 3 non-empty formulations of at most 500 characters"
        )
    root = root.resolve()
    scope = (root / path).resolve()
    if not scope.is_relative_to(root):
        raise ValueError("path must be within the project")
    formulations = list(
        dict.fromkeys([question.strip(), *[h.strip() for h in hypotheses]])
    )
    configure_for_project(conn)
    embedder = get_embedder()
    queries = [embedder.embed_query(q) for q in formulations]
    query_terms = [terms(q) for q in formulations]
    rows, indexed_count = retrieve(
        conn, root, scope, query_terms, queries, include_tests=include_tests
    )
    reader = SourceReader(root)
    live = []
    issues = []
    for row in rows:
        try:
            live.append(reader.resolve(row))
        except (OSError, ValueError, SyntaxError, RuntimeError) as exc:
            issues.append(
                {
                    "path": row["path"],
                    "qualname": row["qualname"],
                    "reason": str(exc)[:180],
                }
            )
    # Re-embed the current full documentation of the small candidate set. The
    # stored index selects candidates only; stale quotes never become evidence.
    import numpy as np

    passages = [
        embed_intent_text(
            "module_docstring" if s.kind == "module" else "symbol_docstring",
            s.documentation[:12000],
        )
        for s in live
    ]
    matrix = (
        np.asarray(embedder.embed_passages(passages), dtype=np.float32)
        if live
        else np.zeros((0, embedder.dim))
    )
    current_scores = [cosine_against(q, matrix) for q in queries]
    candidates = [
        assess_symbol(
            symbol,
            formulations,
            query_terms,
            [scores[i] for scores in current_scores],
            reasoners,
        )
        for i, symbol in enumerate(live)
    ]
    return present(
        question,
        candidates,
        limit=limit,
        scope=scope.relative_to(root).as_posix(),
        indexed_count=indexed_count,
        inspected_count=len(live),
        include_tests=include_tests,
        issues=issues,
        hypotheses=formulations[1:],
    )
