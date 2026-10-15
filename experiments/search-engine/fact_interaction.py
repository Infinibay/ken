"""Transparent query text clauses and source-fact cosine interaction for research."""
from __future__ import annotations
import math
import re
from collections.abc import Sequence
import numpy as np

FACT_KINDS = ('conditions', 'guarded_effects', 'value_relations', 'assertions', 'call_relations')
FACT_FIELDS = (*FACT_KINDS, 'all')
METRICS = ('original_max', 'expanded_max', 'required_min', 'required_mean', 'alternative_max')
FACT_FEATURES = (*(f'fact_{field}_{metric}' for field in FACT_FIELDS for metric in METRICS),
                 'fact_log_count', 'fact_query_alternative')
_QUOTES = re.compile(r'''"(?:\\.|[^"\\])*"|(?<!\w)'(?:\\.|[^'\\])*'(?!\w)|`(?:\\.|[^`\\])*`''')
_BOUNDARY = re.compile(r'(?<![\w.$])(?:instead\s+of|rather\s+than|and|while|when|before|after|but|without)(?![\w.$])|[,;]', re.IGNORECASE)


def query_clauses(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    masked = _QUOTES.sub(lambda match: '_'*len(match.group()), text)
    required: list[str] = []
    avoided: list[str] = []
    position, alternative, prefix = 0, False, ''
    for boundary in [*_BOUNDARY.finditer(masked), None]:
        fragment = text[position:boundary.start() if boundary else len(text)].strip()
        if fragment:
            (avoided if alternative else required).append(prefix+fragment)
        if boundary is None:
            break
        marker = boundary.group().lower()
        if marker in {',', ';', 'but'}:
            alternative = False
        elif marker.startswith(('instead', 'rather')):
            alternative = True
        prefix = marker+' ' if marker in {'while', 'when', 'before', 'after', 'without'} else ''
        position = boundary.end()
    return tuple(required), tuple(avoided)


def fact_features(original: np.ndarray, expanded: np.ndarray, required: np.ndarray,
                  avoided: np.ndarray, facts: np.ndarray, kinds: Sequence[str]) -> np.ndarray:
    original, expanded, required, avoided, facts = [np.asarray(v, dtype=np.float32)
        for v in (original, expanded, required, avoided, facts)]
    if (original.ndim != 1 or not len(original) or expanded.shape != original.shape
            or any(v.ndim != 2 or v.shape[1] != len(original) for v in (required, avoided, facts))
            or len(facts) != len(kinds) or any(k not in FACT_KINDS for k in kinds)
            or any(not np.isfinite(v).all() for v in (original, expanded, required, avoided, facts))):
        raise ValueError('compatible finite query/fact vectors and known source kinds required')
    kinds_array = np.asarray(kinds)
    result: list[float] = []
    for field in FACT_FIELDS:
        vectors = facts if field == 'all' else facts[kinds_array == field]
        if not len(vectors):
            result.extend([0.]*5)
            continue
        matches = (required@vectors.T).max(axis=1) if len(required) else None
        result.extend([float((vectors@original).max()), float((vectors@expanded).max()),
            float(matches.min()) if matches is not None else 0.,
            float(matches.mean()) if matches is not None else 0.,
            float((avoided@vectors.T).max()) if len(avoided) else 0.])
    result.extend([math.log1p(len(facts)), float(bool(len(avoided)))])
    return np.asarray(result)
