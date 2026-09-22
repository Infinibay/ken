"""Behavioral joins must use the same request, response and lazy allocation.

The examples are parsed, never executed. Constants retain valid language syntax;
changing a relationship must reject the pattern even when its vocabulary remains.
"""
from functools import lru_cache

import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, query_graph
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project
from .catalog_matrix_support import matrix_cases, noise

LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']


@lru_cache(maxsize=1)
def registry():
    return query_registry(builtin_rules())


def source(target, language):
    return next(c.source for c in matrix_cases()
                if (c.target, c.language, c.family) == (target, language, 'canonical'))


def matches(target, language, text):
    graph = link_project([lower_source(text, language, 'correlation.' + language)])
    assert not graph.diagnostics, graph.diagnostics
    result = Engine(query_graph(graph), registry(), QueryBudget(timeout_ms=3000), 'strict').execute(registry()[target])
    assert result['complete'], result
    return bool(result['matches'])


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('replace_index', [0, 1, 'both'])
def test_adapter_indexed_arguments_must_come_from_its_request(language, replace_index):
    target = 'adapter#functional-adapter'
    text = source(target, language)
    literal = {'python': '[3, 5]', 'javascript': '[3, 5]', 'typescript': '[3, 5]',
               'java': 'new int[]{3, 5}', 'csharp': 'new int[]{3, 5}',
               'cpp': 'std::vector<int>{3, 5}', 'go': '[]int{3, 5}', 'rust': '[3, 5]'}[language]
    for index in ([0, 1] if replace_index == 'both' else [replace_index]):
        old = f'pair[{index}]'
        assert old in text
        text = text.replace(old, f'{literal}[{index}]')
    assert not matches(target, language, text)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('target', ['adapter#functional-adapter', 'proxy#remote-subject', 'proxy#lazy-subject'])
def test_correlated_algorithms_survive_twenty_independent_statements(target, language):
    assert matches(target, language, noise(source(target, language), language, 20))


@pytest.mark.parametrize('language', LANGUAGES)
def test_remote_proxy_must_decode_the_response_of_its_transport(language):
    target = 'proxy#remote-subject'
    text = source(target, language)
    previous = '&response' if language == 'rust' else 'response'
    replacement = '0' if language == 'cpp' else '"unrelated"'
    # Edit only the decoder argument, leaving the transport/encoder fully intact.
    old = '(' + previous + ')'
    assert old in text
    text = text.replace(old, '(' + replacement + ')')
    assert not matches(target, language, text)


@pytest.mark.parametrize('language', LANGUAGES)
def test_remote_proxy_rejects_response_overwritten_before_decoding(language):
    target = 'proxy#remote-subject'
    text = source(target, language)
    literal = '0' if language == 'cpp' else 'String::new()' if language == 'rust' else '"unrelated"'
    if language == 'python':
        text = text.replace('        return self.codec.decode(response)',
                            f'        response = {literal}\n        return self.codec.decode(response)')
    else:
        text = text.replace('const response =', 'let response =').replace('let response =', 'let mut response =' if language == 'rust' else 'let response =')
        # The final return in these sources is the decoder in the proxy method.
        position = text.rfind('return ')
        assert position >= 0
        text = text[:position] + f'response = {literal};\n' + text[position:]
    assert text != source(target, language)
    assert not matches(target, language, text)


@pytest.mark.parametrize('language', LANGUAGES)
def test_callable_decorator_needs_an_added_responsibility(language):
    target = 'decorator#callable-wrapper'
    text = source(target, language)
    # Strip the explicit tracing effects, preserving capture, arguments and return.
    markers = ('print(', 'println(', 'println!(', 'console.log(',
               'System.out.println(', 'Console.WriteLine(', 'std::puts(')
    transparent = '\n'.join(line for line in text.splitlines()
                            if not any(marker in line for marker in markers)) + '\n'
    assert text != transparent
    assert not matches(target, language, transparent)


@pytest.mark.parametrize('helpers', [('increment', 'double', 'calculate'), ('load', 'save', 'run')])
def test_function_composition_alone_does_not_establish_a_facade(helpers):
    first, second, entry = helpers
    text = (f'def {first}(x): return x + 1\n'
            f'def {second}(x): return x * 2\n'
            f'def {entry}(x): return {second}({first}(x))\n')
    assert not matches('facade#module-surface', 'python', text)


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.parametrize('child_method,expected', [('run', True), ('reset', False)])
def test_recursive_composite_calls_the_uniform_component_operation(language, child_method, expected):
    text = {
        'python': f'''class Component:
 def run(self): pass
 def reset(self): pass
class Branch(Component):
 def __init__(self, children: list[Component]): self.children: list[Component] = children
 def run(self):
  for child in self.children: child.{child_method}()
''',
        'java': f'''import java.util.List;
class Component {{ void run() {{}} void reset() {{}} }}
class Branch extends Component {{
 List<Component> children;
 void run() {{ for (Component child : children) {{ child.{child_method}(); }} }}
}}
''',
        'typescript': f'''class Component {{ run() {{}} reset() {{}} }}
class Branch extends Component {{
 children: Array<Component>;
 run() {{ for (const child of this.children) {{ child.{child_method}(); }} }}
}}
''',
    }[language]
    assert matches('composite#recursive-contract', language, text) is expected


@pytest.mark.parametrize('parameter', ['T', 'U'])
def test_generic_bridge_rejects_an_unrelated_type_regardless_of_parameter_spelling(parameter):
    text = f'''interface Driver {{ run(): number; }}
class Box<T extends Driver> {{
 constructor(private driver: T) {{}}
 run() {{ return this.driver.run(); }}
}}
class Unrelated<{parameter}> {{}}
'''
    assert not matches('bridge#generic-composition', 'typescript', text)


def test_generic_refinement_may_rename_its_implementation_parameter():
    text = '''interface Driver { run(): number; }
class Box<T extends Driver> {
 constructor(protected driver: T) {}
 run() { return this.driver.run(); }
}
class Refined<U extends Driver> extends Box<U> {}
'''
    assert matches('bridge#generic-composition', 'typescript', text)


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.parametrize('early_return', [True, False])
def test_proxy_guard_can_reject_early_but_unconditional_forwarding_is_insufficient(language, early_return):
    guard = 'if not allowed: return None' if early_return else 'if not allowed: print("rejected")'
    sources = {
        'python': f'''class Contract:
 def run(self): pass
class Subject(Contract):
 def __init__(self, inner: Contract): self.inner = inner
 def run(self, allowed):
  {guard}
  return self.inner.run()
''',
        'java': '''class Contract { int run(boolean allowed) { return 0; } }
class Subject extends Contract {
 Contract inner;
 int run(boolean allowed) {
  GUARD
  return inner.run(allowed);
 }
}
'''.replace('GUARD', 'if (!allowed) { return 0; }' if early_return else 'if (!allowed) { System.out.println("rejected"); }'),
        'typescript': '''class Contract { run(allowed: boolean) { return 0; } }
class Subject extends Contract {
 inner: Contract;
 run(allowed: boolean) {
  GUARD
  return this.inner.run(allowed);
 }
}
'''.replace('GUARD', 'if (!allowed) { return 0; }' if early_return else 'if (!allowed) { console.log("rejected"); }'),
    }
    assert matches('proxy#guarded-access', language, sources[language]) is early_return


def test_module_facade_can_coordinate_functions_owned_by_different_modules():
    # Multi-file resolution proves the subsystem boundaries, even without classes.
    sources = [('reader.py', 'def fetch(x): return x\n'),
               ('writer.py', 'def store(x): return x\n'),
               ('entry.py', 'from reader import fetch\nfrom writer import store\ndef run(x): return store(fetch(x))\n')]
    graph = link_project([lower_source(text, 'python', path) for path, text in sources])
    assert not graph.diagnostics
    target = 'facade#module-surface'
    result = Engine(query_graph(graph), registry(), QueryBudget(timeout_ms=3000), 'strict').execute(registry()[target])
    assert result['complete'], result
    assert len(result['matches']) == 1


@pytest.mark.parametrize('language', LANGUAGES)
def test_lazy_proxy_cannot_discard_its_allocation_and_store_null(language):
    target = 'proxy#lazy-subject'
    text = source(target, language)
    old, new = {
        'python': ('self.subject = RealSubject()', 'RealSubject(); self.subject = None'),
        'javascript': ('this.subject = new RealSubject()', 'new RealSubject(); this.subject = null'),
        'typescript': ('this.subject = new RealSubject()', 'new RealSubject(); this.subject = null'),
        'java': ('subject = new RealSubject()', 'new RealSubject(); subject = null'),
        'csharp': ('subject = new RealSubject()', 'new RealSubject(); subject = null'),
        'cpp': ('subject = new RealSubject()', 'new RealSubject(); subject = nullptr'),
        'go': ('p.subject = &RealSubject{}', '_ = &RealSubject{}; p.subject = nil'),
        'rust': ('self.subject = Some(RealSubject { })', 'let _ = RealSubject { }; self.subject = None'),
    }[language]
    assert old in text
    assert not matches(target, language, text.replace(old, new))


@pytest.mark.parametrize('language', LANGUAGES)
def test_callable_decorator_can_transform_the_returned_result_without_an_extra_call(language):
    import re
    target = 'decorator#callable-wrapper'
    text = source(target, language)
    markers = ('print(', 'println(', 'println!(', 'console.log(',
               'System.out.println(', 'Console.WriteLine(', 'std::puts(')
    lines = [line for line in text.splitlines() if not any(marker in line for marker in markers)]
    assignment = next(line for line in lines if re.search(r'\bresult\s*(?::=|=)', line))
    delegated = re.split(r'\bresult\s*(?::=|=)\s*', assignment, maxsplit=1)[1].rstrip(';')
    result = []
    for line in lines:
        if line == assignment:
            continue
        if re.fullmatch(r'\s*(?:return\s+)?result;?\s*', line):
            end = '' if language in {'python', 'go'} else ';'
            line = re.match(r'\s*', line)[0] + f'return {delegated} + 1{end}'
        result.append(line)
    assert matches(target, language, '\n'.join(result) + '\n')
