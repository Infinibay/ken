"""Path-local pending completions, separate from local value provenance."""
from dataclasses import dataclass, replace
from typing import Any

from ken.structural.control_exceptions import consumes
from .path_values import Snapshot


@dataclass(frozen=True, slots=True)
class FinalizerContinuation:
    scope: str
    target: str
    exception: str
    returned: tuple[str, Snapshot | None] | None


@dataclass(frozen=True, slots=True)
class GroupDispatch:
    scope: str
    exception: str
    matched: bool = False
    raised: bool = False
    processed_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Continuations:
    finalizers: tuple[FinalizerContinuation, ...] = ()
    groups: tuple[GroupDispatch, ...] = ()
    returned: tuple[str, Snapshot | None] | None = None
    closing: bool = False
    exception: str = ""


def permits(event: dict[str, Any], flow: Continuations, target: str, kind: str = '') -> bool:
    action, scope = event.get('action'), event.get('scope')
    if flow.exception == 'GeneratorExit' and (
        event.get('close_blocked') or action == 'propagate' and event.get('close') == 'no'
        or event.get('close') == 'no' and kind == 'handler'
    ):
        return False
    if action == 'finally-leave':
        return bool(flow.finalizers and flow.finalizers[-1].scope == scope
                    and flow.finalizers[-1].target == target)
    if action == 'star-exit':
        if not flow.groups or flow.groups[-1].scope != scope:
            return False
        group = flow.groups[-1]
        if target == event['normal']:
            return group.matched and not group.raised
        return group.raised or not consumes(group.processed_types, (group.exception or 'BaseException',))
    if action == 'star-match' and flow.groups:
        group = flow.groups[-1]
        if consumes(group.processed_types, (group.exception or 'BaseException',)):
            return False
        types = event.get('types', ())
        if group.exception and types and not consumes(types, (group.exception,)):
            return False
        return not consumes(group.processed_types, types)
    return True


def advance(event: dict[str, Any], flow: Continuations, snapshot: Snapshot | None, target: str) -> Continuations:
    action, scope = event.get('action'), event.get('scope')
    if action == 'unwind':
        abandoned = event.get('scopes', ())
        remaining = tuple(f for f in flow.finalizers if f.scope not in abandoned)
        flow = replace(flow, finalizers=remaining,
                       returned=((remaining[-1].returned if remaining else None)
                                 if len(remaining) != len(flow.finalizers) else flow.returned))
    if action == 'return-eval':
        return replace(flow, returned=(event['operation'], snapshot), exception='')
    if action == 'finally-enter':
        assert isinstance(scope, str)
        return replace(flow, finalizers=(*flow.finalizers, FinalizerContinuation(
            scope, event['target'], flow.exception, flow.returned)))
    if action == 'finally-leave':
        return replace(flow, finalizers=flow.finalizers[:-1], exception=flow.finalizers[-1].exception,
                       returned=flow.finalizers[-1].returned)
    if action == 'star-enter':
        assert isinstance(scope, str)
        return replace(flow, groups=(*flow.groups, GroupDispatch(scope, flow.exception)))
    if action == 'star-header' and flow.groups and target != event['match']:
        group = flow.groups[-1]
        updated = replace(group, processed_types=(*group.processed_types, *event.get('types', ())))
        return replace(flow, groups=(*flow.groups[:-1], updated))
    if action in {'star-match', 'star-raise'} and flow.groups:
        group = flow.groups[-1]
        updated = replace(group, matched=group.matched or action == 'star-match',
                          raised=group.raised or action == 'star-raise',
                          processed_types=(*group.processed_types, *event.get('types', ())))
        return replace(flow, groups=(*flow.groups[:-1], updated), exception='')
    if action == 'star-exit':
        return replace(flow, groups=flow.groups[:-1], exception=(
            '' if target == event['normal'] or flow.groups[-1].raised else flow.groups[-1].exception))
    if action == 'handler':
        return replace(flow, exception='')
    return flow
