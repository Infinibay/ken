"""Two independently useful source contributions of one canonical owner."""
from ken.retrieval.description import OwnerDescription

VIEW_NAMES = ('contract', 'implementation')
VIEW_PROJECTION = 'own-contract-full-doc-empty-source-and-docless-owned-implementation-prefix512-v1'


def owner_views(description: OwnerDescription) -> dict[str, str]:
    fields = description.fields
    header = [description.entity.path, fields['identity'], fields['signature']]
    return {
        'contract': '\n'.join([*header, 'Documentation: '+fields['documentation'], 'Source:', '']),
        'implementation': '\n'.join([*header, 'Documentation: ', 'Source:', fields['implementation']]),
    }
