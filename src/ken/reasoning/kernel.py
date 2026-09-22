"""Serializable stochastic work queue with indexed, interruptible joins.

Scheduling affects effort to a partial answer, never the inference semantics.
Each join candidate consumes one work unit. A checkpoint retains join cursors.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .model import Atom, digest, unify

MAX_FACTS = 10000
MAX_JOBS = 50000
MAX_PROOFS = 50000
VERSION = 1


class Kernel:
    def __init__(self, rules: list[dict[str, Any]], state: dict[str, Any] | None = None, seed: int = 7):
        self.rules = rules
        self.s = state or {'version': VERSION, 'facts': {}, 'jobs': [], 'applications': [],
                           'rng': seed & 0xffffffff or 1, 'steps': 0, 'limits': []}
        if self.s['version'] != VERSION:
            raise ValueError('Incompatible reasoning checkpoint')
        self.atoms = {k: Atom.read(v['atom'], ground=True) for k, v in self.s['facts'].items()}
        self.index: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for aid, atom in self.atoms.items():
            self._index(aid, atom)
        self.applied = set(self.s['applications'])
        self.by_pred: dict[tuple[str, bool, str], list[tuple[int, int]]] = defaultdict(list)
        for ri, r in enumerate(rules):
            for pos, a in enumerate(r['body']):
                self.by_pred[Atom.read(a).key].append((ri, pos))

    def _index(self, aid: str, atom: Atom) -> None:
        for key in (atom.key, atom.key + ('s', atom.subject), atom.key + ('o', atom.object),
                    atom.key + ('pair', atom.subject, atom.object)):
            self.index[key].append(aid)

    def candidates(self, p: Atom) -> list[str]:
        if not p.subject.startswith('?') and not p.object.startswith('?'):
            key: tuple[Any, ...] = p.key + ('pair', p.subject, p.object)
        elif not p.subject.startswith('?'):
            key = p.key + ('s', p.subject)
        elif not p.object.startswith('?'):
            key = p.key + ('o', p.object)
        else:
            key = p.key
        return self.index.get(key, [])

    def enqueue(self, job: dict[str, Any]) -> None:
        if len(self.s['jobs']) >= MAX_JOBS:
            self.s['limits'] = ['max_jobs']
        else:
            self.s['jobs'].append(job)

    def add(self, atom: Atom, proof: dict[str, Any]) -> None:
        aid = atom.id
        key = digest([aid, proof])
        if key in self.applied:
            return
        if len(self.applied) >= MAX_PROOFS:
            self.s['limits'] = ['max_proofs']
            return
        if aid not in self.atoms:
            if len(self.atoms) >= MAX_FACTS:
                self.s['limits'] = ['max_facts']
                return
            self.atoms[aid] = atom
            self.s['facts'][aid] = {'atom': atom.data(), 'proofs': []}
            self._index(aid, atom)
            self.enqueue({'kind': 'expand', 'fact': aid})
        self.applied.add(key)
        self.s['facts'][aid]['proofs'].append(proof)

    def relevant(self, goal: Atom) -> set[tuple[str, bool, str]]:
        keys = {goal.key, goal.opposite().key}
        while True:
            old = len(keys)
            for r in self.rules:
                if Atom.read(r['head']).key in keys:
                    keys.update(Atom.read(a).key for a in r['body'])
            if old == len(keys):
                return keys

    def run(self, goal: Atom, budget: int) -> dict[str, Any]:
        relevant = self.relevant(goal)
        start = self.s['steps']
        while self.s['jobs'] and self.s['steps'] - start < budget and not self.s['limits']:
            # Every tenth job uses FIFO; otherwise choose stochastically among
            # a bounded window, biased toward predicates upstream of the goal.
            jobs = self.s['jobs']
            index = 0
            if self.s['steps'] % 10:
                self.s['rng'] = (1664525 * self.s['rng'] + 1013904223) & 0xffffffff
                window = jobs[:64]
                weights = [4 if (self.atoms[j['fact']].key if j['kind'] == 'expand'
                                else Atom.read(self.rules[j['rule']]['head']).key) in relevant else 1
                           for j in window]
                pick = self.s['rng'] % sum(weights)
                for index, weight in enumerate(weights):
                    pick -= weight
                    if pick < 0:
                        break
            job = jobs.pop(index)
            self.s['steps'] += 1
            if job['kind'] == 'expand':
                fact = self.atoms[job['fact']]
                for ri, pos in self.by_pred[fact.key]:
                    r = self.rules[ri]
                    b = unify(Atom.read(r['body'][pos]), fact)
                    if b is not None:
                        self.enqueue({'kind': 'join', 'rule': ri, 'binding': b,
                                      'premises': [job['fact']],
                                      'remaining': [i for i in range(len(r['body'])) if i != pos]})
            else:
                self._join(job)
        self.s['applications'] = sorted(self.applied)
        return {'work': self.s['steps'] - start, 'total_work': self.s['steps'],
                'facts': len(self.atoms), 'pending': len(self.s['jobs']),
                'complete': not self.s['jobs'] and not self.s['limits'],
                'limits': self.s['limits'] or (['budget'] if self.s['jobs'] else []),
                'resumable': bool(self.s['jobs']) and not self.s['limits']}

    def _join(self, job: dict[str, Any]) -> None:
        r = self.rules[job['rule']]
        if not job['remaining']:
            atom = Atom.read(r['head']).bind(job['binding'])
            if atom.id in job['premises'] or (atom.predicate == 'subclass' and atom.subject == atom.object):
                return
            self.add(atom, {'kind': 'deduced', 'source': r['source'], 'rule': r['id'],
                            'premises': sorted(job['premises'])})
            return
        if 'position' not in job:
            job['position'] = min(job['remaining'], key=lambda i: len(self.candidates(
                Atom.read(r['body'][i]).bind(job['binding']))))
            job['cursor'] = 0
            job['stop'] = len(self.candidates(Atom.read(r['body'][job['position']]).bind(job['binding'])))
        p = Atom.read(r['body'][job['position']])
        candidates = self.candidates(p.bind(job['binding']))
        if job['cursor'] >= job['stop']:
            return
        aid = candidates[job['cursor']]
        b = unify(p, self.atoms[aid], job['binding'])
        job['cursor'] += 1
        if job['cursor'] < job['stop']:
            self.enqueue(job)
        if b is not None:
            self.enqueue({'kind': 'join', 'rule': job['rule'], 'binding': b,
                          'premises': job['premises'] + [aid],
                          'remaining': [i for i in job['remaining'] if i != job['position']]})

    def proof(self, aid: str, path: frozenset[str] = frozenset(), depth: int = 50,
              remaining: list[int] | None = None) -> dict[str, Any] | None:
        remaining = remaining if remaining is not None else [300]
        if aid in path or depth <= 0 or remaining[0] <= 0:
            return None
        remaining[0] -= 1
        record = self.s['facts'][aid]
        for support in sorted(record['proofs'], key=lambda p: p['kind'] == 'deduced'):
            children = [self.proof(p, path | {aid}, depth - 1, remaining) for p in support['premises']]
            if all(c is not None for c in children):
                return {'fact': record['atom'], 'support': support, 'premises': children}
        return None

    def answers(self, goal: Atom, limit: int = 25) -> dict[str, Any]:
        positives = [(a, unify(goal, a)) for a in self.atoms.values() if unify(goal, a) is not None]
        negatives = [a for a in self.atoms.values() if unify(goal.opposite(), a) is not None]
        status = 'supported' if positives else 'unknown'
        if not goal.variables:
            status = 'conflict' if positives and negatives else 'refuted' if negatives else status
        elif any(a.opposite().id in self.atoms for a, _ in positives):
            status = 'conflict'
        answers = [{'fact': a.data(), 'binding': b, 'proof': self.proof(a.id),
                    'opposing_proof': self.proof(a.opposite().id) if a.opposite().id in self.atoms else None}
                   for a, b in sorted(positives, key=lambda p: p[0].id)[:limit]]
        return {'status': status, 'answers': answers, 'answers_truncated': len(positives) > limit,
                'opposition': [self.proof(a.id) for a in negatives[:limit]] if not goal.variables else [],
                'proof_note': 'Null proof means the explanation depth limit was reached, not absence of support.'}
