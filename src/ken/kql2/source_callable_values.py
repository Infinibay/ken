"""Conservative local callable aliases when closure scopes prevent full flow analysis."""


def reaches(callable_id, value_id, point, operations, rows, check):
    def block(operation):
        seen=set()
        while operation is not None and operation.id not in seen:
            seen.add(operation.id)
            if operation.native_kind in ('block','statement_block','compound_statement','statement_list'):
                return operation.id
            operation=operations.get(operation.parent or '')
        return None

    region=block(point)
    before=point.start
    seen=set()
    while value_id != callable_id:
        check()
        if value_id in seen or len(seen)>=16:
            return False
        seen.add(value_id)
        loaded=rows('LOADED_FROM',value_id)
        if len(loaded)==1:
            value_id=loaded[0].object
            continue
        counts=rows('STORAGE_WRITE_COUNT',value_id)
        status=rows('STORAGE_WRITE_STATUS',value_id)
        if (len(counts)!=1 or not counts[0].object.isdigit() or not status
                or any(f.object!='supported' for f in status)):
            return False
        candidates=[]
        for operation in operations.values():
            check()
            if operation.owner==point.owner and any(f.object==value_id for f in rows('ASSIGNMENT_TARGET',operation.id)):
                candidates.append(operation)
        # Counts include captured/iteration writes too. If a write is not in
        # this owner's explicit inventory, its timing is not established here.
        if len(candidates)!=int(counts[0].object):
            return False
        earlier=[write for write in candidates if write.end<before]
        if not earlier or not region or any(block(write)!=region for write in earlier):
            return False
        write=max(earlier,key=lambda operation:operation.end)
        values=rows('ASSIGNMENT_VALUE',write.id)
        if len(values)!=1:
            return False
        value_id=values[0].object
        before=write.start
    return True
