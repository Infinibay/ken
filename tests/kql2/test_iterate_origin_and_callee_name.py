"""The iterate `origin:` and call `name: $role` primitives, end to end.

A local batch a lookup filled is walkable when the pattern names the call that filled
it; the callee spelling a call dispatches to can be reported and whitelisted; and a
pattern that names a local by its producing call still reaches the place that call
filled.
"""
import pytest

from ken.kql2.service import search
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, query_registry
from ken.structural.semantic import link_project

SOURCE = '''class Work:
 def __init__(self, store):
  self.changes={}
  self.store=store
 def register(self, entity, key):
  batch=self.changes.get(key)
  batch.append(entity)
  self.changes[key]=batch
 def commit(self):
  self.process_new()
 def process_new(self):
  batch=self.changes.get("new")
  for item in batch:
   self.store.insert(item)
'''

LOOP = '''language "kql/2";
module t;
pattern detect(out TypeDecl $unit, out Binding $item, out Call $effect, out Value $action) {
  type $unit {
    field $changes {}
    field $store {}
    method $worker {
      constructor: false;
      body {
        let $batch = call $lookup { receiver: $changes; name: ["get"]; resolution: unresolved; };
        iterate $batch as $item as $iteration {
          ORIGIN
          body {
            call on $store { name: NAME; argument $item at 0; resolution: unresolved; } as $effect;
          }
        }
      }
    }
  }
}
query results {
  use detect(unit: $unit, item: $item, effect: $effect, action: $action);
  select $unit, $item, $effect, $action;
}
'''

REGISTER = '''language "kql/2";
module t;
pattern detect(out TypeDecl $unit, out Field $changes, out Value $batch) {
  type $unit {
    field $changes {}
    method $register {
      constructor: false;
      param $entity {}
      param $key {}
      body {
        let $batch = call $lookup { receiver: $changes; name: ["get"]; resolution: unresolved; };
        insert $entity into $batch as $insertion;
        WRITE
      }
    }
  }
  where $entity != $key;
}
query results {
  use detect(unit: $unit, changes: $changes, batch: $batch);
  select $unit, $changes, $batch;
}
'''


def rows(tmp_path, query):
    (tmp_path / 'sample.py').write_text(SOURCE)
    return search(tmp_path, query, cache_mb=0)['rows']


def loop(tmp_path, origin='', name='$action in ["insert"]'):
    return rows(tmp_path, LOOP.replace('ORIGIN', origin).replace('NAME', name))


def test_named_origin_makes_a_lookup_filled_batch_walkable(tmp_path):
    """``origin: $lookup;`` states the provenance the entry-source analysis infers."""
    assert len(loop(tmp_path, origin='origin: $lookup;')) == 1


def test_a_walk_without_its_origin_is_refused(tmp_path):
    """A local batch whose fill is not stated has no entry source, so the walk fails."""
    assert loop(tmp_path) == []


def test_the_callee_name_is_reported_and_whitelisted(tmp_path):
    assert len(loop(tmp_path, origin='origin: $lookup;', name='$action in ["insert"]')) == 1
    assert loop(tmp_path, origin='origin: $lookup;', name='$action in ["delete"]') == []


def structural_matches(query, language='python'):
    """Run the pattern over the fixture through the structural rule path."""
    graph = link_project([lower_source(SOURCE, language, 'sample')])
    saved = SavedRule(id='p.fixture', name='fixture', query=query, source=query,
                      query_language='kql/2')
    query_registry([saved])
    registry = builtin_rules()
    registry.append(saved)
    return execute_rules(graph, [saved], registry=registry)['matches']


def test_a_pattern_naming_a_local_by_its_call_still_reaches_the_place():
    """The batch is named by the lookup that produced it; the write lands in its place."""
    query = REGISTER.replace('WRITE', 'insert $batch into $changes at $key as $writeback;')
    assert len(structural_matches(query)) == 1


def test_an_indexed_write_under_the_wrong_key_is_refused():
    query = REGISTER.replace('WRITE', 'insert $batch into $changes at $entity as $writeback;')
    assert structural_matches(query) == []


def test_an_indexed_assignment_names_the_element_it_writes():
    query = REGISTER.replace('WRITE', '$changes[$key] = $batch as $writeback;')
    assert len(structural_matches(query)) == 1


def test_an_indexed_assignment_under_the_wrong_key_is_refused():
    query = REGISTER.replace('WRITE', '$changes[$entity] = $batch as $writeback;')
    assert structural_matches(query) == []
