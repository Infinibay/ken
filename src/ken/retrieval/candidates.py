"""Union independent evidence sources, grouping by owner before applying budgets."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ken.retrieval.embedding_store import IndexVersionError, load_vectors, retrieval_snapshot
from ken.retrieval.dense import DenseView
from ken.retrieval.lexical import lexical_candidates
from ken.retrieval.intent import interpret
from ken.retrieval.indexing import source_policy_key
from ken.retrieval.model import Candidate, EntityKey, Passage, SearchRequest, merge_spans
from ken.retrieval.profile import Encoder, EncoderSpec, RetrievalProfile, active_profile, load_encoder
from ken.retrieval.storage import load_passage_map
from ken.retrieval.description import OwnerDescription, describe_owner
from ken.retrieval.contextual import ContextualRetriever
from ken.retrieval.proposals import fuse_proposals


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


@lru_cache(maxsize=4)
def _owner_snapshot(conn: sqlite3.Connection, generation: int) -> dict[EntityKey, tuple[Passage, ...]]:
    groups: dict[EntityKey, list[Passage]] = defaultdict(list)
    for passage in _passage_snapshot(conn, generation).values():
        groups[passage.entity].append(passage)
    return {entity: tuple(passages) for entity, passages in groups.items()}


def owner_passages(conn: sqlite3.Connection) -> Mapping[EntityKey, tuple[Passage, ...]]:
    """Complete source ownership in the current pinned generation, without copying bodies."""
    with retrieval_snapshot(conn) as snapshot:
        return MappingProxyType(_owner_snapshot(conn, snapshot.generation))


def owner_descriptions(conn: sqlite3.Connection, candidates: list[Candidate]) -> dict[EntityKey, OwnerDescription]:
    """Describe selected owners completely within the caller's source generation."""
    with retrieval_snapshot(conn) as snapshot:
        owners = _owner_snapshot(conn, snapshot.generation)
        if any(c.entity not in owners or not c.passages for c in candidates):
            raise IndexVersionError('owner changed before ranking; retry retrieval')
        result = {c.entity: describe_owner(owners[c.entity]) for c in candidates}
        if any(result[c.entity].source_hash != c.passages[0].source_hash for c in candidates):
            raise IndexVersionError('source changed before owner ranking; retry retrieval')
        return result


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


def retrieve_contextual(conn: sqlite3.Connection, root: Path, request: SearchRequest,
                        profile: RetrievalProfile, *, runtime: ContextualRetriever | None,
                        expand_query: Callable[[str], str] | None,
                        encoders: Mapping[str, Encoder] | None = None
                        ) -> tuple[list[Candidate], str]:
    policy = profile.contextual
    if policy is None:
        raise ValueError('contextual retrieval requires its pinned source policy')
    source_profile = replace(profile, candidate_limit=policy.channel_limit)
    with retrieval_snapshot(conn) as snapshot:
        original = retrieve(conn, root, request, source_profile, encoders=encoders)
        if len(original) == 1 and original[0].signals.get('exact'):
            return original, request.query
        if runtime is None or expand_query is None:
            raise ValueError('contextual profile requires its pinned retriever and query preparation')
        expanded = expand_query(request.query)
        if not isinstance(expanded, str) or not expanded.strip():
            raise ValueError('contextual expansion must return nonempty query text')
        runs = {'original': original}
        if expanded != request.query:
            translated = retrieve(conn, root, replace(request, query=expanded), source_profile,
                                  encoders=encoders)
            runs['expanded'] = [replace(c, signals={k: v for k, v in c.signals.items() if k != 'exact'})
                                for c in translated]
        static = fuse_proposals(runs, limit=2*policy.channel_limit, rrf_k=profile.rrf_k)
        exact = _exact(conn, _passage_snapshot(conn, snapshot.generation), request)
        regions = _region_snapshot(conn, snapshot.generation)
        for candidate in exact:
            candidate.owned_regions = regions[candidate.entity]
        owners = _owner_snapshot(conn, snapshot.generation)
        contextual = runtime.score(request.query, expanded, owners,
                                   generation=snapshot.generation, policy=policy)
        combined = fuse_proposals({
            'static': [replace(c, signals={k: v for k, v in c.signals.items() if k != 'exact'})
                       for c in static],
            'code': contextual.propose(owners, limit=policy.channel_limit), 'exact': exact},
            limit=policy.broad_limit, rrf_k=profile.rrf_k)
        contextual.enrich(combined)
        return combined, expanded
