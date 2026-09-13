"""Language-specific variants and near misses outside the shared object matrix."""
import pytest
from ken.structural.catalog import catalog
from ken.structural.rules import builtin_rules, named_rule, execute_rules
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from .test_gof_executable import evaluate


@pytest.mark.parametrize('imports,decorator', [
 ('from contextlib import contextmanager', 'contextmanager'),
 ('from contextlib import contextmanager as scope', 'scope'),
 ('import contextlib', 'contextlib.contextmanager'),
 ('import contextlib as ctx', 'ctx.contextmanager'),
 ('from contextlib import asynccontextmanager as scope', 'scope'),
])
def test_contextlib_generators_are_not_iterator_results(imports, decorator):
    prefix = 'async ' if 'asynccontextmanager' in imports else ''
    source = f'{imports}\n@{decorator}\n{prefix}def scope_body():\n yield 1\n'
    assert not evaluate(source, 'python', 'iterator')


def test_shadowed_contextmanager_does_not_apply_library_model():
    source = '''
from contextlib import contextmanager

def contextmanager(f): return f

@contextmanager
def items():
 yield 1
'''
    assert evaluate(source, 'python', 'iterator')


@pytest.mark.parametrize('language,source', [
 ('python', 'async def items():\n yield 1\n'),
 ('javascript', 'async function* items(){ yield 1; }'),
 ('typescript', 'async function* items():AsyncGenerator<number>{ yield 1; }'),
 ('csharp', 'class Items { System.Collections.Generic.IEnumerable<int> Values(){yield return 1;} }'),
])
def test_suspension_variants(language, source):
    assert evaluate(source, language, 'iterator')


@pytest.mark.parametrize('outer_yields', [False, True])
def test_csharp_local_iterator_has_its_own_owner(outer_yields):
    outer_return = 'yield return 2;' if outer_yields else 'return true;'
    outer_type = 'IEnumerable<int>' if outer_yields else 'bool'
    source = f'''using System.Collections.Generic;
class Conversion {{
 {outer_type} Convert() {{
  IEnumerable<int> Elements() {{ yield return 1; }}
  {outer_return}
 }}
}}'''
    graph = link_project([lower_source(source, 'csharp', 'conversion.cs')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('gof.iterator', registry)], registry=registry)
    assert result['complete']
    names = {graph.entities[v].name for m in result['matches'] for v in m['bindings'].values()}
    assert names == ({'Elements', 'Convert'} if outer_yields else {'Elements'})
    local = next(e.id for e in graph.entities.values() if e.kind == 'CALLABLE' and e.name == 'Elements')
    assert not any(f.relation == 'HAS_METHOD' and f.object == local for f in graph.facts)


@pytest.mark.parametrize('language,source', [
 ('javascript', '''class Stream {
 constructor(){this.listeners=[];}
 subscribe(listener){this.listeners.push(listener);}
 emit(event){for(const listener of this.listeners){listener(event);}}
 }'''),
 ('python', '''class Stream:
 def __init__(self): self.listeners=[]
 def subscribe(self, listener): self.listeners.append(listener)
 def emit(self, event):
  for listener in self.listeners: listener(event)
 '''),
])
def test_callback_observer_and_unrelated_callback_negative(language, source):
    assert evaluate(source, language, 'observer')
    assert not evaluate(source.replace('listener(event)', 'unrelated(event)'), language, 'observer')


def test_next_builtin_model_does_not_accept_shadowed_parameter():
    source = '''
class Cursor:
 def __init__(self, values): self.values=values
 def __iter__(self): return self
 def __next__(self, next): return next(self.values)
'''
    assert not evaluate(source, 'python', 'iterator')


def test_every_catalogue_entry_has_executable_root_and_variant():
    registry = builtin_rules()
    rules = [r for r in registry if 'gof' in r.collections]
    assert len(rules) == 23
    for rule in rules:
        assert rule.query.startswith('query ')
        assert any(v['status']=='ready' and v.get('query') for v in rule.variants)
        rule.validate()
        assert named_rule('gof.'+rule.id, registry)
    assert all(item['query'].startswith('query ') for item in catalog())


def test_legacy_observer_requires_explicit_namespace():
    graph = link_project([lower_source('''
class Files:
 def __init__(self): self.files=[]
 def close(self):
  for file in self.files: file.close()
''', 'python', 'files.py')])
    registry = builtin_rules()
    ordinary = next(r for r in registry if r.id=='observer')
    historical = named_rule('legacy.gof.observer', registry)
    result = execute_rules(graph, [ordinary,historical], registry=registry)
    assert result['complete']
    assert {m['id'] for m in result['matches']} == {'legacy.gof.observer'}


DIRECTOR = '''
class Product: pass
class Parts:
 def first(self, value): self.x=value
 def second(self, value): self.y=value
 def finish(self): return Product()
class Director:
 def run(self, parts: Parts, other: Parts):
  parts.first(1)
  parts.second(2)
  return parts.finish()
'''


GO_MAP_OBSERVER = '''package sample
type Listener interface { Receive(int) }
type Hub struct { listeners map[Listener]Listener; others map[Listener]Listener }
func (h *Hub) Add(listener Listener) { h.listeners[listener] = listener }
func (h *Hub) Notify(event int) {
 for key, value := range h.listeners { key.Receive(event); _ = value }
}
'''


def test_go_map_keys_observer():
    assert evaluate(GO_MAP_OBSERVER, 'go', 'observer')
    assert evaluate(GO_MAP_OBSERVER.replace('Listener', 'Client').replace('Hub', 'Registry'), 'go', 'observer')


@pytest.mark.parametrize('before,after', [
 ('key.Receive(event)', 'value.Receive(event)'),
 ('range h.listeners', 'range h.others'),
 ('h.listeners[listener] = listener', 'h.others[listener] = listener'),
 ('h.listeners[listener] = listener', 'delete(h.listeners, listener)'),
 ('h.listeners[listener] = listener', '_ = h.listeners[listener]'),
])
def test_go_map_observer_requires_registered_keys_of_same_map(before, after):
    assert not evaluate(GO_MAP_OBSERVER.replace(before, after), 'go', 'observer')


def test_director_correlates_all_steps_and_finish_to_same_receiver():
    assert evaluate(DIRECTOR, 'python', 'builder')
    assert not evaluate(DIRECTOR.replace('parts.second(2)', 'other.second(2)'), 'python', 'builder')
    assert not evaluate(DIRECTOR.replace('return parts.finish()', 'return other.finish()'), 'python', 'builder')


def test_constructor_alone_is_not_a_builder_step():
    source = '''
class Product:
 def __init__(self, value): self.value=value
class Copyable:
 def __init__(self, value): self.value=value
 def finish(self): return Product(self.value)
'''
    assert not evaluate(source, 'python', 'builder')


def test_local_work_in_helpers_is_not_builder_state():
    source = '''
class Result: pass
class Service:
 def parse(self): data=[]
 def validate(self): valid=True
 def finish(self): return Result()
 def run(self):
  self.parse()
  self.validate()
  return self.finish()
'''
    assert not evaluate(source, 'python', 'builder')
