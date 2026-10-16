"""Score a requested code unit from its declaration and member evidence."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import math
from pathlib import PurePosixPath

import numpy as np

from ken.retrieval.description import OwnerDescription
from ken.retrieval.evidence_features import FeatureMatrix, _coverage, _STATS, _EXPANDED_STATS
from ken.retrieval.intent import interpret, requested_piece_kind, requested_piece_path
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.profile import Encoder
from ken.retrieval.tokenization import code_terms

_FIELDS = ('identity', 'signature', 'documentation', 'executable', 'calls', 'returns', 'path', 'all')
_KINDS = ('class', 'module', 'symbol', 'file')
_DECLARATIONS = ('class', 'interface', 'enum', 'type', 'function', 'method', 'module', 'constant')
_SCALARS = ('native_score', 'native_to_best', 'native_rank', 'member_log_count',
            'matched_log_count', 'matched_fraction', 'member_score_mean3', 'member_score_gap',
            'declaration_present', 'declaration_in_matches', 'declaration_score_to_best',
            'log_owned_lines', 'log_executable_lines', 'documentation_fraction',
            'test_path', 'data_file', 'request_tests', 'request_documentation')
PIECE_FEATURES = (*_SCALARS, *(f'request_{k}' for k in _KINDS),
    *(f'declaration_kind_{k}' for k in _DECLARATIONS),
    *(f'original_{f}_{s}' for f in _FIELDS for s in _STATS),
    *(f'piece_{f}_{s}' for f in _FIELDS for s in _EXPANDED_STATS),
    *(f'declaration_{f}_{s}' for f in _FIELDS for s in _EXPANDED_STATS))


@dataclass(frozen=True)
class PieceCandidate:
    kind: str
    path: str
    entity: EntityKey | None
    members: tuple[OwnerDescription, ...]
    matches: tuple[CodeMatch, ...]

    def __post_init__(self) -> None:
        if self.kind not in _KINDS or not self.members or not self.matches:
            raise ValueError('requested piece requires members and retrieved evidence')
        if (self.kind in {'class', 'symbol'}) != (self.entity is not None):
            raise ValueError('requested piece identity disagrees with its kind')
        keys = {m.entity for m in self.members}
        if len(keys) != len(self.members) or any(m.entity.path != self.path for m in self.members):
            raise ValueError('piece member identity differs')
        if len({m.source_hash for m in self.members}) != 1:
            raise ValueError('piece member source versions differ')
        if self.entity is not None:
            if self.entity not in keys or any(k != self.entity and (self.kind != 'class'
                    or not (k.qualname or '').startswith((self.entity.qualname or '') + '.')) for k in keys):
                raise ValueError('piece member lies outside requested entity')
        if any(m.entity not in keys or m.source_hash != self.members[0].source_hash for m in self.matches):
            raise ValueError('retrieved member is outside the piece source')

    @property
    def declaration(self) -> OwnerDescription | None:
        return next((m for m in self.members if m.entity == self.entity
                     or self.entity is None and m.entity.qualname is None), None)


def _document(members: Sequence[OwnerDescription], *, identity: str = '') -> dict[str, list[str]]:
    fields = {field: '\n'.join(dict.fromkeys(m.fields.get(field, '') for m in members))
              for field in _FIELDS[:-1]}
    fields['identity'] = identity + '\n' + fields['identity']
    fields['all'] = '\n'.join(fields.values())
    return {field: code_terms(text, limit=4096) for field, text in fields.items()}


def piece_features(request: SearchRequest, pieces: Sequence[PieceCandidate], *,
                   encoder: Encoder, stem_words: Callable[[list[str]], list[str]],
                   expanded_query: str | None = None) -> FeatureMatrix:
    """Describe units directly; native owner score remains one bounded prior."""
    kind = requested_piece_kind(request)
    purpose = interpret(request).purpose
    if any(piece.kind != kind for piece in pieces):
        raise ValueError('piece candidates differ from requested kind')
    if not pieces:
        return FeatureMatrix(PIECE_FEATURES, np.empty((0, len(PIECE_FEATURES))))
    documents = [_document(p.members, identity=p.path + '\n' + (p.entity.qualname or '' if p.entity else ''))
                 for p in pieces]
    declarations = [_document((p.declaration,) if p.declaration else ()) for p in pieces]
    expanded = expanded_query or request.query
    original = _coverage(request.query, documents, _FIELDS, encoder=encoder)
    whole = _coverage(expanded, documents, _FIELDS, encoder=encoder, stem_words=stem_words)
    direct = _coverage(expanded, declarations, _FIELDS, encoder=encoder, stem_words=stem_words)
    best_score = pieces[0].matches[0].score
    rows = []
    for rank, (piece, raw, all_fields, declaration) in enumerate(zip(pieces, original, whole, direct, strict=True), 1):
        ordered = sorted(piece.matches, key=lambda m: -m.score)
        top = ordered[:3]
        root = piece.declaration
        root_match = next((m for m in ordered if root and m.entity == root.entity), None)
        owned = sum(m.owned_lines for m in piece.members)
        executable = sum(m.executable_lines for m in piece.members)
        parts = PurePosixPath(piece.path).parts
        row = dict(native_score=ordered[0].score, native_to_best=ordered[0].score - best_score,
            native_rank=1./rank, member_log_count=math.log1p(len(piece.members)),
            matched_log_count=math.log1p(len(ordered)), matched_fraction=len(ordered)/len(piece.members),
            member_score_mean3=sum(m.score for m in top)/len(top),
            member_score_gap=ordered[0].score - (ordered[1].score if len(ordered)>1 else ordered[0].score),
            declaration_present=float(root is not None), declaration_in_matches=float(root_match is not None),
            declaration_score_to_best=root_match.score-ordered[0].score if root_match else 0.,
            log_owned_lines=math.log1p(owned), log_executable_lines=math.log1p(executable),
            documentation_fraction=1-executable/max(1, owned),
            test_path=float(any(p in {'test', 'tests', 'typing_tests', 'platform-tests', 'spec', 'specs'} for p in parts)),
            data_file=float(PurePosixPath(piece.path).suffix in {'.json', '.yaml', '.yml', '.toml'}),
            request_tests=float(purpose=='tests'), request_documentation=float(purpose=='documentation'))
        row.update({f'request_{k}': float(kind==k) for k in _KINDS})
        row.update({f'declaration_kind_{k}': float(root is not None and root.entity.kind==k) for k in _DECLARATIONS})
        row.update({'original_'+name: value for name,value in raw.items()})
        row.update({'piece_'+name: value for name,value in all_fields.items()})
        row.update({'declaration_'+name: value for name,value in declaration.items()})
        rows.append([row[name] for name in PIECE_FEATURES])
    return FeatureMatrix(PIECE_FEATURES, np.asarray(rows, dtype=np.float64))


@dataclass(frozen=True)
class PieceMatch:
    piece: PieceCandidate
    score: float


class PieceReranker:
    def __init__(self, model: NumericRanker, encoder: Encoder, *,
                 stem_words: Callable[[list[str]], list[str]]):
        if model.features != PIECE_FEATURES:
            raise ValueError('piece model uses an incompatible feature schema')
        self.model, self.encoder, self.stem_words = model, encoder, stem_words

    def rank(self, request: SearchRequest, pieces: Sequence[PieceCandidate], *,
             expanded_query: str | None = None) -> list[PieceMatch]:
        if requested_piece_kind(request) == 'symbol':
            return [PieceMatch(piece, piece.matches[0].score) for piece in pieces]
        features = piece_features(request, pieces, encoder=self.encoder, stem_words=self.stem_words,
                                  expanded_query=expanded_query)
        scores = self.model.predict(features.values)
        named_path = requested_piece_path(request)
        return sorted((PieceMatch(piece, float(score)) for piece,score in zip(pieces,scores,strict=True)),
                      key=lambda m: (-float(named_path is not None and m.piece.path==named_path),
                                     -max(match.signals.get('exact',0) for match in m.piece.matches),
                                     -m.score))
