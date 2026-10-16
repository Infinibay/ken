"""Native CORE relevance predicates, independent from retrieval or model code."""


def correct_piece(result, target):
    if not correct_file(result, target):
        return False
    for anchor in target.get('anchor_ranges', []):
        if any(evidence['start_line'] <= anchor['start_line']
               and evidence['end_line'] >= anchor['end_line']
               for evidence in result.get('evidence', [])):
            return True
    entity = result.get('entity') or {}
    span = result.get('entity_span') or {}
    if target['kind'] in {'fragment', 'file'} or not target.get('qualname'):
        return False
    return (entity.get('kind') == target['kind']
            and entity.get('qualname') == target['qualname']
            and target.get('declaration_start_line', target['start_line'])
                <= span.get('start_line', -1) <= target['start_line']
            and span.get('end_line') == target['end_line'])


def correct_file(result, target):
    return (result.get('path') == target['path']
            and result.get('source_hash') == target['source_sha256']
            and result.get('stale') is False)
