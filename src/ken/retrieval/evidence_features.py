"""Turn query, retrieval signals and owned source views into ranking evidence."""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from ken.retrieval.alignment import TermAlignment
from ken.retrieval.description import OwnerDescription
from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, EntityKey, SearchRequest
from ken.retrieval.profile import Encoder
from ken.retrieval.tokenization import code_terms, code_tokens

FEATURE_VERSION = 1
_TERM_BLOCK_SIZE = 4096
BASE_FEATURES = ('rrf', 'cosine_identity', 'cosine_behavior', 'bm25f', 'bm25_body',
    'bm25_documentation', 'bm25_identity', 'bm25_signature', 'bm25_path', 'role_match',
    'class', 'module', 'log_lines', 'name_overlap', 'body_overlap')
_RAW_FIELDS = ('identity', 'signature', 'documentation', 'body', 'path', 'all')
_SOURCE_FIELDS = ('identity', 'signature', 'documentation', 'implementation', 'executable',
                  'comments', 'calls', 'returns', 'path', 'all')
_STATS = ('exact', 'mean', 'min', 'p25', 'above50', 'above70', 'weighted', 'mean_cosine', 'log_words')
_EXPANDED_STATS = ('exact', 'stem', *_STATS[1:])
_KINDS = ('function', 'method', 'class', 'struct', 'interface', 'enum', 'trait', 'type',
          'module', 'constant', 'property', 'variable', 'constructor')
_OPERATIONS = ('return', 'raise', 'throw', 'panic', 'if', 'else', 'try', 'catch', 'except',
               'for', 'while', 'match', 'switch', 'await', 'yield')
_SHAPE = ('log_executable_lines', 'log_comment_lines', 'log_owned_lines', 'log_regions',
          'documentation_fraction', 'query_negation', 'query_test')
FEATURES = (*BASE_FEATURES, 'is_exception', 'is_constructor', 'query_log_tokens',
    'query_identifier', 'query_kind_class',
    *(f'{f}_{s}' for f in _RAW_FIELDS for s in _STATS),
    *(f'{n}_{t}' for n in BASE_FEATURES[:9] for t in ('relative', 'rank')),
    *(f'expanded_{f}_{s}' for f in _SOURCE_FIELDS for s in _EXPANDED_STATS),
    *(f'expanded_kind_{k}' for k in _KINDS), *(f'expanded_{k}' for k in _SHAPE),
    *(f'expanded_op_{k}' for k in _OPERATIONS))


@dataclass(frozen=True)
class FeatureMatrix:
    names: tuple[str, ...]
    values: np.ndarray


def base_features(request: SearchRequest, candidate: Candidate) -> dict[str, float]:
    """Preserve measured channel evidence, including explicit missing-channel zeros."""
    features = {name: float(candidate.signals.get(name, 0)) for name in BASE_FEATURES[:9]}
    for name in BASE_FEATURES[3:9]:
        features[name] = math.log1p(max(0, features[name]))
    intent = interpret(request)
    expected = {'implementation': 'definition', 'tests': 'test', 'usage': 'example',
                'documentation': 'documentation'}[intent.purpose]
    query = set(code_tokens(request.query))
    features.update(role_match=float(candidate.passages[0].role == expected),
        **{'class': float(candidate.entity.kind == 'class'),
           'module': float(candidate.entity.qualname is None)},
        log_lines=math.log1p(max(p.entity_span.end_line-p.entity_span.start_line+1
                                for p in candidate.passages)),
        name_overlap=len(query & set(code_tokens(candidate.entity.qualname or ''))) / max(1, len(query)),
        body_overlap=max(len(query & set(code_tokens(p.fields['body']))) / max(1, len(query))
                         for p in candidate.passages))
    return features


def _coverage(query: str, documents: list[dict[str, list[str]]], fields: Sequence[str], *,
              encoder: Encoder, stem_words: Callable[[list[str]], list[str]] | None = None
              ) -> list[dict[str, float]]:
    words = code_terms(query, limit=128)
    vocabulary = sorted(set(words) | {w for d in documents for ws in d.values() for w in ws})
    lookup = {word: i for i, word in enumerate(vocabulary)}
    all_words = [set(d['all']) for d in documents]
    weights = np.array([math.log1p(len(documents)/(1+sum(w in d for d in all_words))) for w in words])
    sentence = np.asarray(encoder.embed_query(query), dtype=np.float32)
    query_vectors = (np.asarray(encoder.embed_passages(words), dtype=np.float32) if words
                     else np.empty((0, len(sentence)), dtype=np.float32))
    alignment = TermAlignment(query_vectors, weights)
    # Memory depends on a vector block and field summaries, never on the
    # product of the whole candidate vocabulary and the query length.
    memberships = [np.asarray(sorted(lookup[w] for w in d[f]), dtype=np.int64)
                   for d in documents for f in fields]
    sums = np.zeros((len(memberships), len(sentence)), dtype=np.float64)
    peaks = np.full((len(memberships), len(words)), -np.inf, dtype=np.float32)
    for offset in range(0, len(vocabulary), _TERM_BLOCK_SIZE):
        block = vocabulary[offset:offset+_TERM_BLOCK_SIZE]
        vectors = np.asarray(encoder.embed_passages(block), dtype=np.float32)
        similarities = alignment.similarities(vectors)
        for index, ids in enumerate(memberships):
            lower, upper = np.searchsorted(ids, (offset, offset+len(block)))
            local = ids[lower:upper]-offset
            if len(local):
                sums[index] += vectors[local].sum(axis=0, dtype=np.float64)
                peaks[index] = np.maximum(peaks[index], similarities[:, local].max(axis=1))
    stems = dict(zip(vocabulary, stem_words(vocabulary), strict=True)) if stem_words else {}
    query_stems = {stems[w] for w in words} if stems else set()
    coverage_by_field = alignment.summarize_maxima(peaks,
        present=np.asarray([bool(len(ids)) for ids in memberships], dtype=bool))
    rows = []
    for document_index, document in enumerate(documents):
        row: dict[str, float] = {}
        for field_index, field in enumerate(fields):
            terms = document[field]
            index = document_index * len(fields) + field_index
            coverage = coverage_by_field[index]
            mean = sums[index]/len(terms) if terms else np.zeros(len(sentence))
            norm = np.linalg.norm(mean)
            values = (len(set(words) & set(terms))/max(1, len(words)), coverage.mean,
                coverage.minimum, coverage.quartile, coverage.above50, coverage.above70,
                coverage.weighted, float(sentence @ mean/norm) if norm else 0., math.log1p(len(terms)))
            row.update(zip((f'{field}_{s}' for s in _STATS), values, strict=True))
            if stems:
                row[field+'_stem'] = len(query_stems & {stems[w] for w in terms})/max(1, len(query_stems))
        rows.append(row)
    return rows


def evidence_features(request: SearchRequest, candidates: Sequence[Candidate],
                      descriptions: Mapping[EntityKey, OwnerDescription], *, encoder: Encoder,
                      stem_words: Callable[[list[str]], list[str]],
                      expanded_query: str | None = None) -> FeatureMatrix:
    """Public query inputs only; training labels and case identifiers have no role."""
    if not candidates:
        return FeatureMatrix(FEATURES, np.empty((0, len(FEATURES))))
    owners: list[OwnerDescription] = [descriptions[c.entity] for c in candidates]
    if any(d.source_hash != c.passages[0].source_hash for c, d in zip(candidates, owners, strict=True)):
        raise ValueError('ranking description source is stale')
    raw_documents = []
    source_documents = []
    for owner in owners:
        raw = {f: code_terms(owner.fields[f], limit=4096) for f in _RAW_FIELDS[:-1]}
        raw['all'] = list(dict.fromkeys(w for f in _RAW_FIELDS[:-1] for w in raw[f]))
        raw_documents.append(raw)
        # Keep the original projection order explicit: limits cannot depend on
        # dictionary insertion order or duplicate documentation in raw bodies.
        source = {f: owner.fields[f] for f in ('identity', 'signature', 'documentation', 'path',
                  'implementation', 'comments', 'executable', 'calls', 'returns')}
        source['all'] = '\n'.join(source.values())
        source_documents.append({f: code_terms(source[f], limit=4096)
                                 for f in _SOURCE_FIELDS})
    raw_coverage = _coverage(request.query, raw_documents, _RAW_FIELDS, encoder=encoder)
    expanded = expanded_query if expanded_query is not None else request.query
    source_coverage = _coverage(expanded, source_documents, _SOURCE_FIELDS, encoder=encoder, stem_words=stem_words)
    intent = interpret(request)
    query_count = len(set(code_tokens(request.query)))
    expanded_intent = interpret(replace(request, query=expanded))
    rows = []
    for candidate, owner, raw_stats, source_stats in zip(candidates, owners, raw_coverage, source_coverage, strict=True):
        row = base_features(request, candidate)
        name = (candidate.entity.qualname or '').lower().split('.')[-1]
        row.update(is_exception=float(any(x in name for x in ('exception', 'error'))),
            is_constructor=float(name in ('__init__', 'new', 'constructor')),
            query_log_tokens=math.log1p(query_count), query_identifier=float(intent.identity),
            query_kind_class=float(intent.kind == 'class'))
        row.update(raw_stats)
        row.update({'expanded_'+n: value for n, value in source_stats.items()})
        row.update({'expanded_kind_'+kind: float(candidate.entity.kind == kind) for kind in _KINDS})
        row.update(expanded_log_executable_lines=math.log1p(owner.executable_lines),
            expanded_log_comment_lines=math.log1p(owner.comment_lines),
            expanded_log_owned_lines=math.log1p(owner.owned_lines), expanded_log_regions=math.log1p(owner.regions),
            expanded_documentation_fraction=1-owner.implementation_lines/max(1, owner.owned_lines),
            expanded_query_negation=float(bool(re.search(r'\b(?:not|without|never|no|sin)\b', expanded.casefold()))),
            expanded_query_test=float(expanded_intent.purpose == 'tests'))
        operations = Counter(re.findall(r'\b\w+\b', owner.fields['executable']))
        row.update({'expanded_op_'+kind: math.log1p(operations[kind]) for kind in _OPERATIONS})
        rows.append(row)
    for name in BASE_FEATURES[:9]:
        values = np.array([r[name] for r in rows])
        order = np.argsort(-values, kind='stable')
        ranks = np.empty(len(rows)); ranks[order] = np.arange(1, len(rows)+1)
        for i, row in enumerate(rows):
            row[name+'_relative'] = (values[i]-values.min())/max(1e-9, float(np.ptp(values)))
            row[name+'_rank'] = 1./ranks[i]
    matrix = np.array([[r[name] for name in FEATURES] for r in rows])
    if not np.isfinite(matrix).all():
        raise ValueError('ranking features must be finite')
    return FeatureMatrix(FEATURES, matrix)
