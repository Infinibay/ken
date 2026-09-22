"""Strict interchange format; entity and sense IDs are supplied by the caller."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError('Expected a nonempty identifier of at most 256 characters')
    return value


@dataclass(frozen=True)
class Atom:
    predicate: str
    subject: str
    object: str
    negative: bool = False
    scope: str = 'present'

    @classmethod
    def read(cls, data: Any, *, ground: bool = False) -> Atom:
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError('Atom fields: predicate, subject, object, negative, scope')
        for field in ('predicate', 'subject', 'object'):
            name(data.get(field))
        name(data.get('scope', 'present'))
        if type(data.get('negative', False)) is not bool:
            raise ValueError('negative must be boolean')
        a = cls(**data)
        if a.predicate.startswith('?') or a.scope.startswith('?'):
            raise ValueError('Only subject and object may contain variables')
        if ground and a.variables:
            raise ValueError('Premises must be ground; variables start with ?')
        return a

    @property
    def variables(self) -> set[str]:
        return {x for x in (self.subject, self.object) if x.startswith('?')}

    @property
    def key(self) -> tuple[str, bool, str]:
        return self.predicate, self.negative, self.scope

    @property
    def id(self) -> str:
        return digest(self.data())

    def data(self) -> dict[str, Any]:
        return asdict(self)

    def opposite(self) -> Atom:
        return Atom(self.predicate, self.subject, self.object, not self.negative, self.scope)

    def bind(self, binding: dict[str, str]) -> Atom:
        return Atom(self.predicate, binding.get(self.subject, self.subject),
                    binding.get(self.object, self.object), self.negative, self.scope)


def unify(pattern: Atom, fact: Atom, binding: dict[str, str] | None = None) -> dict[str, str] | None:
    if pattern.key != fact.key:
        return None
    out = dict(binding or {})
    for p, f in ((pattern.subject, fact.subject), (pattern.object, fact.object)):
        if p.startswith('?'):
            if p in out and out[p] != f:
                return None
            out[p] = f
        elif p != f:
            return None
    return out


def rule(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {'body', 'head'}:
        raise ValueError('Rule fields: body, head')
    if not isinstance(data['body'], list) or not 1 <= len(data['body']) <= 3:
        raise ValueError('Rules require one to three premises')
    body = [Atom.read(a) for a in data['body']]
    head = Atom.read(data['head'])
    if not head.variables <= set().union(*(a.variables for a in body)):
        raise ValueError('Head variables must be bound in the body')
    return {'body': [a.data() for a in body], 'head': head.data()}


def builtin_rules(atoms: list[Atom]) -> list[dict[str, Any]]:
    out = []
    for scope in sorted({a.scope for a in atoms}):
        def a(p: str, s: str, o: str, n: bool = False) -> dict[str, Any]:
            return Atom(p, s, o, n, scope).data()
        out.extend([
            {'body': [a('subclass', '?a', '?b'), a('subclass', '?b', '?c')], 'head': a('subclass', '?a', '?c')},
            {'body': [a('type', '?x', '?a'), a('subclass', '?a', '?b')], 'head': a('type', '?x', '?b')},
        ])
        for p in sorted({x.predicate for x in atoms if x.predicate.startswith('all/')}):
            for n in (False, True):
                out.extend([
                    {'body': [a('type', '?x', '?c'), a(p, '?c', '?o', n)], 'head': a(p[4:], '?x', '?o', n)},
                    {'body': [a('subclass', '?a', '?b'), a(p, '?b', '?o', n)], 'head': a(p, '?a', '?o', n)},
                ])
    return [r | {'source': '@builtin', 'id': digest(r)} for r in out]
