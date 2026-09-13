"""Occurrence-correlated argument bindings and explicit constructor candidates."""
from collections import defaultdict

from .model import FactIndex, IR


def call_bindings(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    params = defaultdict(list)
    arguments = defaultdict(list)
    targets = defaultdict(set)
    constructors = defaultdict(list)
    methods = defaultdict(list)
    for f in index.rows('HAS_PARAMETER'):
        if not f.attrs.get('receiver'):
            params[f.subject].append(f)
    for f in index.rows('ARGUMENT'):
        arguments[f.subject].append(f)
    for f in index.rows('TARGET'):
        if graph.entities.get(f.object) is not None and graph.entities[f.object].kind == 'CALLABLE':
            targets[f.subject].add(f.object)
    for f in index.rows('HAS_METHOD'):
        methods[f.subject].append(f.object)
        if graph.entities[f.object].attrs.get('constructor'):
            constructors[f.subject].append(f.object)
    for f in index.rows('ALLOCATES_TYPE'):
        unit = graph.entities[f.object]
        candidates = constructors[f.object]
        if unit.attrs.get('language') not in {'python', 'javascript', 'typescript', 'java', 'csharp'}:
            graph.add(f.subject, 'CONSTRUCTOR_STATUS', 'unsupported', *f.evidence[:1], reason='language')
            continue
        if unit.attrs.get('language') == 'python' and any(graph.entities[m].name == '__new__' for m in methods[f.object]):
            graph.add(f.subject, 'CONSTRUCTOR_STATUS', 'unsupported', *f.evidence[:1], reason='custom-allocation')
            continue
        if len(candidates) == 1:
            graph.add(f.subject, 'CONSTRUCTOR_TARGET', candidates[0], *f.evidence[:1], basis='unique-declaration')
            graph.add(f.subject, 'CONSTRUCTOR_STATUS', 'resolved', *f.evidence[:1], basis='unique-declaration')
            targets[f.subject] = {candidates[0]}
        else:
            for candidate in candidates:
                graph.add(f.subject, 'MAY_CONSTRUCTOR_TARGET', candidate, *f.evidence[:1], modality='may')
            graph.add(f.subject, 'CONSTRUCTOR_STATUS', 'unsupported', *f.evidence[:1],
                      reason='ambiguous' if candidates else 'implicit-or-inherited')
    unsupported_signatures = {o.owner for o in graph.operations
                              if any(t in {'ref', 'out', 'params'} for t in o.attrs.get('tokens', []))}
    for call, call_targets in targets.items():
        if len(call_targets) != 1:
            continue
        target = next(iter(call_targets))
        entity = graph.entities[target]
        ev = f'{graph.entities[call].path}:{graph.entities[call].line}'
        signature = sorted(params[target], key=lambda p: p.attrs.get('position', 0))
        actual = sorted(arguments[call], key=lambda a: a.attrs.get('position', 0))
        reason = ''
        if entity.attrs.get('language') not in {'python', 'javascript', 'typescript', 'java', 'csharp'}:
            reason = 'language'
        elif target in unsupported_signatures:
            reason = 'parameter-mode'
        elif any(a.attrs.get('kind', '').startswith('spread') for a in actual):
            reason = 'expanded-arguments'
        # Container-valued variadics need element/key provenance, not scalar equality.
        elif any(p.attrs.get('kind', '').startswith('variadic') for p in signature):
            reason = 'variadic-parameters'
        positional = [p for p in signature if p.attrs.get('kind') != 'keyword_only']
        names = {graph.entities[p.object].name: p for p in signature}
        bound = set()
        pending = []
        position = 0
        named_seen = False
        for argument in actual:
            if reason:
                break
            kind = argument.attrs.get('kind')
            parameter = None
            if kind == 'positional' and not named_seen and position < len(positional):
                parameter = positional[position]
                position += 1
            elif kind == 'named' and entity.attrs.get('language') in {'python', 'csharp'}:
                named_seen = True
                parameter = names.get(argument.attrs.get('name', ''))
                if parameter is not None and parameter.attrs.get('kind') == 'positional_only':
                    parameter = None
            if parameter is None or parameter.object in bound:
                reason = 'argument-shape'
                break
            bound.add(parameter.object)
            pending.append((argument, parameter))
        if not reason and any(p.object not in bound and not p.attrs.get('default') for p in signature):
            reason = 'missing-argument'
        graph.add(call, 'BINDING_STATUS', 'unsupported' if reason else 'supported', ev,
                  analysis='explicit-arguments/1', reason=reason)
        if reason:
            continue
        for argument, parameter in pending:
            position = argument.attrs.get('position', 0)
            binding = f'{call}/binding/{position}'
            graph.add(call, 'CALL_BINDING', binding, *argument.evidence[:1], position=position,
                      kind=argument.attrs.get('kind'), name=argument.attrs.get('name', ''), mode='direct')
            graph.add(binding, 'BINDING_PARAMETER', parameter.object, *argument.evidence[:1])
            graph.add(binding, 'BINDING_VALUE', argument.object, *argument.evidence[:1])
            graph.add(binding, 'BINDING_TARGET', target, *argument.evidence[:1])
