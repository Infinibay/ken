"""Evaluate source type matchers on a shared indexed type descriptor graph."""
from types import SimpleNamespace

from .source_execution import SourceSemantics
from .source_types import matches
from .values import is_unknown


def filter_row(executor, spec, row):
    from ken.structural.relational import Row
    role, property_name, expected = spec[:3]
    if not hasattr(executor, '_source_type_semantics'):
        executor._source_type_semantics = SourceSemantics(executor.index, executor.tick)
    semantics = executor._source_type_semantics
    if property_name == 'escapes':
        from .receiver_effects import ReceiverEffects
        if not hasattr(executor, '_receiver_effects'):
            executor._receiver_effects = ReceiverEffects(executor.index,executor.tick)
        owner = row.bindings[spec[3]]
        actual = executor._receiver_effects.summarize(owner,row.bindings[role])
        if actual is None:
            yield Row(row.bindings,row.evidence,row.unknown | {'receiver_escape:unknown'})
        elif actual == (expected.value == 'true'):
            yield row
        return
    if property_name in ('initial','writes'):
        from .source_storage_contracts import evaluate
        accepted = evaluate(semantics,row.bindings,role,property_name,expected)
        if accepted is True:
            yield row
        elif accepted is None:
            yield Row(row.bindings,row.evidence,row.unknown | {'source_storage:unknown'})
        return
    if property_name == 'reassigned':
        binding = row.bindings[role]
        statuses = semantics.facts('STORAGE_WRITE_STATUS',binding)
        counts = semantics.facts('STORAGE_WRITE_COUNT',binding)
        if not statuses or any(f.object != 'supported' for f in statuses) or len(counts) != 1:
            yield Row(row.bindings,row.evidence,row.unknown | {'parameter_writes:unknown'})
        elif (int(counts[0].object) > 0) == (expected.value == 'true'):
            yield row
        return
    if property_name == 'completes':
        # ``completes: true``: the callable's body operation admits normal completion.
        # Every other operation it owns is a statement inside that body, so the body
        # is the one the callable is the owner of and that plays the body role.
        owner = row.bindings[role]
        bodies = [f.object for f in semantics.facts('HAS_OPERATION',owner)
                  if any(g.attrs.get('role') == 'body' for g in semantics.facts('OPERATION',f.object))]
        completion = {f.object for body in bodies for f in semantics.facts('NORMAL_COMPLETION',body)}
        if len(bodies) != 1 or not completion:
            yield Row(row.bindings,row.evidence,row.unknown | {'normal_completion:unknown'})
        elif ('possible' in completion) == (expected.value == 'true'):
            yield row
        return
    actual = semantics.type_of(SimpleNamespace(local_id=row.bindings[role]),
                               returns=property_name.startswith('return_'))
    if property_name.endswith('_status'):
        accepted = ('unknown' if is_unknown(actual) else 'known') == expected.value.strip('"')
    else:
        accepted = matches(actual, expected)
    if accepted is True:
        yield row
    elif is_unknown(accepted):
        yield Row(row.bindings, row.evidence, row.unknown | {'source_type:unknown'})
