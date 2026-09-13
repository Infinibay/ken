"""Deferred change batches require registration, item flow and shared persistence."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']


def source(language):
    if language == 'python':
        return '''class Work:
 def __init__(self, store):
  self.changes={}
  self.store=store
 def register(self, entity, key):
  batch=self.changes.get(key)
  if batch is None: batch=[]
  batch.append(entity)
  self.changes[key]=batch
 def commit(self):
  self.process_new()
  self.process_old()
 def process_new(self):
  batch=self.changes.get("new")
  for item in batch:
   self.store.insert(item)
 def process_old(self):
  batch=self.changes.get("old")
  for item in batch:
   self.store.delete(item)
'''
    if language in {'javascript', 'typescript'}:
        return '''class Work {
 constructor(store){this.store=store;this.changes=new Map();}
 register(entity,key){let batch=this.changes.get(key);if(batch==null){batch=[];}
 batch.push(entity);this.changes.set(key,batch);}
 commit(){this.process_new();this.process_old();}
 process_new(){const batch=this.changes.get("new");for(const item of batch){this.store.insert(item);}}
 process_old(){const batch=this.changes.get("old");for(const item of batch){this.store.delete(item);}}
}'''
    if language == 'java':
        return '''import java.util.Map; import java.util.List; import java.util.ArrayList;
class Work {
 Map<String,List<Item>> changes; Store store;
 void register(Item entity,String key){var batch=changes.get(key);if(batch==null){batch=new ArrayList<Item>();}
 batch.add(entity);changes.put(key,batch);}
 void commit(){process_new();process_old();}
 void process_new(){var batch=changes.get("new");for(var item:batch){store.insert(item);}}
 void process_old(){var batch=changes.get("old");for(var item:batch){store.delete(item);}}
}'''
    return '''using System.Collections.Generic;
class Work {
 Dictionary<string,List<Item>> changes; Store store;
 void register(Item entity,string key){var batch=changes.GetValueOrDefault(key);if(batch==null){batch=new List<Item>();}
 batch.Add(entity);changes[key]=batch;}
 void commit(){process_new();process_old();}
 void process_new(){var batch=changes.GetValueOrDefault("new");foreach(var item in batch){store.insert(item);}}
 void process_old(){var batch=changes.GetValueOrDefault("old");foreach(var item in batch){store.delete(item);}}
}'''


def run(text, language, operation=False):
    graph = link_project([lower_source(text, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    name = 'persistence.unit-of-work' + ('.keyed_flush' if operation else '')
    result = execute_rules(graph, [named_rule(name, registry)], registry=registry)
    assert result['complete']
    return graph, result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_keyed_change_set(language):
    graph, matches = run(source(language), language)
    assert len(matches) == 1
    assert {k:graph.entities[v].name for k,v in matches[0]['bindings'].items()} == {
        '$unit':'Work', '$flush':'commit', '$store':'store'}


@pytest.mark.parametrize('language', LANGUAGES)
def test_domain_names_are_not_the_detector(language):
    text = source(language)
    for old,new in [('Work','Session'), ('changes','pending'), ('commit','apply'), ('register','track'), ('process_new','first'), ('process_old','second')]:
        text = text.replace(old,new)
    assert run(text, language)[1]


@pytest.mark.parametrize('language', LANGUAGES)
def test_public_flush_operation_keeps_workers_items_and_actions(language):
    graph, matches = run(source(language), language, operation=True)
    assert len(matches) == 2
    assert {m['bindings']['$action'] for m in matches} == {'insert','delete'}
    assert {graph.entities[m['bindings']['$worker']].name for m in matches} == {'process_new','process_old'}


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['other-item', 'other-buffer', 'other-store', 'one-action',
                                    'not-persistence', 'no-coordinator', 'no-registration',
                                    'wrong-key', 'wrong-writeback', 'registered-key-not-entity'])
def test_unit_of_work_near_misses(language, mutation):
    text = source(language)
    if mutation == 'other-item':
        text = text.replace('insert(item)', 'insert(other)')
    elif mutation == 'other-buffer':
        text = text.replace('changes.get("new")', 'other.get("new")').replace('changes.GetValueOrDefault("new")', 'other.GetValueOrDefault("new")')
    elif mutation == 'other-store':
        text = text.replace('store.insert', 'other.insert')
    elif mutation == 'one-action':
        text = text.replace('store.delete', 'store.insert')
    elif mutation == 'not-persistence':
        text = text.replace('store.insert', 'store.log')
    elif mutation == 'no-coordinator':
        text = text.replace('  self.process_new()\n', '').replace('this.process_new();','').replace('process_new();','')
    elif mutation == 'no-registration':
        text = text.replace('batch.append(entity)', 'pass').replace('batch.push(entity);','').replace('batch.add(entity);','').replace('batch.Add(entity);','')
    elif mutation == 'wrong-key':
        text = text.replace('changes[key]=batch', 'changes[entity]=batch').replace('changes.set(key,batch)', 'changes.set(entity,batch)').replace('changes.put(key,batch)', 'changes.put(entity,batch)')
    elif mutation == 'wrong-writeback':
        text = text.replace('changes[key]=batch', 'changes[key]=other').replace('changes.set(key,batch)', 'changes.set(key,other)').replace('changes.put(key,batch)', 'changes.put(key,other)')
    else:
        text = text.replace('append(entity)', 'append(key)').replace('push(entity)', 'push(key)').replace('add(entity)', 'add(key)').replace('Add(entity)', 'Add(key)')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_batch_overwritten_before_effect_is_not_a_flush(language):
    text = source(language)
    text = text.replace('  for item', '  batch=other\n  for item') if language == 'python' else text.replace(';for(', ';batch=other;for(').replace(';foreach(', ';batch=other;foreach(')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_rebinding_iterated_entity_is_not_entity_flow(language):
    text = source(language)
    text = text.replace('   self.store.insert', '   item=other\n   self.store.insert') if language == 'python' else text.replace('store.insert(item)', 'store.insert(item=other)')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_pascal_case_persistence_api(language):
    assert run(source(language).replace('.insert(', '.Insert(').replace('.delete(', '.Delete('), language)[1]
