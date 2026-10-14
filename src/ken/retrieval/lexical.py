"""Incremental fielded lexical retrieval over the same source passages as dense views."""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from functools import lru_cache

import numpy as np

from ken.retrieval.embedding_store import retrieval_snapshot

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



def score_postings(rows: Sequence[tuple[int, str, str, int, int]], *, documents: int,
                   averages: Mapping[str, float]) -> dict[int, dict[str, float]]:
    """BM25F over matching postings only, saturating shared terms across fields once."""
    if not rows:
        return {}
    field_index = {field:i for i,field in enumerate(FIELDS)}
    terms = {term:i for i,term in enumerate(dict.fromkeys(row[2] for row in rows))}
    values = np.fromiter(((pid, field_index[field], terms[term], tf, length)
        for pid,field,term,tf,length in rows), dtype=np.dtype([
            ('pid','i8'), ('field','i4'), ('term','i4'), ('tf','f8'), ('length','f8')]), count=len(rows))
    ids, local = np.unique(values['pid'], return_inverse=True)
    fields, term_ids = values['field'], values['term']
    avg = np.array([averages.get(f, 0.) for f in FIELDS])
    length_normalized = np.isin(fields, [field_index['body'], field_index['documentation']]) & (avg[fields] > 0)
    norm = np.ones(len(rows))
    norm[length_normalized] = .25 + .75 * values['length'][length_normalized] / avg[fields[length_normalized]]
    tf = values['tf'] / norm
    # A passage contributes once to df even if a term occurs in several fields.
    combined = np.bincount(local * len(terms) + term_ids, weights=tf,
                           minlength=len(ids)*len(terms)).reshape(len(ids), len(terms))
    df = np.count_nonzero(combined, axis=0)
    idf = np.log1p((documents-df+.5)/(df+.5))
    total = (idf * 2.2 * combined / (1.2+combined)).sum(axis=1)
    individual = np.bincount(local*len(FIELDS)+fields,
        weights=idf[term_ids]*2.2*tf/(1.2+tf), minlength=len(ids)*len(FIELDS)).reshape(len(ids),len(FIELDS))
    return {int(pid): {'bm25f':float(total[i]), **{f'bm25_{field}':float(individual[i,j])
            for j,field in enumerate(FIELDS)}} for i,pid in enumerate(ids)}


@lru_cache(maxsize=4)
def _corpus_stats(conn: sqlite3.Connection, generation: int, own_changes: int):
    # Generation pins committed writers; total_changes also separates a caller's
    # own rolled-back edits from a later transaction reusing the same generation.
    documents = int(conn.execute('SELECT COUNT(*) FROM ci_passages').fetchone()[0])
    averages = {r[0]:float(r[1]) for r in conn.execute(
        'SELECT field,AVG(length) FROM ci_passage_lengths GROUP BY field')}
    return documents, averages


def lexical_candidates(conn: sqlite3.Connection, request: SearchRequest,
                       limit: int = 100) -> list[Candidate]:
    with retrieval_snapshot(conn) as snapshot:
        return _lexical_candidates(conn, request, limit, snapshot.generation)


def _lexical_candidates(conn: sqlite3.Connection, request: SearchRequest,
                        limit: int, generation: int) -> list[Candidate]:
    terms = list(dict.fromkeys(code_tokens(request.query)))[:128]
    if not terms:
        return []
    placeholders = ','.join('?' for _ in terms)
    cursor = conn.cursor()
    cursor.row_factory = None
    rows = cursor.execute(
        'SELECT t.passage_id,t.field,t.term,t.tf,l.length,p.file_id,p.symbol_id '
        'FROM ci_passage_terms t JOIN ci_passages p ON p.id=t.passage_id '
        'JOIN ci_passage_lengths l ON l.passage_id=t.passage_id AND l.field=t.field '
        'WHERE t.term IN ('+placeholders+')', terms).fetchall()
    if not rows:
        return []
    documents, averages = _corpus_stats(conn, generation, conn.total_changes)
    scores = score_postings([row[:5] for row in rows], documents=documents, averages=averages)
    groups_by_pid = {row[0]:(row[5],row[6]) for row in rows}
    grouped: dict[tuple[int,int|None], list[int]] = defaultdict(list)
    for pid in sorted(scores, key=lambda p:(-scores[p]['bm25f'],p)):
        grouped[groups_by_pid[pid]].append(pid)
    selected = list(grouped.values())[:max(1,limit)]
    passages = load_passage_map(conn, [pid for group in selected for pid in group[:4]])
    out = []
    for group in selected:
        owned = [passages[pid] for pid in group[:4]]
        features = {name:max(scores[pid][name] for pid in group) for name in scores[group[0]]}
        out.append(Candidate(owned[0].entity,owned,features))
    return out
