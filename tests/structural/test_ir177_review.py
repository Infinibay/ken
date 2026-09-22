"""Independent adversarial review of IR 1.77's execution/write evidence.

A closed write inventory must count every modeled binding site or explicitly
withhold a count. Execution evidence is local and conservative: missing control
analysis must not turn a proved dead definition-time expression into possible.
"""
from __future__ import annotations

from collections import Counter

import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def graph(source, language='python'):
    if language == 'python':
        compile(source, '<ir177-review>', 'exec')
    result = link_project([lower_source(source, language, 'review.' + language)])
    assert not result.diagnostics, result.diagnostics
    return result


def facts(ir, relation, subject=None):
    return [f for f in ir.facts if f.relation == relation and (subject is None or f.subject == subject)]


def call_execution(ir, name):
    calls = {f.subject for f in facts(ir, 'CALLEE_NAME') if f.object == name}
    assert calls, name
    return {f.attrs.get('execution') for f in facts(ir, 'HAS_CALL') if f.object in calls}


def binding_inventory(ir, name):
    bindings = [e.id for e in ir.entities.values() if e.kind == 'STORAGE' and e.name == name]
    assert len(bindings) == 1, bindings
    return ({f.object for f in facts(ir, 'STORAGE_WRITE_STATUS', bindings[0])},
            {f.object for f in facts(ir, 'STORAGE_WRITE_COUNT', bindings[0])})


@pytest.mark.parametrize('language,source', [
    ('python', 'def f():\n return\n dead()\n'),
    ('javascript', 'function f(){ return; dead(); }'),
    ('typescript', 'function f():void { return; dead(); }'),
    ('java', 'class C { void f(){ return; dead(); } }'),
    ('csharp', 'class C { void F(){ return; Dead(); } }'),
    ('cpp', 'void f(){ return; dead(); }'),
    ('go', 'package p\nfunc f(){ return; dead() }\n'),
    ('rust', 'fn f(){ return; dead(); }'),
])
def test_calls_after_unconditional_return_are_retained_but_dead(language, source):
    ir = graph(source, language)
    name = 'Dead' if language == 'csharp' else 'dead'
    assert call_execution(ir, name) == {'unreachable'}
    assert facts(ir, 'SYNTAX_PARENT'), 'Raw syntax must remain searchable'


@pytest.mark.parametrize('abrupt', ['break', 'continue'])
def test_loop_exit_only_kills_its_own_statement_suffix(abrupt):
    ir = graph(f'''def f(values):
 for item in values:
  {abrupt}
  dead()
 live()
''')
    assert call_execution(ir, 'dead') == {'unreachable'}
    assert call_execution(ir, 'live') == {'possible'}


def test_return_in_one_branch_does_not_kill_the_sibling_or_following_code():
    ir = graph('''def f(flag):
 if flag:
  return
  dead()
 else:
  sibling()
 following()
''')
    assert call_execution(ir, 'dead') == {'unreachable'}
    assert call_execution(ir, 'sibling') == {'possible'}
    assert call_execution(ir, 'following') == {'possible'}


def test_return_in_nested_function_does_not_kill_enclosing_function():
    ir = graph('''def outer():
 def inner():
  return
  dead()
 live()
 return inner
''')
    assert call_execution(ir, 'dead') == {'unreachable'}
    assert call_execution(ir, 'live') == {'possible'}


@pytest.mark.parametrize('definition', [
    ' class C:\n  dead()\n',
    ' def inner(value=dead()):\n  pass\n',
])
def test_dead_definition_time_calls_do_not_become_possible_at_owner_boundary(definition):
    ir = graph('def outer():\n return\n' + definition)
    assert call_execution(ir, 'dead') <= {'unreachable', 'unknown'}


@pytest.mark.parametrize('language,source', [
    ('python', 'shared=0\nother=0\nshared,other=1,2\n'),
    ('javascript', 'let shared=0; let other=0; ({shared,other}={shared:1,other:2});'),
    ('typescript', 'let shared=0; let other=0; [shared,other]=[1,2];'),
])
def test_destructuring_cannot_leave_a_closed_single_write_inventory(language, source):
    ir = graph(source, language)
    for binding in ['shared', 'other']:
        status, counts = binding_inventory(ir, binding)
        assert (status, counts) in [({'supported'}, {'2'}), ({'unsupported'}, set())]


@pytest.mark.parametrize('language,source', [
    ('python', 'shared=0\nfor shared in [1,2]:\n pass\n'),
    ('javascript', 'let shared=0; for(shared in {a:1}) {}'),
    ('typescript', 'let shared=0; for(shared of [1,2]) {}'),
])
def test_loop_binding_sites_are_counted_or_withheld(language, source):
    status, counts = binding_inventory(graph(source, language), 'shared')
    assert (status, counts) in [({'supported'}, {'2'}), ({'unsupported'}, set())]


def test_module_captured_explicit_write_is_included():
    status, counts = binding_inventory(graph('let shared=0; function replace(){ shared=1; }', 'javascript'), 'shared')
    assert status == {'supported'}
    assert counts == {'2'}


def test_python_nonlocal_binding_write_withholds_closed_inventory():
    ir = graph('''def outer():
 shared=0
 def replace():
  nonlocal shared
  shared=1
 return replace
''')
    assert not facts(ir, 'STORAGE_WRITE_COUNT')
    assert all(f.object == 'unsupported' for f in facts(ir, 'STORAGE_WRITE_STATUS'))


def test_dead_explicit_write_still_counts_as_a_source_occurrence():
    ir = graph('let shared=0; function replace(){ return; shared=1; }', 'javascript')
    assert binding_inventory(ir, 'shared') == ({'supported'}, {'2'})


def test_rust_wildcard_keeps_rhs_calls_without_inventing_an_underscore_binding():
    ir = graph('fn f(){ let _ = change_state(); after(); }', 'rust')
    assert call_execution(ir, 'change_state') == {'possible'}
    assert call_execution(ir, 'after') == {'possible'}
    assert any(op.kind == 'DISCARD' for op in ir.operations)
    assert not any(e.kind in {'STORAGE', 'PARAMETER'} and e.name == '_' for e in ir.entities.values())
    discarded = facts(ir, 'DISCARDS_RESULT')
    calls = {f.subject for f in facts(ir, 'CALLEE_NAME') if f.object == 'change_state'}
    assert any(f.object in calls for f in discarded)


def test_nested_function_return_does_not_override_outer_finally():
    ir = graph('''def f():
 try:
  return 1
 finally:
  def deferred():
   return 2
''')
    assert {f.object for f in facts(ir, 'TRY_EXIT_STATUS')} == {'no-explicit-override'}


def test_explicit_return_in_finally_can_override_pending_return():
    ir = graph('''def f():
 try:
  return 1
 finally:
  return 2
''')
    assert {f.object for f in facts(ir, 'TRY_EXIT_STATUS')} == {'may-override'}


def test_unreferenced_fields_do_not_materialize_every_method_field_pair():
    n = 40
    source = ('class Wide:\n' + ''.join(f' field{i}: int = 0\n' for i in range(n))
              + ''.join(f' def method{i}(self): pass\n' for i in range(n)))
    ir = graph(source)
    sizes = Counter(f.relation for f in ir.facts)
    # Deterministic graph-size bound, not a timing assertion. No method touches a
    # field; a complete cross product has no source use to justify its storage.
    assert sizes['BINDING_WRITE_COUNT'] <= n * 4, sizes
    assert sizes['UNREASSIGNED_BINDING'] <= n * 4, sizes


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_hoisted_function_defaults_execute_when_called_before_their_declaration(language):
    ir = graph('function outer(){ return deferred(); function deferred(value=initialize()){ return value; }}', language)
    assert call_execution(ir, 'initialize') == {'possible'}


@pytest.mark.parametrize('source', [
    'shared=1\nwith context() as shared:\n pass\n',
    'shared=1\ntry:\n risky()\nexcept Exception as shared:\n pass\n',
])
def test_python_context_and_exception_targets_invalidate_single_write_claim(source):
    status, counts = binding_inventory(graph(source), 'shared')
    # Exception bindings are additionally deleted at handler exit. Unsupported
    # is preferable to inventing an exact write count without that model.
    assert status == {'unsupported'} or counts != {'1'}
    assert status != {'unsupported'} or not counts


def test_previous_loop_binding_replacement_blocks_entry_source_evidence():
    ir = graph('''def consume(queue, replacements):
 for queue in replacements:
  pass
 for action in queue:
  action()
''')
    queue = next(e.id for e in ir.entities.values() if e.kind == 'PARAMETER' and e.name == 'queue')
    assert any(f.object == queue for f in facts(ir, 'ITERATION_BINDING'))
    assert not any(f.object == queue for f in facts(ir, 'ITERATION_ENTRY_SOURCE'))


def test_decorator_can_replace_a_scalar_returning_function_with_a_callable_factory():
    source = '''def decorate(function):
 def replacement():
  return lambda value: value
 return replacement

@decorate
def adapt():
 return 42

def factory():
 return adapt()
'''
    ir = graph(source)
    calls = {f.subject for f in facts(ir, 'CALLEE_NAME') if f.object == 'adapt'}
    assert calls
    assert not any(f.subject in calls and f.object == 'scalar' for f in facts(ir, 'CALL_RESULT_KIND'))


def test_nominal_base_target_does_not_prove_scalar_virtual_dispatch_result():
    ir = graph('''class Base:
 def adapt(self): return 42
class Derived(Base):
 def adapt(self): return lambda value: value

def factory(obj: Base):
 return obj.adapt()
''')
    assert facts(ir, 'OVERRIDES')
    assert not any(f.object == 'scalar' for f in facts(ir, 'CALL_RESULT_KIND'))


def test_direct_scalar_function_still_has_scalar_result_evidence():
    ir = graph('def calculate():\n return 42\ndef invoke():\n return calculate()\n')
    calls = {f.subject for f in facts(ir, 'CALLEE_NAME') if f.object == 'calculate'}
    assert any(f.subject in calls and f.object == 'scalar' for f in facts(ir, 'CALL_RESULT_KIND'))


@pytest.mark.parametrize('alias_lines,expected', [
    (' Alias = Base\n', True),
    (' Alias = Base\n Alias = Other\n', False),
    (' if flag:\n  Alias = Base\n', False),
    (' Alias = Base\n for Alias in replacements:\n  pass\n', False),
])
def test_base_input_alias_requires_preceding_unconditional_unique_binding(alias_lines, expected):
    ir = graph('def specialize(Base, Other, flag, replacements):\n' + alias_lines
               + ' class Derived(Alias): pass\n return Derived\n')
    base = next(e.id for e in ir.entities.values() if e.kind == 'PARAMETER' and e.name == 'Base')
    assert bool([f for f in facts(ir, 'BASE_INPUT') if f.object == base]) is expected


@pytest.mark.parametrize('source,expected', [
    ('function f(x){if(x===undefined){return 1;}return 2;}', True),
    ('function f(x,undefined){if(x===undefined){return 1;}return 2;}', False),
    ('function f(env,x){with(env){if(x===undefined){return 1;}return 2;}}', False),
    ('function f(x){eval("var undefined=42");if(x===undefined){return 1;}return 2;}', False),
])
def test_undefined_evidence_requires_an_unshadowed_binding(source, expected):
    assert bool(facts(graph(source, 'javascript'), 'UNDEFINED_TEST')) is expected


def test_template_call_qualifier_is_owned_by_its_method_template_not_a_sibling_parameter():
    ir = graph('''template<class P> struct Algorithm {
 template<class Q> int run(int x) { return Q::apply(x); }
};''', 'cpp')
    links = facts(ir, 'TYPE_PARAMETER_OWNER')
    assert links
    for link in links:
        assert ir.entities[link.object].kind == 'CALLABLE'
        assert ir.entities[link.object].name == 'run'


def test_dynamic_module_execution_invalidates_direct_scalar_callee_identity():
    ir = graph('''def adapt(): return 42
exec("adapt=lambda: (lambda value: value)")
def factory(): return adapt()
''')
    calls = {f.subject for f in facts(ir, 'CALLEE_NAME') if f.object == 'adapt'}
    assert calls
    assert not any(f.subject in calls and f.object == 'scalar' for f in facts(ir, 'CALL_RESULT_KIND'))
