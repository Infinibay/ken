"""Project observed owner order into canonical requested pieces, without Gold."""
from ken.retrieval.model import EntityKey
from verifiable_pieces import canonical, module_name


def piece_order(owners, target_kind, catalog):
    grouped = {}
    for owner in sorted(owners, key=lambda row: row['rank']):
        key = EntityKey(path=owner['path'], **owner['entity'])
        primary = catalog.primary(key, target_kind)
        if primary is None:
            continue
        path = primary.path if isinstance(primary, EntityKey) else primary
        unit = {'target_kind': target_kind, 'path': path,
                'entity': primary.to_dict() if isinstance(primary, EntityKey) else None,
                'module_name': module_name(path) if target_kind == 'module' else None}
        identity = canonical(unit)
        if identity not in grouped:
            grouped[identity] = {'rank': len(grouped) + 1, 'unit': unit,
                                 'representative_proposal_index': owner['proposal_index'],
                                 'representative_owner_rank': owner['rank'], 'score': owner['score'],
                                 'owner_proposal_indices': []}
        grouped[identity]['owner_proposal_indices'].append(owner['proposal_index'])
    return list(grouped.values())
