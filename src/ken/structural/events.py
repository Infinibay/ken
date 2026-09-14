"""C# events: declaration, handler registration/removal and raising.

An ``event`` is a field-like member with add/remove accessors, not a plain
delegate field: ``+=`` registers a handler and ``-=`` unregisters one. These facts
tie a registration, a removal or a raise to the event the declaring type
publishes, so a query can require the *same storage* instead of comparing names.

Two deliberate exclusions:

- A custom accessor (``event_declaration`` with an ``accessor_list``) is never
  marked as an event field, so no registration fact is emitted for it. Its
  semantics are not known.
- ``MEMBER_DECLARATION`` is emitted only when the receiver's recorded type is a
  single nominal class or interface that declares that member. A structural,
  generic or ambiguous receiver yields no fact, never a guessed slot.
"""
import re
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

    receivers: dict[str, set[str]] = defaultdict(set)
    for fact in index.rows('MEMBER_OF'):
        receivers[fact.subject].add(fact.object)
    fields: dict[str, dict[str, str]] = defaultdict(dict)
    for fact in index.rows('HAS_FIELD'):
        fields[fact.subject][entities[fact.object].name] = fact.object
    by_name: dict[str, list[str]] = defaultdict(list)
    for entity in entities.values():
        if entity.kind in {'CLASS', 'INTERFACE'}:
            by_name[entity.name].append(entity.id)

    def declared_slot(access: str) -> str | None:
        """Field a member access denotes, when its receiver's type is nominal."""
        for receiver in receivers.get(access, ()):
            if receiver not in entities:
                continue
            spelling = str(entities[receiver].attrs.get('type') or '')
            if not re.fullmatch(r'[A-Za-z_][\w.]*', spelling):
                continue
            candidates = by_name.get(spelling, [])
            if len(candidates) != 1:
                continue
            slot = fields[candidates[0]].get(entities[access].name)
            if slot is not None:
                return slot
        return None

    for access in sorted(receivers):
        slot = declared_slot(access)
        if slot is not None:
            graph.add(access, 'MEMBER_DECLARATION', slot,
                      f'{entities[access].path}:{entities[access].line}', basis='nominal-receiver')

    targets = {fact.subject: fact.object for fact in index.rows('ASSIGNMENT_TARGET')}
    handlers = {fact.subject: fact.object for fact in index.rows('ASSIGNMENT_VALUE')}
    for op in graph.operations:
        operator = next((t for t in op.attrs.get('tokens') or [] if t in {'+=', '-='}), None)
        if operator is None or op.id not in targets:
            continue
        target = targets[op.id]
        slot = target if target in events else declared_slot(target)
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
