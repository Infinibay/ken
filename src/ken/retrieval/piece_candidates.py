"""Build requested units directly from ranked owners, without diagnostic traces."""
from __future__ import annotations

from collections.abc import MutableMapping, Sequence

from ken.retrieval.description import OwnerDescription, describe_owner
from ken.retrieval.model import CodeMatch, EntityKey
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.piece_ranking import PieceCandidate


def assemble_pieces(matches: Sequence[CodeMatch], kind: str, catalog: SourceCatalog,
                    descriptions: MutableMapping[EntityKey, OwnerDescription], *,
                    limit: int = 10) -> list[PieceCandidate]:
    """Preserve native piece proposals; describe their complete source membership.

    The caller's generation-bound cache shares descriptions across queries. A
    member's owner score is evidence for its piece, never the piece's identity.
    """
    if limit <= 0:
        raise ValueError('positive piece candidate limit required')
    groups: dict[EntityKey | str, list[CodeMatch]] = {}
    for match in matches:
        primary = catalog.primary(match.entity, kind)
        if primary is not None:
            groups.setdefault(primary, []).append(match)
    result = []
    for primary, supporting in list(groups.items())[:limit]:
        path = primary.path if isinstance(primary, EntityKey) else primary
        entity = primary if isinstance(primary, EntityKey) else None
        if kind == 'class':
            keys = [k for k in catalog.by_path[path] if k == entity or catalog.classes.get(k) == entity]
        elif kind == 'symbol':
            assert entity is not None
            keys = [entity]
        else:
            keys = catalog.by_path[path]
        for key in keys:
            if key not in descriptions:
                descriptions[key] = describe_owner(catalog.owners[key])
        # Use complete canonical passages, as in the measured source projection.
        evidence = tuple(CodeMatch(m.entity, m.score, list(catalog.owners[m.entity]),
                                   m.source_hash, m.signals, m.owned_regions)
                         for m in sorted(supporting, key=lambda m: -m.score))
        result.append(PieceCandidate(kind, path, entity,
                                     tuple(descriptions[k] for k in keys), evidence))
    return result
