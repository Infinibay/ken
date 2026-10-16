"""Adapt a closed native owner order to source-authenticated requested units."""
from ken.retrieval.description import describe_owner
from ken.retrieval.model import CodeMatch, EntityKey
from ken.retrieval.piece_ranking import PieceCandidate


def candidates_from_trace(data, catalog, cache, *, limit=10):
    result = []
    for piece in data['pieces'][:limit]:
        unit = piece['unit']; kind = unit['target_kind']; path = unit['path']
        primary = EntityKey(path=path, **unit['entity']) if unit['entity'] else None
        if kind == 'class':
            keys = [k for k in catalog.by_path[path] if k == primary or catalog.classes.get(k) == primary]
        elif kind == 'symbol':
            keys = [primary]
        else:
            keys = catalog.by_path[path]
        for key in keys:
            if key not in cache:
                cache[key] = describe_owner(catalog.owners[key])
        members = tuple(cache[k] for k in keys)
        matches = []
        for index in piece['owner_proposal_indices']:
            owner = data['owners'][index]
            key = EntityKey(path=owner['path'], **owner['entity'])
            matches.append(CodeMatch(key, owner['score'], list(catalog.owners[key]),
                                     owner['source_hash'], owner['signals']))
        matches.sort(key=lambda m: -m.score)
        result.append(PieceCandidate(kind, path, primary, members, tuple(matches)))
    return result
