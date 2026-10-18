"""Repeated semantic identities must not multiply the retained source size."""

import json

from ken.kql2.semantic_index import SemanticIndex, exceeds_allowance
from ken.structural.model import IR
from ken.structural_store import Store
from ken.structural_store.migrations import migrate, validate


def test_admission_counts_context_payloads_as_well_as_identities():
    graph = IR('sample.py', 'python')
    graph.add('f', 'ENTITY', 'CALLABLE', payload='x' * 4096)
    assert exceeds_allowance(graph, 1024, lambda: None)


def test_default_put_materializes_syntax_of_a_previously_deferred_unit(tmp_path):
    from ken.common_ast import normalize
    from ken.structural.frontend import lower_source
    from ken.structural_store.common_ast import load

    original = lower_source('def original(): return 1\n', 'python', 'sample.py')
    other = lower_source('def unrelated(): return 2\n', 'python', 'sample.py')
    with Store(tmp_path / 'store.sqlite') as store:
        unit = store.put_unit('same-key', original, 'h', 'v', include_syntax=False)
        assert not store.db.execute('SELECT 1 FROM k2_ast_units').fetchone()
        assert store.put_unit('same-key', other, 'h', 'v') == unit
        assert store.db.execute('SELECT 1 FROM k2_ast_units').fetchone()
        assert load(store, unit) == normalize(original)


def test_semantic_storage_shares_repeated_identifiers_losslessly(tmp_path):
    graph = IR('long/project/module.py', 'python')
    subject = 'long/project/module.py::' + 'owner/' * 80
    for i in range(4000):
        graph.add(subject, 'RETURN_ORIGIN', subject + str(i % 10),
                  'proof:' + str(i), modality='must', position=i)
    with Store(tmp_path / 'store.sqlite') as source:
        index = SemanticIndex.spill(source.db, 1, graph, lambda: None)
        try:
            rows = index.db.execute('SELECT subject,relation,object,context,evidence '
                                    'FROM k2_semantic_facts ORDER BY ordinal').fetchall()
            assert rows == [(f.subject, f.relation, f.object, json.dumps(f.attrs),
                             json.dumps(f.evidence)) for f in graph.facts]
            size = (index.db.execute('PRAGMA page_count').fetchone()[0]
                    * index.db.execute('PRAGMA page_size').fetchone()[0])
            raw_text = sum(len(f.subject) + len(f.object) for f in graph.facts)
            assert size < raw_text / 2
        finally:
            index.close()


def test_populated_semantic_cache_migrates_in_both_directions(tmp_path):
    with Store(tmp_path / 'store.sqlite') as store:
        migrate(store.db, 14)
        store.db.execute("INSERT INTO k2_snapshots VALUES (1,'sample','full',1)")
        store.db.execute("INSERT INTO k2_analysis VALUES (1,'[]','[]')")
        row = (1, 0, 'owner', 'CALLS', 'target', '{"possible": true}', '["proof"]')
        store.db.execute('INSERT INTO k2_semantic_facts VALUES (?,?,?,?,?,?,?)', row)
        migrate(store.db)
        assert validate(store.db) >= 15
        assert store.db.execute('SELECT * FROM k2_semantic_facts').fetchall() == [row]
        migrate(store.db, 14)
        assert validate(store.db) == 14
        assert store.db.execute('SELECT * FROM k2_semantic_facts').fetchall() == [row]
