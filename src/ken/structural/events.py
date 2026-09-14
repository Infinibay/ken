"""C# events: declaration, handler registration/removal and raising.

An ``event`` is a field-like member with add/remove accessors, not a plain
delegate field: ``+=`` registers a handler and ``-=`` unregisters one. These facts
tie a registration, a removal or a raise to the event the declaring type
publishes, so a query can require the *same storage* instead of comparing names.

The member-to-declaration resolution this needs is general and comes from
``structural_contracts`` (``MEMBER_DECLARATION``), not from this pass.

Two deliberate exclusions:

- A custom accessor (``event_declaration`` with an ``accessor_list``) is never
  marked as an event field, so no registration fact is emitted for it. Its
  semantics are not known.
- Only a registration whose target resolves to an event produces a fact. An
  unresolvable member yields nothing.
"""
from collections import defaultdict

from .model import FactIndex, IR


def csharp_events(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    entities = graph.entities

    events = {fact.object for fact in index.rows('DECLARES_EVENT')}
    if not events:
        return

    declared = {fact.subject: fact.object for fact in index.rows('MEMBER_DECLARATION')}
    targets = {fact.subject: fact.object for fact in index.rows('ASSIGNMENT_TARGET')}
    handlers = {fact.subject: fact.object for fact in index.rows('ASSIGNMENT_VALUE')}
    for op in graph.operations:
        operator = next((t for t in op.attrs.get('tokens') or [] if t in {'+=', '-='}), None)
        if operator is None or op.id not in targets:
            continue
        target = targets[op.id]
        slot = target if target in events else declared.get(target)
        if slot not in events:
            continue
        owner = entities.get(op.owner)
        evidence = f'{owner.path}:{op.line}' if owner is not None else ''
        graph.add(op.owner, 'ADDS_HANDLER' if operator == '+=' else 'REMOVES_HANDLER', slot,
                  evidence, handler=handlers.get(op.id, ''))

    for relation in ('RECEIVER', 'CALLEE_VALUE'):
        for fact in index.rows(relation):
            if fact.object in events:
                graph.add(fact.subject, 'RAISES_EVENT', fact.object,
                          fact.evidence[0] if fact.evidence else '', basis='event-invocation')
