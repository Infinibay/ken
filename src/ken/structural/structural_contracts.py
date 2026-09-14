"""Nominal member resolution and structural interface satisfaction.

Two general capabilities that languages without a shared inheritance model need:

- A member access on a receiver whose recorded type is a single nominal class or
  interface resolves to the field or method that type declares
  (``MEMBER_DECLARATION``), and a call through such a member resolves to the
  declared method (``TARGET``) when nothing else resolved it already. This is what
  makes ``creator.create()`` on a ``dyn Creator`` parameter reach the trait slot,
  with no inheritance involved.
- Go satisfies an interface by method set rather than by an ``implements``
  keyword, which is ``IMPLEMENTS`` and never ``SUBTYPE_OF``.

Both refuse rather than guess: a structural, generic or ambiguous receiver yields
no fact, and Go links only an exact method-set coverage.
"""
import re
from collections import defaultdict

from .model import Entity, FactIndex, IR


def structural_contracts(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    entities = graph.entities

    receivers: dict[str, set[str]] = defaultdict(set)
    for fact in index.rows('MEMBER_OF'):
        receivers[fact.subject].add(fact.object)
    fields: dict[str, dict[str, str]] = defaultdict(dict)
    for fact in index.rows('HAS_FIELD'):
        fields[fact.subject][entities[fact.object].name] = fact.object
    methods: dict[str, dict[str, str]] = defaultdict(dict)
    for fact in index.rows('HAS_METHOD'):
        methods[fact.subject][entities[fact.object].name] = fact.object
    by_name: dict[str, list[str]] = defaultdict(list)
    for declared_type in entities.values():
        if declared_type.kind in {'CLASS', 'INTERFACE'}:
            by_name[declared_type.name].append(declared_type.id)

    def nominal_type(receiver: str) -> str | None:
        entity = entities.get(receiver)
        if entity is None:
            return None
        # ``&dyn Trait``, ``dyn Trait``, ``impl Trait``, ``*T`` and ``T`` all name
        # the same declaration for member lookup; a generic argument does not, so
        # it is left unresolved.
        spelling = str(entity.attrs.get('type') or '')
        spelling = re.sub(r'^[&*]+\s*', '', spelling.strip())
        spelling = re.sub(r'^(?:dyn|impl|mut|const)\s+', '', spelling).strip()
        if not re.fullmatch(r'[A-Za-z_][\w.]*', spelling):
            return None
        candidates = by_name.get(spelling, [])
        return candidates[0] if len(candidates) == 1 else None

    def declared(access: str) -> tuple[str | None, str | None]:
        """Field and method an access denotes, when its receiver type is nominal."""
        for receiver in receivers.get(access, ()):
            unit = nominal_type(receiver)
            if unit is None:
                continue
            name = entities[access].name
            field, method = fields[unit].get(name), methods[unit].get(name)
            if field is not None or method is not None:
                return field, method
        return None, None

    for access in sorted(receivers):
        field, _ = declared(access)
        if field is None:
            continue
        # Members that resolve to a method are left to the nominal call resolution
        # in ``semantic``, which already separates a declared slot from the
        # possible concrete targets. Only the field link is new here.
        graph.add(access, 'MEMBER_DECLARATION', field,
                  f'{entities[access].path}:{entities[access].line}', basis='nominal-receiver')

    required: dict[str, dict[str, str]] = defaultdict(dict)
    provided: dict[str, dict[str, str]] = defaultdict(dict)
    for owner, table in methods.items():
        entity = entities.get(owner)
        if entity is None or entity.attrs.get('language') != 'go':
            continue
        if entity.kind == 'INTERFACE':
            required[owner] = table
        elif entity.kind == 'CLASS':
            provided[owner] = table
    arity: dict[str, int] = defaultdict(int)
    for fact in index.rows('HAS_PARAMETER'):
        if not fact.attrs.get('receiver'):
            arity[fact.subject] += 1

    for interface, wanted in required.items():
        if not wanted:
            continue
        for concrete, available in provided.items():
            if not all(name in available and arity[available[name]] == arity[wanted[name]]
                       for name in wanted):
                continue
            evidence = f'{entities[concrete].path}:{entities[concrete].line}'
            graph.add(concrete, 'IMPLEMENTS', interface, evidence, basis='method-set')
            for name, contract in wanted.items():
                graph.add(available[name], 'OVERRIDES', contract, evidence, basis='method-set')

    # Shared member signatures. Two nominal types that declare the same member
    # name with the same arity expose the same slot, whether or not they share a
    # base: JavaScript objects, TypeScript interfaces and Go method sets are all
    # structural, and a query that relates two providers by their slot set cannot
    # join on ``name`` without pairing every method with every other method.
    # Grouping the slot under one entity turns that into a join by identity.
    # Constructors are excluded: every class has one, so they would group
    # unrelated types, and they are a declaration rather than a creation slot.
    members: dict[tuple[str, int], list[str]] = defaultdict(list)
    owners: dict[tuple[str, int], set[str]] = defaultdict(set)
    for owner, table in methods.items():
        declaring_type = entities.get(owner)
        if declaring_type is None or declaring_type.kind not in {'CLASS', 'INTERFACE'}:
            continue
        for name, member in table.items():
            if not name or entities[member].attrs.get('constructor'):
                continue
            key = (name, arity[member])
            members[key].append(member)
            owners[key].add(owner)
    for (name, count), declared_by in sorted(owners.items()):
        if len(declared_by) < 2:
            continue
        signature = f'signature:{name}/{count}'
        first = entities[members[(name, count)][0]]
        evidence = f'{first.path}:{first.line}'
        if signature not in entities:
            entities[signature] = Entity(signature, 'SIGNATURE', name, first.path, first.line,
                                         first.end_line, {'name': name, 'arity': count,
                                                          'language': graph.language})
            graph.add(signature, 'IS', 'SIGNATURE', evidence, basis='shared-member-signature')
        for member in members[(name, count)]:
            graph.add(member, 'MATCHES_SIGNATURE', signature, evidence,
                      basis='shared-member-signature')
