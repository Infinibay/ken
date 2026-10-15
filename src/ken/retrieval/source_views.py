"""Registered contributions of one owner, scored only after owner proposals."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ken.retrieval.description import OwnerDescription
from ken.retrieval.model import Candidate, EntityKey
from ken.retrieval.profile import EncoderSpec

SOURCE_VIEW_NAMES = ('contract', 'implementation')
SOURCE_VIEW_PROJECTION = 'own-contract-full-doc-empty-source-and-docless-owned-implementation-prefix512-v1'


def owner_view_texts(description: OwnerDescription) -> dict[str, str]:
    fields = description.fields
    header = [description.entity.path, fields['identity'], fields['signature']]
    return {
        'contract': '\n'.join([*header, 'Documentation: '+fields['documentation'], 'Source:', '']),
        'implementation': '\n'.join([*header, 'Documentation: ', 'Source:', fields['implementation']]),
    }


@dataclass(frozen=True)
class SourceViewSnapshot:
    """All owners share a deduplicated, optionally read-only mapped vector pool.

    The caller verifies the registered source-file and vector artifact hashes
    before constructing this snapshot. Mutable arrays are detached; read-only
    memmaps stay mapped, so scoring does not require another complete heap copy.
    """
    model: EncoderSpec
    generation: int
    owners: tuple[EntityKey, ...]
    source_hashes: tuple[str, ...]
    matrix: np.ndarray
    rows: Mapping[str, np.ndarray]
    query_model: EncoderSpec

    def __post_init__(self) -> None:
        if self.model == self.query_model:
            raise ValueError('separate source views require their distinct projection identity')
        if (self.generation < 0 or not self.owners or len(set(self.owners)) != len(self.owners)
                or len(self.source_hashes) != len(self.owners) or not all(self.source_hashes)):
            raise ValueError('source views require unique owners and source versions')
        versions: dict[str, str] = {}
        for owner, digest in zip(self.owners, self.source_hashes, strict=True):
            if versions.setdefault(owner.path, digest) != digest:
                raise ValueError('source views contain mixed source versions')
        mapped = (isinstance(self.matrix, np.memmap) and self.matrix.mode == 'r'
                  and self.matrix.dtype == np.float32 and not self.matrix.flags.writeable)
        matrix = self.matrix if mapped else np.array(self.matrix, dtype=np.float32, copy=True)
        if matrix.ndim != 2 or not matrix.size:
            raise ValueError('nonempty source view vectors required')
        for start in range(0, len(matrix), 4096):
            chunk = matrix[start:start+4096]
            if (not np.isfinite(chunk).all()
                    or not np.allclose(np.linalg.norm(chunk, axis=1), 1., atol=1e-5)):
                raise ValueError('source view vectors must be finite and normalized')
        if set(self.rows) != set(SOURCE_VIEW_NAMES):
            raise ValueError('both registered source views are required')
        rows = {}
        for name in SOURCE_VIEW_NAMES:
            indexes = np.asarray(self.rows[name])
            if (indexes.shape != (len(self.owners),) or indexes.dtype.kind not in 'iu'
                    or np.any(indexes < 0) or np.any(indexes >= len(matrix))):
                raise ValueError('source view rows must identify a vector for every owner')
            indexes = np.array(indexes, dtype=np.int64, copy=True)
            indexes.setflags(write=False)
            rows[name] = indexes
        matrix.setflags(write=False)
        object.__setattr__(self, 'matrix', matrix)
        object.__setattr__(self, 'rows', MappingProxyType(rows))

    def enrich(self, candidates: Sequence[Candidate], original: np.ndarray,
               expanded: np.ndarray) -> None:
        if not candidates:
            return
        lookup = {owner: i for i, owner in enumerate(self.owners)}
        indexes = [lookup[c.entity] for c in candidates]
        for name in SOURCE_VIEW_NAMES:
            # Gather only the combined proposal pool, preserving its order.
            vectors = self.matrix[self.rows[name][indexes]]
            a = vectors @ original
            b = a if expanded is original else vectors @ expanded
            for candidate, x, y in zip(candidates, a, b, strict=True):
                candidate.signals.update({f'cosine_view_{name}_original': float(x),
                                          f'cosine_view_{name}_expanded': float(y)})
