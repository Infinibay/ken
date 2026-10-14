"""Incremental fielded lexical retrieval over the same source passages as dense views."""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Mapping

from ken.retrieval.model import Candidate, SearchRequest
from ken.retrieval.storage import load_passage_map
from ken.retrieval.tokenization import code_tokens

FIELDS = ("identity", "signature", "documentation", "body", "path")


def bm25f_score(frequencies: Mapping[str, int], lengths: Mapping[str, int],
               averages: Mapping[str, float], *, document_frequency: int,
               documents: int, k1: float = 1.2,
               weights: Mapping[str, float] | None = None) -> float:
    if not documents or not frequencies:
        return 0.0
    if not 0 <= document_frequency <= documents:
        raise ValueError("invalid document frequency")
    tf = 0.0
    for name, frequency in frequencies.items():
        b = 0.75 if name in ("body", "documentation") else 0.0
        average = averages.get(name, 0.0)
        norm = (1 - b + b * lengths.get(name, 0) / average) if average else 1.0
        tf += (weights or {}).get(name, 1.0) * frequency / norm
    if tf <= 0:
        return 0.0
    idf = math.log1p((documents - document_frequency + 0.5) / (document_frequency + 0.5))
    return idf * (k1 + 1) * tf / (k1 + tf)


def lexical_candidates(conn: sqlite3.Connection, request: SearchRequest,
                       limit: int = 100) -> list[Candidate]:
    terms = list(dict.fromkeys(code_tokens(request.query)))[:128]
    if not terms:
        return []
    placeholders = ",".join("?" for _ in terms)
    rows = conn.execute(
        "SELECT t.*,p.file_id,p.symbol_id FROM ci_passage_terms t "
        "JOIN ci_passages p ON p.id=t.passage_id WHERE t.term IN (" + placeholders + ")", terms,
    ).fetchall()
    if not rows:
        return []
    documents = int(conn.execute("SELECT COUNT(*) FROM ci_passages").fetchone()[0])
    averages = {r[0]: float(r[1]) for r in conn.execute(
        "SELECT field,AVG(length) FROM ci_passage_lengths GROUP BY field")}
    frequencies = {r[0]: int(r[1]) for r in conn.execute(
        "SELECT term,COUNT(DISTINCT passage_id) FROM ci_passage_terms WHERE term IN (" +
        placeholders + ") GROUP BY term", terms)}
    lengths: dict[int, dict[str, int]] = defaultdict(dict)
    for row in conn.execute(
        "SELECT * FROM ci_passage_lengths WHERE passage_id IN "
        "(SELECT passage_id FROM ci_passage_terms WHERE term IN (" + placeholders + "))", terms,
    ):
        lengths[row["passage_id"]][row["field"]] = row["length"]
    tf: dict[int, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    groups: dict[int, tuple[int, int | None]] = {}
    for row in rows:
        pid = row["passage_id"]
        tf[pid][row["term"]][row["field"]] = row["tf"]
        groups[pid] = (row["file_id"], row["symbol_id"])
    scores: dict[int, dict[str, float]] = {}
    for pid, term_counts in tf.items():
        features = {"bm25f": 0.0, **{f"bm25_{f}": 0.0 for f in FIELDS}}
        for term, field_counts in term_counts.items():
            features["bm25f"] += bm25f_score(
                field_counts, lengths[pid], averages,
                document_frequency=frequencies[term], documents=documents)
            for name, count in field_counts.items():
                features[f"bm25_{name}"] += bm25f_score(
                    {name: count}, lengths[pid], averages,
                    document_frequency=frequencies[term], documents=documents)
        scores[pid] = features
    grouped: dict[tuple[int, int | None], list[int]] = defaultdict(list)
    for pid in sorted(scores, key=lambda p: (-scores[p]["bm25f"], p)):
        grouped[groups[pid]].append(pid)
    selected = list(grouped.values())[:max(1, limit)]
    ids = [pid for group in selected for pid in group[:4]]
    passages = load_passage_map(conn, ids)
    out = []
    for group in selected:
        owned = [passages[pid] for pid in group[:4]]
        features = {name: max(scores[pid][name] for pid in group) for name in scores[group[0]]}
        out.append(Candidate(owned[0].entity, owned, features))
    return out
