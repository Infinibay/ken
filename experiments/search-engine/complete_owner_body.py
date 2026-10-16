"""Complete a symbol's owned implementation only when existing budgets permit."""
from copy import deepcopy

from ken.retrieval.model import EntityKey
from ken.retrieval.piece_cards import MAX_CHARS, MAX_EXCERPTS, MAX_LINES, canonical, validate_card


def complete_owner_body(card, catalog):
    """Retain existing evidence and add all owned code, or return the exact card.

    This is an all-or-original projection. It never borrows lexical child code,
    changes the primary identity, chooses a new window or expands a budget.
    """
    unit = card['unit']
    if unit['target_kind'] != 'symbol' or not unit['entity']:
        return card
    key = EntityKey(path=unit['path'], **unit['entity'])
    ranges = catalog.owned_ranges(key, implementation=True)
    if sum(b - a + 1 for a, b in ranges) > MAX_LINES:
        return card
    owned = {n for a, b in ranges for n in range(a, b + 1)}
    old_lines = {n for e in card['excerpts'] for n in range(e['start_line'], e['end_line'] + 1)}
    if owned <= old_lines:
        return card
    fixed = [e for e in card['excerpts'] if e['role'] != 'implementation']
    fixed_lines = {n for e in fixed for n in range(e['start_line'], e['end_line'] + 1)}
    combined = fixed_lines | owned
    if len(combined) > MAX_LINES or not old_lines <= combined:
        return card
    runs = []
    for line in sorted(owned - fixed_lines):
        if runs and runs[-1][1] + 1 == line:
            runs[-1][1] = line
        else:
            runs.append([line, line])
    if len(fixed) + len(runs) > MAX_EXCERPTS:
        return card
    implementation = [{'role': 'implementation', 'path': key.path,
        'start_line': a, 'end_line': b, 'source_hash': catalog.hashes[key.path],
        'entity': key.to_dict(), 'content': '\n'.join(catalog.lines[key.path][a-1:b])}
        for a, b in runs]
    result = deepcopy(card)
    result['excerpts'] = ([deepcopy(e) for e in fixed if e['role'] == 'declaration']
        + implementation + [deepcopy(e) for e in fixed if e['role'] != 'declaration'])
    start, end = catalog.extent(key)
    result['truncated'] = len(combined) != end - start + 1
    if len(canonical(result)) > MAX_CHARS:
        return card
    validate_card(result, catalog, check_disk=False)
    return result
