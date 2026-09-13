"""Differential contract for lazy FactIndex versus the previous eager index."""
from concurrent.futures import ThreadPoolExecutor
import random

import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, parse, query_graph
from ken.structural.model import FactIndex, IR
from ken.structural.semantic import link_project


class EagerIndex:
    """Reference implementation retained independently for differential tests."""
    def __init__(self, ir):
        self.ir = ir
        self.by_relation, self.by_subject, self.by_object = {}, {}, {}
        for fact in ir.facts:
            self.by_relation.setdefault(fact.relation, []).append(fact)
            self.by_subject.setdefault((fact.relation, fact.subject), []).append(fact)
            self.by_object.setdefault((fact.relation, fact.object), []).append(fact)

    def rows(self, relation, subject=None, object=None):
        result = self.by_relation.get(relation, [])
        if subject is not None:
            result = self.by_subject.get((relation, subject), [])
        if object is not None:
            other = self.by_object.get((relation, object), [])
            if subject is None or len(other) < len(result):
                result = other
        return result


def sample(seed=0):
    rng = random.Random(seed)
    graph = IR('sample', 'mixed')
    for number in range(150):
        graph.add(rng.choice(['a','b','c','']), rng.choice(['R','S','T']), rng.choice(['x','y','z','']), str(number), modality='may' if number%3 == 0 else 'must')
    return graph


@pytest.mark.parametrize('seed', range(12))
def test_candidate_rows_equal_eager_reference_for_all_endpoints(seed):
    graph = sample(seed)
    lazy, eager = FactIndex(graph), EagerIndex(graph)
    selections = [(relation,subject,object) for relation in ['R','S','T','missing']
                  for subject in [None,'a','b','c','','absent'] for object in [None,'x','y','z','','absent']]
    random.Random(seed).shuffle(selections)
    for selection in selections:
        actual, expected = lazy.rows(*selection), eager.rows(*selection)
        assert [id(f) for f in actual] == [id(f) for f in expected]
    assert list(lazy.by_subject.items()) == list(eager.by_subject.items())
    assert list(lazy.by_object.items()) == list(eager.by_object.items())


def test_only_requested_relation_and_endpoint_are_indexed():
    index = FactIndex(sample())
    assert index._by_subject == index._by_object == {}
    index.rows('R')
    assert index._by_subject == index._by_object == {}
    index.rows('R', subject='a')
    assert {relation for relation,_ in index._by_subject} == {'R'}
    assert not index._by_object
    index.rows('S', object='x')
    assert {relation for relation,_ in index._by_object} == {'S'}


@pytest.mark.parametrize('materialize_first', [False,True])
def test_snapshot_excludes_graph_additions_before_and_after_lazy_build(materialize_first):
    graph = sample()
    index, eager = FactIndex(graph), EagerIndex(graph)
    if materialize_first:
        index.rows('R', 'a')
        index.by_object
    graph.add('a','R','x','late')
    graph.add('new','NEW','late')
    for relation in ['R','S','NEW']:
        assert index.rows(relation) == eager.rows(relation)
        assert index.rows(relation,'a','x') == eager.rows(relation,'a','x')
    assert index.by_subject == eager.by_subject
    assert index.by_object == eager.by_object


@pytest.mark.parametrize('side', ['subject','object'])
def test_public_materialization_preserves_bucket_identity_order_and_duplicates(side):
    graph = IR('x','mixed')
    for subject,relation,object in [('a','R','x'),('b','S','y'),('c','R','z'),('a','R','x')]:
        graph.add(subject,relation,object)
    index, eager = FactIndex(graph), EagerIndex(graph)
    bucket = index.rows('R', **{side:'a' if side=='subject' else 'x'})
    full = getattr(index, 'by_'+side)
    assert list(full.items()) == list(getattr(eager,'by_'+side).items())
    assert full[('R','a' if side=='subject' else 'x')] is bucket
    assert len(bucket) == 2  # Preserve original duplicate facts, add none.
    assert getattr(index,'by_'+side) is full
    assert index.rows('R', **{side:'a' if side=='subject' else 'x'}) is bucket


def test_combined_endpoints_choose_smaller_bucket_not_intersection_and_ties_choose_subject():
    graph = IR('x','mixed')
    for subject,object in [('a','x'),('a','y'),('b','y')]:
        graph.add(subject,'R',object)
    index = FactIndex(graph)
    assert index.rows('R','a','x') == index.rows('R',object='x')
    assert index.rows('R','b','y') == index.rows('R',subject='b')
    assert index.rows('R','a','y') is index.rows('R',subject='a')
    assert any(f.object != 'y' for f in index.rows('R','a','y'))


def test_concurrent_first_reads_do_not_duplicate_facts():
    graph = sample()
    index, eager = FactIndex(graph), EagerIndex(graph)
    work = [('R','a','x'),('S','b',None),('T',None,'z')]*30
    with ThreadPoolExecutor(max_workers=6) as pool:
        actual = list(pool.map(lambda selection:index.rows(*selection),work))
    assert actual == [eager.rows(*selection) for selection in work]
    assert index.by_subject == eager.by_subject
    assert index.by_object == eager.by_object


def test_real_source_query_outcomes_match_eager_index():
    source = '''class Product: pass
class Base:
 def make(self): pass
class Factory(Base):
 def make(self): return Product()
def use(factory:Factory): return factory.make()
'''
    graph = query_graph(link_project([lower_source(source,'python','example.py')])).ir
    query = parse('''query products {
      require $factory OVERRIDES $slot;
      require $factory RETURNS_NEW $product;
      require $creation TARGET $factory;
      emit $factory,$product,$creation;
    }''')
    lazy = Engine(FactIndex(graph),{}).execute(query)
    eager = Engine(EagerIndex(graph),{}).execute(query)
    assert lazy['matches'] == eager['matches']
    assert lazy['complete'] == eager['complete']
    assert lazy['unknown'] == eager['unknown']
    assert lazy['matches']
