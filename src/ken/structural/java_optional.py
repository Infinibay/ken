"""Explicit-import Optional API model, seeded by unshadowed ofNullable calls."""
import re
from collections import defaultdict, deque

from .model import IR


def optional_facts(graph: IR) -> None:
    imports: dict[str, set[str]] = defaultdict(set)
    arguments: dict[str, dict[int, str]] = defaultdict(dict)
    receivers: dict[str, list[str]] = defaultdict(list)
    assignments: dict[str, set[str]] = defaultdict(set)
    for fact in graph.facts:
        if fact.relation == 'IMPORT_SYNTAX' and fact.attrs.get('language') == 'java':
            match = re.fullmatch(r'import\s+([\w.]+\.Optional)\s*;', fact.object)
            if match: imports[fact.subject.removesuffix('::module')].add(match[1])
        elif fact.relation == 'ARGUMENT':
            arguments[fact.subject][fact.attrs.get('position', 0)] = fact.object
        elif fact.relation == 'RECEIVER':
            receivers[fact.object].append(fact.subject)
        elif fact.relation == 'ASSIGNED_FROM':
            assignments[fact.subject].add(fact.object)
    # Conservatively reject declaration collisions anywhere in that source file.
    shadowed = {e.path for e in graph.entities.values() if e.name == 'Optional'
                and (e.kind in {'CLASS', 'INTERFACE', 'PARAMETER', 'CALLABLE'} or e.attrs.get('declared'))}
    aliases: dict[str, list[str]] = defaultdict(list)
    for storage, values in assignments.items():
        if len(values) == 1:
            aliases[next(iter(values))].append(storage)
    pending: deque[str] = deque()
    for receiver, calls in receivers.items():
        symbol = graph.entities.get(receiver)
        if (symbol is None or symbol.name != 'Optional' or symbol.path in shadowed
                or symbol.kind != 'STORAGE' or symbol.attrs.get('native_kind') != 'identifier'):
            continue
        if imports[symbol.path] != {'java.util.Optional'}:
            continue
        for call in calls:
            entity = graph.entities[call]
            if entity.attrs.get('name') == 'ofNullable' and set(arguments[call]) == {0}:
                graph.add(call, 'OPTIONAL_VALUE', arguments[call][0], f'{entity.path}:{entity.line}', model='java.util.Optional.ofNullable')
                pending.append(call)
    visited: set[str] = set()
    while pending:
        receiver = pending.popleft()
        if receiver in visited: continue
        visited.add(receiver)
        pending.extend(aliases.get(receiver, []))
        for call in receivers.get(receiver, []):
            entity = graph.entities[call]
            name = entity.attrs.get('name', '')
            relation = {'or': 'OPTIONAL_OR', 'ifPresent': 'OPTIONAL_PRESENT', 'orElse': 'OPTIONAL_FALLBACK'}.get(name)
            if relation and set(arguments[call]) == {0}:
                graph.add(call, relation, arguments[call][0], f'{entity.path}:{entity.line}', model='java.util.Optional.' + str(name))
                if name == 'or': pending.append(call)
