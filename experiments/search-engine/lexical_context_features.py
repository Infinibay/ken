"""Additional lexical source signals from a registered callable context catalog."""
from __future__ import annotations

from collections.abc import Callable, Sequence
import math

import numpy as np

from ken.retrieval.tokenization import code_terms
from lexical_context import LexicalContext

FIELDS = ('lexical_full', 'lexical_nested')
STATS = ('exact', 'stem', 'mean', 'min', 'p25', 'above50', 'above70', 'weighted',
         'mean_cosine', 'log_words')
FEATURES = (*(f'{field}_{stat}' for field in FIELDS for stat in STATS),
            'lexical_available', 'lexical_log_lines', 'lexical_log_nested_scopes',
            'lexical_log_nested_bytes', 'lexical_foreign_owner_fraction')
Coverage = Callable[[str, list[dict[str, list[str]]], tuple[str, ...]], list[dict[str, float]]]


def context_texts(context: LexicalContext) -> dict[str, str]:
    """Project literal source; joining scopes asserts neither execution nor order."""
    raw = context.text.encode('utf-8')
    if len(raw) != context.end_byte - context.start_byte:
        raise ValueError('lexical context bytes differ from their registered bounds')
    nested = []
    for scope in context.scopes:
        if scope.parent_index != 0:
            continue
        start, end = scope.start_byte-context.start_byte, scope.end_byte-context.start_byte
        if not 0 <= start <= end <= len(raw):
            raise ValueError('nested syntax leaves registered context bytes')
        nested.append(raw[start:end].decode('utf-8'))
    return {'lexical_full': context.text, 'lexical_nested': '\n'.join(nested)}


def lexical_context_features(query: str, contexts: Sequence[LexicalContext | None], *,
                             coverage: Coverage) -> np.ndarray:
    """Append25fixed summaries, reusing the existing encoder/coverage callback.

    The caller binds source catalog receipts/generations before using these
    inputs. No labels, case identifiers or resolved call edges are accepted.
    Candidate-local coverage includes empty documents for absent contexts;
    those rows are explicitly neutral, while all-absent batches need no encoder.
    """
    values = np.zeros((len(contexts), len(FEATURES)), dtype=np.float64)
    if not any(context is not None for context in contexts):
        return values
    documents = []
    for context in contexts:
        projected = context_texts(context) if context is not None else dict.fromkeys(FIELDS, '')
        fields = {name: code_terms(projected[name], limit=4096) for name in FIELDS}
        fields['all'] = list(dict.fromkeys(word for name in FIELDS for word in fields[name]))
        documents.append(fields)
    rows = coverage(query, documents, FIELDS)
    if len(rows) != len(contexts):
        raise ValueError('one lexical coverage row per candidate required')
    for index, context in enumerate(contexts):
        if context is None:
            continue
        values[index,:20] = [rows[index][field+'_'+stat] for field in FIELDS for stat in STATS]
        line_count = context.extent.end_line-context.extent.start_line+1
        foreign = sum(part.span.end_line-part.span.start_line+1 for part in context.parts
                      if part.owner is not None and part.owner != context.primary)
        nested_bytes = sum(scope.end_byte-scope.start_byte for scope in context.scopes
                           if scope.parent_index == 0)
        values[index,20:] = (1., math.log1p(line_count), math.log1p(len(context.scopes)-1),
                            math.log1p(nested_bytes), foreign/line_count)
    if not np.isfinite(values).all():
        raise ValueError('finite lexical coverage required')
    return values
