"""Per-callable explicit binding write inventory, without a heap/purity claim."""
from collections import defaultdict
from .model import FactIndex, IR


def binding_writes(graph: IR) -> None:
    if graph.diagnostics:
        return
    index=FactIndex(graph)
    by_owner=defaultdict(list)
    for op in graph.operations:
        by_owner[op.owner].append(op)
    targets={f.subject:f.object for f in index.rows('ASSIGNMENT_TARGET')}
    members={f.subject for f in index.rows('MEMBER_OF')}
    nested={f.object for f in index.rows('OWNED_BY') if graph.entities[f.subject].kind=='CALLABLE'}
    cfg={f.subject:f.object for f in index.rows('CFG_STATUS')}
    call_owners={f.object:f.subject for f in index.rows('HAS_CALL')}
    dynamic={call_owners.get(f.subject) for f in index.rows('CALLEE_NAME')
             if f.object in {'eval','exec','locals','globals','_getframe','currentframe'}}
    candidates=defaultdict(set)
    for relation in ['HAS_PARAMETER','READS']:
        for f in index.rows(relation):candidates[f.subject].add(f.object)
    for relation in ['RECEIVER','ARGUMENT']:
        for f in index.rows(relation):
            if f.subject in call_owners:candidates[call_owners[f.subject]].add(f.object)
    for owner,ops in by_owner.items():
        entity=graph.entities[owner]
        if entity.kind!='CALLABLE' or entity.attrs.get('language') not in {'python','javascript','typescript','java','csharp'}:
            continue
        reason=''
        if cfg.get(owner)!='structured' or owner in nested or owner in dynamic:
            reason='control-or-dynamic-scope'
        writes=defaultdict(list)
        for op in ops:
            if op.kind in {'UPDATE','LOOP'} or op.native_kind in {'global_statement','nonlocal_statement','delete_statement','named_expression'}:
                reason=reason or 'indirect-write'
            if any(t in {'ref','out','++','--','+=','-=','*=','/=','%=','??=','&&=','||=','&=','|=','^=','<<=','>>='} for t in op.attrs.get('tokens',[])):
                reason=reason or 'indirect-write'
            if op.id in targets:
                target=targets[op.id];target_entity=graph.entities.get(target)
                if target_entity is None or target_entity.kind not in {'STORAGE','PARAMETER'} and target not in members:
                    reason=reason or 'unmodeled-target'
                writes[target].append(op)
            if op.kind=='ASSIGN' and (op.id not in targets or '=' not in op.attrs.get('tokens',[])):
                reason=reason or 'unmodeled-assignment'
        graph.add(owner,'BINDING_WRITE_STATUS','unsupported' if reason else 'supported',
                  analysis='binding-writes/1',reason=reason)
        if reason:continue
        for target,events in writes.items():
            graph.add(owner,'BINDING_WRITE_COUNT',target,f'{entity.path}:{entity.line}',
                      count=len(events),basis='explicit-writes',analysis='binding-writes/1')
            if len(events)==1:
                op=events[0]
                graph.add(op.id,'UNIQUE_BINDING_WRITE',target,f'{entity.path}:{op.line}',
                          basis='explicit-writes',analysis='binding-writes/1')
        for binding in candidates[owner]-writes.keys():
            candidate_entity=graph.entities.get(binding)
            if candidate_entity is not None and (candidate_entity.kind in {'STORAGE','PARAMETER'} or binding in members):
                graph.add(owner,'BINDING_WRITE_COUNT',binding,f'{entity.path}:{entity.line}',
                          count=0,basis='explicit-writes',analysis='binding-writes/1')
                graph.add(owner,'UNREASSIGNED_BINDING',binding,f'{entity.path}:{entity.line}',
                          basis='explicit-writes',analysis='binding-writes/1')
