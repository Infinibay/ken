"""Research topology; call-target controls54/54b FAILED source fidelity review.

CALLEE_VALUE can select wrong overloads, earlier redefinitions or class members
where Python looks up a global. These call edges are provisional experimental
inputs, never certified targets or deployable retrieval evidence. Canonical
nesting is a separate, source-verified geometry used in the negative54c control.
See output/analysis/source-context-v54b-review.md for the preserved witnesses.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ken.retrieval.model import EntityKey, Span
from ken.structural.model import IR


@dataclass(frozen=True)
class CallEdge:
    caller: EntityKey
    callee: EntityKey
    call_span: Span
    target_line: int


def collect_call_edges(graph: IR, ownership: Mapping[EntityKey, Sequence[Span]]
                       ) -> tuple[tuple[CallEdge, ...], dict[str, int]]:
    """Use explicit IR targets; unknown target/ownership never falls back to names."""
    lines: dict[int, EntityKey] = {}
    for owner, spans in ownership.items():
        if owner.path != graph.path:
            raise ValueError('context path differs from canonical source ownership')
        for span in spans:
            for line in range(span.start_line, span.end_line+1):
                if lines.setdefault(line, owner) != owner:
                    raise ValueError('canonical context ownership overlap')
    targets: dict[str, set[str]] = defaultdict(set)
    declared_calls: set[str] = set()
    written: set[str] = set()
    definitions = Counter((e.path, e.qualname) for e in ownership if e.qualname)
    for fact in graph.facts:
        if fact.relation == 'CALLEE_VALUE':
            targets[fact.subject].add(fact.object)
        elif fact.relation == 'HAS_CALL':
            declared_calls.add(fact.object)
        elif fact.relation in {'WRITES', 'ASSIGNMENT_TARGET'}:
            written.add(fact.object)
        elif fact.relation == 'ASSIGNED_FROM':
            written.add(fact.subject)
    edges: list[CallEdge] = []
    counts: Counter[str] = Counter()
    for call in graph.entities.values():
        if call.kind != 'CALL':
            continue
        counts['calls'] += 1
        if call.id not in declared_calls:
            counts['missing_call_owner'] += 1
            continue
        values = targets.get(call.id, set())
        if not values:
            counts['unresolved_call'] += 1
            continue
        if len(values) != 1:
            counts['multiple_targets'] += 1
            continue
        caller = lines.get(call.line)
        if caller is None or any(lines.get(line) != caller for line in range(call.line, call.end_line+1)):
            counts['unmapped_caller'] += 1
            continue
        target = graph.entities.get(next(iter(values)))
        if target is None or target.kind not in {'CALLABLE', 'CLASS', 'INTERFACE', 'TYPE'}:
            counts['unresolved_call'] += 1
            continue
        callee = lines.get(target.line) if target is not None else None
        if (callee is None or not callee.qualname
                or callee.qualname.split('.')[-1] != target.name):
            counts['unmapped_target'] += 1
            continue
        if definitions[(callee.path, callee.qualname)] != 1:
            counts['ambiguous_definition'] += 1
            continue
        if target.id in written:
            counts['target_written'] += 1
            continue
        edges.append(CallEdge(caller, callee, Span(call.line, call.end_line), target.line))
        counts['mapped'] += 1
    for key in ('calls', 'unresolved_call', 'multiple_targets', 'unmapped_caller', 'unmapped_target',
                'ambiguous_definition', 'target_written', 'missing_call_owner', 'mapped'):
        counts.setdefault(key, 0)
    return tuple(dict.fromkeys(edges)), dict(counts)


def enclosing_edges(definitions: Mapping[EntityKey, Span]) -> tuple[tuple[EntityKey, EntityKey], ...]:
    """A named parent with one nearest enclosing definition, without sibling guesses."""
    by_name: dict[tuple[str, str], list[EntityKey]] = defaultdict(list)
    for entity in definitions:
        if entity.qualname:
            by_name[(entity.path, entity.qualname)].append(entity)
    edges: list[tuple[EntityKey, EntityKey]] = []
    for child, extent in definitions.items():
        if not child.owner:
            continue
        parents = [p for p in by_name.get((child.path, child.owner), ())
                   if p != child and definitions[p].start_line <= extent.start_line
                   and extent.end_line <= definitions[p].end_line and definitions[p] != extent]
        if not parents:
            continue
        lengths = {p: definitions[p].end_line-definitions[p].start_line for p in parents}
        nearest = [p for p in parents if lengths[p] == min(lengths.values())]
        if len(nearest) == 1:
            edges.append((nearest[0], child))
    return tuple(edges)
