"""Resolve native search identities without adding evidence or changing order."""
from collections import defaultdict


def native_units(native, target_kind, inventory):
    """Unknown/wrong-kind results occupy their original rank as misses.

    The complete pre-query source catalog disambiguates duplicate definitions.
    It never supplies a missing candidate or changes a native symbol's owner.
    """
    by_name=defaultdict(list)
    for row in inventory:
        by_name[(row['path'],row['entity']['kind'],row['entity']['qualname'])].append(row)
    result=[]
    for item in native:
        if target_kind in {'file','module'}:
            result.append({'unit':{'target_kind':target_kind,'path':item['path']}})
            continue
        allowed={'class'} if target_kind=='class' else {'function','method','const','constant'}
        if item.get('kind') not in allowed:
            result.append(None);continue
        matches=by_name[(item.get('file'),item.get('kind'),item.get('qualname'))]
        if len(matches)>1:
            line=item.get('line')
            matches=[r for r in matches if isinstance(line,int) and
                     r['extent'][0]<=line<=r['extent'][1]]
        if len(matches)!=1:
            result.append(None);continue
        row=matches[0]
        result.append({'unit':{'target_kind':target_kind,'path':row['path'],
                               'entity':row['entity']}})
    return result
