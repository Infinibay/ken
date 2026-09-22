from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.structural.model import IR, Entity
from ken.structural_store import Store


def test_missing_parameter_classification_does_not_certify_empty_domain():
    p = compile(parse('language "kql/2"; module t; query q { select count(Parameter $p | true | $p); }'))
    with Store() as store:
        ir = IR('a','python',entities={'p':Entity('p','PARAMETER','p','a',1,1)})
        unit = store.put_unit('u',ir,'h','v')
        result = execute(p,store,store.publish([unit],expected_parent=None))
        assert result.rows == [] and result.unknown_candidates == 1


def test_indexed_name_prefilter_preserves_unknown_candidates():
    p = compile(parse('language "kql/2"; module t; query q { class $c { name: "A"; } select $c; }'))
    with Store() as store:
        ir = IR('a','python',entities={'c':Entity('c','CLASS','A','a',1,1)})
        unit = store.put_unit('u',ir,'h','v')
        # The storage schema explicitly admits an unavailable name.
        store.db.execute('UPDATE k2_nodes SET name=NULL')
        snapshot = store.publish([unit],expected_parent=None)
        indexed = execute(p,store,snapshot)
        reference = execute(p,store,snapshot,reference=True)
        assert indexed.rows == reference.rows == []
        assert indexed.unknown_candidates == reference.unknown_candidates == 1


def test_optimized_negative_name_filter_preserves_unknown():
    p = compile(parse('language "kql/2"; module t; query q { not exists { class $c { name: "A"; } } select 1; }'))
    with Store() as store:
        ir = IR('a','python',entities={'c':Entity('c','CLASS','A','a',1,1)})
        unit = store.put_unit('u',ir,'h','v')
        store.db.execute('UPDATE k2_nodes SET name=NULL')
        result = execute(p,store,store.publish([unit],expected_parent=None))
        assert result.rows == [] and result.unknown_candidates == 1
