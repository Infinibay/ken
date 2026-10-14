"""Union independent evidence sources, grouping by owner before applying budgets."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from ken.retrieval.embedding_store import IndexVersionError, load_vectors, retrieval_snapshot
from ken.retrieval.dense import DenseView
from ken.retrieval.lexical import lexical_candidates
from ken.retrieval.intent import interpret
from ken.retrieval.indexing import source_policy_key
from ken.retrieval.model import Candidate, EntityKey, Passage, SearchRequest, merge_spans
from ken.retrieval.profile import Encoder, EncoderSpec, RetrievalProfile, active_profile, load_encoder
from ken.retrieval.storage import load_passage_map


@lru_cache(maxsize=4)
def _passage_snapshot(conn: sqlite3.Connection, generation: int) -> Mapping[int, Passage]:
    # The caller pins the matching WAL generation before entering this cache.
    return load_passage_map(conn)


@lru_cache(maxsize=8)
def _vector_snapshot(conn: sqlite3.Connection, generation: int, view: str, revision: str):
    return DenseView(_passage_snapshot(conn, generation), load_vectors(conn, view, revision))


@lru_cache(maxsize=4)
def _region_snapshot(conn: sqlite3.Connection, generation: int):
    groups = defaultdict(list)
    for p in _passage_snapshot(conn, generation).values():
        groups[p.entity].append(p.span)
    return {entity: merge_spans(spans) for entity, spans in groups.items()}


@lru_cache(maxsize=256)
def _query_vector(spec: EncoderSpec, text: str) -> np.ndarray:
    vector = np.asarray(load_encoder(spec).embed_query(text), dtype=np.float32)
    vector.setflags(write=False)
    return vector


def _exact(conn: sqlite3.Connection, passages: Mapping[int, Passage],
           request: SearchRequest) -> list[Candidate]:
    intent = interpret(request)
    if not intent.identifiers:
        return []
    placeholders = ",".join("?" for _ in intent.identifiers)
    rows = conn.execute(
        "SELECT s.name,s.kind,s.qualname,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id "
        f"WHERE s.name COLLATE NOCASE IN ({placeholders}) OR s.qualname COLLATE NOCASE IN ({placeholders}) "
        "ORDER BY f.path,s.line_start,s.id", (*intent.identifiers, *intent.identifiers),
    ).fetchall()
    rows = [r for r in rows if intent.kind is None or r["kind"] == intent.kind]
    matching: set[tuple[str, str, str | None]] = set()
    for identifier in intent.identifiers:
        preferred = [r for r in rows if identifier in (r["name"], r["qualname"])]
        if not preferred:
            preferred = [r for r in rows if identifier.casefold() in (
                (r["name"] or "").casefold(), (r["qualname"] or "").casefold())]
        matching.update((r["path"], r["kind"], r["qualname"]) for r in preferred)
    groups: dict[EntityKey, list[Passage]] = defaultdict(list)
    for p in passages.values():
        if (p.entity.path, p.entity.kind, p.entity.qualname) in matching:
            groups[p.entity].append(p)
    return [Candidate(key, values, {"exact": 1.0})
            for key, values in groups.items()]


def retrieve(conn: sqlite3.Connection, root: Path, request: SearchRequest,
             profile: RetrievalProfile | None = None, *,
             encoders: Mapping[str, Encoder] | None = None) -> list[Candidate]:
    profile = profile or active_profile(conn)
    with retrieval_snapshot(conn) as snapshot:
        passages = _passage_snapshot(conn, snapshot.generation)
        if not passages:
            raise IndexVersionError("no source passages; reindex the project")
        exact = _exact(conn, passages, request)
        regions = _region_snapshot(conn, snapshot.generation)
        for candidate in exact:
            candidate.owned_regions = regions[candidate.entity]
        if len(exact) == 1:
            exact[0].signals["rrf"] = 1.0
            return exact
        version = conn.execute("SELECT value FROM meta WHERE key='retrieval_representation_version'").fetchone()
        if not version or version[0] != str(profile.representation_version):
            raise IndexVersionError("retrieval representation changed; reindex the project")
        policies = conn.execute("SELECT DISTINCT extractor_version,tokenizer_version,max_tokens "
                                "FROM ci_retrieval_files").fetchall()
        if any(tuple(row) != source_policy_key(profile) for row in policies):
            raise IndexVersionError("source passage policy changed; reindex the project")
        channels = [exact, lexical_candidates(conn, request, profile.candidate_limit)]
        injected_queries: dict[int, np.ndarray] = {}
        for view in ("identity", "behavior"):
            spec = getattr(profile, view)
            stored = _vector_snapshot(conn, snapshot.generation, view, profile.vector_revision(view))
            if set(stored.ids) != passages.keys():
                raise IndexVersionError(f"incomplete {view} vectors; reindex the retrieval profile")
            if encoders:
                encoder = encoders[view]
                if id(encoder) not in injected_queries:
                    injected_queries[id(encoder)] = np.asarray(encoder.embed_query(request.query), dtype=np.float32)
                query = injected_queries[id(encoder)]
            else:
                query = _query_vector(spec, request.query)
            channels.append(stored.search(query, view, profile.candidate_limit))
        merged: dict[EntityKey, Candidate] = {}
        for channel in channels:
            for rank, candidate in enumerate(channel, 1):
                entity = candidate.entity
                if entity not in merged:
                    merged[entity] = Candidate(entity, [], {"rrf": 0.0})
                combined = merged[entity]
                for name, value in candidate.signals.items():
                    combined.signals[name] = max(value, combined.signals.get(name, float("-inf")))
                combined.signals["rrf"] += 1 / (profile.rrf_k + rank)
                positions = {p.span: i for i, p in enumerate(combined.passages)}
                for p in candidate.passages:
                    if p.span in positions:
                        index = positions[p.span]
                        prior = combined.passages[index]
                        combined.passages[index] = replace(
                            prior, signals={**prior.signals, **p.signals})
                    else:
                        positions[p.span] = len(combined.passages)
                        combined.passages.append(p)
        result = sorted(merged.values(), key=lambda c: (
            -c.signals.get("exact", 0), -c.signals["rrf"], c.entity.path,
            min(p.span.start_line for p in c.passages)))[:profile.candidate_limit]
        for candidate in result:
            candidate.owned_regions = regions[candidate.entity]
        return result
