"""Project-local evidence store and transactional inference checkpoints.

Append-only additions resume the materialization when the rule set is unchanged.
Replacement/retraction conservatively invalidates that context, including cycles.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .kernel import Kernel
from .model import Atom, builtin_rules, digest, name, rule, unify


class Memory:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS contexts (id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                  context TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(context,id));
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY, context TEXT, source TEXT, action TEXT, payload TEXT,
                  created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS checkpoints (
                  context TEXT, world TEXT, rules_hash TEXT, state TEXT,
                  PRIMARY KEY(context,world));
            ''')

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, source: str, *, context: str = 'main', facts: list[dict[str, Any]] | None = None,
               rules: list[dict[str, Any]] | None = None, evidence: str = '', retract: bool = False) -> dict[str, Any]:
        name(source); name(context)
        if source.startswith('@'):
            raise ValueError('Source IDs starting with @ are reserved')
        if not isinstance(evidence, str) or len(evidence) > 16000:
            raise ValueError('evidence must be text of at most 16000 characters')
        if not isinstance(facts or [], list) or not isinstance(rules or [], list):
            raise ValueError('facts and rules must be arrays')
        if len(facts or []) + len(rules or []) > 500:
            raise ValueError('At most 500 facts/rules per source')
        data = {'facts': [Atom.read(a, ground=True).data() for a in facts or []],
                'rules': [rule(r) for r in rules or []], 'evidence': evidence}
        if retract and (facts or rules or evidence):
            raise ValueError('Retraction cannot also add content')
        if not retract and not (data['facts'] or data['rules']):
            raise ValueError('Provide facts or rules; use ken_remember for unformalized notes')
        payload = json.dumps(data, sort_keys=True)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO contexts VALUES (?,0)', (context,))
            old = db.execute('SELECT payload FROM sources WHERE context=? AND id=?', (context, source)).fetchone()
            revision = db.execute('SELECT revision FROM contexts WHERE id=?', (context,)).fetchone()[0]
            if (old and old[0] == payload and not retract) or (not old and retract):
                return {'changed': False, 'revision': revision}
            if not old and not retract:
                count = db.execute('SELECT COUNT(*) FROM sources WHERE context=?', (context,)).fetchone()[0]
                if count >= 2000:
                    raise ValueError('Prototype limit: 2000 sources per context')
            db.execute('DELETE FROM sources WHERE context=? AND id=?', (context, source))
            if not retract:
                db.execute('INSERT INTO sources VALUES (?,?,?)', (context, source, payload))
            # Preserve base checkpoint on insertion; scenario worlds are cheap,
            # revision-bound overlays and are invalidated on any base mutation.
            db.execute('DELETE FROM checkpoints WHERE context=? AND (world != ? OR ?)', (context, 'base', bool(old)))
            db.execute('UPDATE contexts SET revision=revision+1 WHERE id=?', (context,))
            db.execute('INSERT INTO events(context,source,action,payload) VALUES (?,?,?,?)',
                       (context, source, 'retract' if retract else 'replace' if old else 'insert', payload))
            return {'changed': True, 'revision': revision + 1,
                    'update': 'invalidate_context' if old else 'append_delta'}

    def ask(self, goal: dict[str, Any], *, context: str = 'main', budget: int = 1000,
            seed: int = 7, assumptions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        query = Atom.read(goal); name(context)
        if type(budget) is not int or not 0 <= budget <= 10000 or type(seed) is not int:
            raise ValueError('budget must be 0..10000; seed must be integer')
        if assumptions is not None and (not isinstance(assumptions, list) or len(assumptions) > 8):
            raise ValueError('At most eight ground assumptions')
        assumed = sorted({Atom.read(a, ground=True) for a in assumptions or []}, key=lambda a: a.id)
        world = digest([a.data() for a in assumed]) if assumed else 'base'
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM contexts WHERE id=?', (context,)).fetchone()
            revision = row[0] if row else 0
            sources = {sid: json.loads(p) for sid, p in db.execute(
                'SELECT id,payload FROM sources WHERE context=? ORDER BY id', (context,))}
            atoms = [(Atom.read(a, ground=True), sid) for sid, src in sources.items() for a in src['facts']]
            rules = [r | {'source': sid, 'id': digest([sid, r])}
                     for sid, src in sources.items() for r in src['rules']]
            if len(atoms) > 10000 or len(rules) > 2000:
                raise ValueError('Prototype context limit: 10000 assertions and 2000 rules')
            rules += builtin_rules([a for a, _ in atoms] + assumed +
                                   [Atom.read(a) for r in rules for a in r['body'] + [r['head']]])
            rules_hash = digest(rules)
            checkpoint = db.execute('SELECT rules_hash,state FROM checkpoints WHERE context=? AND world=?',
                                    (context, world)).fetchone()
            if not checkpoint and world != 'base':
                checkpoint = db.execute('SELECT rules_hash,state FROM checkpoints WHERE context=? AND world=?',
                                        (context, 'base')).fetchone()
            reused = bool(checkpoint and checkpoint[0] == rules_hash)
            k = Kernel(rules, json.loads(checkpoint[1]) if reused else None, seed)
            prior_facts = len(k.atoms)
            for a, sid in atoms:
                k.add(a, {'kind': 'asserted', 'source': sid, 'premises': []})
            for a in assumed:
                k.add(a, {'kind': 'assumption', 'source': '@assumption:' + a.id, 'premises': []})
            metrics = k.run(query, budget)
            answer = k.answers(query)
            answer.update(context=context, revision=revision, world=world, query=query.data(),
                          assumptions=[a.data() for a in assumed], metrics=metrics,
                          reuse={'checkpoint': reused, 'prior_facts': prior_facts,
                                 'new_work': metrics['work']},
                          semantics='Conditional on supplied premises, interpretations and scope; not verified world truth.')
            # Source text is included only for selected proofs, avoiding replay
            # of the whole source corpus into the model's context.
            ids: set[str] = set()
            def visit(p: dict[str, Any] | None) -> None:
                if p:
                    ids.add(p['support']['source'])
                    for child in p['premises']:
                        visit(child)
            for a in answer['answers']:
                visit(a['proof']); visit(a['opposing_proof'])
            for p in answer['opposition']:
                visit(p)
            answer['sources'] = {sid: sources[sid]['evidence'] for sid in ids if sid in sources}
            answer['approximation'] = self._missing(query, k) if answer['status'] == 'unknown' else []
            answer['answer'] = self._text(answer)
            db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?)',
                       (context, world, rules_hash, json.dumps(k.s)))
            # Bound persisted overlays. Base materialization is never evicted.
            db.execute('DELETE FROM checkpoints WHERE context=? AND world != ? AND rowid NOT IN '
                       '(SELECT rowid FROM checkpoints WHERE context=? AND world != ? ORDER BY rowid DESC LIMIT 16)',
                       (context, 'base', context, 'base'))
            return answer

    @staticmethod
    def _text(answer: dict[str, Any]) -> str:
        status = answer['status']
        message = {'supported': 'Hay apoyo en las premisas para la consulta.',
                   'refuted': 'Las premisas apoyan la negación de la consulta.',
                   'conflict': 'Hay apoyo tanto a favor como en contra.',
                   'unknown': 'No hay evidencia suficiente entre los hechos alcanzados.'}[status]
        if answer['assumptions']:
            message = 'Bajo los supuestos indicados: ' + message
        if not answer['metrics']['complete']:
            message += ' La búsqueda está incompleta; podés continuar la misma consulta.'
        return message

    @staticmethod
    def _missing(query: Atom, k: Kernel) -> list[dict[str, Any]]:
        # Bounded backward explanation, not a probability or causal assertion.
        # Suggestions retain required conditions and require forward validation.
        if query.variables:
            return []
        out: list[dict[str, Any]] = []
        for r in k.rules:
            binding = unify(Atom.read(r['head']), query)
            if binding is None:
                continue
            body = [Atom.read(a).bind(binding) for a in r['body']]
            if any(a.variables for a in body):
                continue
            missing = [a for a in body if a.id not in k.atoms]
            if missing and query not in missing:
                out.append({'kind': 'conditional_candidate', 'rule': r['id'], 'source': r['source'],
                            'required': [a.data() for a in missing], 'promoted': False,
                            'known_opposition': [a.data() for a in missing if a.opposite().id in k.atoms],
                            'next_step': 'Obtain evidence for these conditions or test them in an assumption world; no causal/probability claim.'})
            if len(out) == 10:
                break
        return out
