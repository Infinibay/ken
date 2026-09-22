"""Select modules and symbols by documented purpose before inspecting source."""

from pathlib import Path
from ken import vectors
from ken.embedder import rank_against
from .reasoners import overlap


def retrieve(conn, root, scope, query_terms, queries, *, include_tests):
    rows = [
        dict(r)
        for r in conn.execute("""
        SELECT s.qualname,s.kind,s.name,s.docstring,f.path,f.content_hash,i.vec_slot,i.embedding
        FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id
        LEFT JOIN ci_intent_sources i ON i.symbol_id=s.id AND i.source_kind='symbol_docstring'
        WHERE s.kind IN ('function','method','class')
        UNION ALL
        SELECT f.path AS qualname,'module' AS kind,f.path AS name,i.text AS docstring,
               f.path,f.content_hash,i.vec_slot,i.embedding
        FROM ci_intent_sources i JOIN ci_files f ON f.id=i.file_id
        WHERE i.source_kind='module_docstring' AND i.symbol_id IS NULL
        ORDER BY path,kind,qualname
    """)
        if _in_scope(root, scope, r["path"])
        and (include_tests or not _is_test(r["path"], r["qualname"]))
    ]
    scores = _similarities(conn, rows, queries)
    ranked = sorted(
        enumerate(rows),
        key=lambda pair: (
            -max(
                max(
                    scores[j].get(pair[0], 0.0),
                    0.85 * overlap(t, pair[1]["docstring"] or ""),
                    0.65 * overlap(t, pair[1]["qualname"]),
                )
                for j, t in enumerate(query_terms)
            )
        ),
    )
    return [row for _, row in ranked[:40]], len(rows)


def _in_scope(root: Path, scope: Path, path: str) -> bool:
    # Lexical filtering first: source resolution checks symlink confinement.
    candidate = root / path
    return candidate == scope or candidate.is_relative_to(scope)


def _is_test(path: str, qualname: str) -> bool:
    p = Path(path)
    return (
        any(part in {"tests", "test", "__tests__"} for part in p.parts)
        or p.stem.startswith("test_")
        or qualname.startswith("test_")
    )


def _similarities(conn, rows, queries):
    result = []
    for query in queries:
        scored = vectors.live_scores(conn, "ci_intent_sources", query)
        by_slot = dict(zip(*scored)) if scored is not None else {}
        values = {
            i: float(by_slot[row["vec_slot"]])
            for i, row in enumerate(rows)
            if row["vec_slot"] in by_slot
        }
        missing = [
            i
            for i, row in enumerate(rows)
            if i not in values and row["embedding"] is not None
        ]
        sims, kept = rank_against(
            query, [rows[i]["embedding"] for i in missing], strict=False
        )
        values.update((missing[k], float(sim)) for k, sim in zip(kept, sims))
        result.append(values)
    return result
