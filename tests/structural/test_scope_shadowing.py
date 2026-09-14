"""P1.1 scope resolution: block-scoped shadowing must never be merged.

Two declarations with the same spelling in different lexical blocks of one
callable are two different bindings. The frontend now gives the shadowing
declaration its own STORAGE (keyed by the declaring block) and resolves reads
to the innermost declaration, so the branch walk can no longer merge the inner
and the outer write sets.

``return_flow`` keeps a ``shadowed-binding`` refusal as a fallback for the
declaration orders the frontend cannot separate (a nested declaration seen
before the outer one, when no callable-level binding exists yet).

``var`` (JS/TS ``variable_declaration``) is function-scoped: both declarations
really are one binding, and that behaviour is preserved. A plain assignment
inside a branch is not a declaration and stays supported.
"""
import pytest

from ken.structural import link_project, lower_source

LANGUAGES = ['java', 'javascript', 'typescript', 'csharp']


def source(language, statements):
    """Wrap statements in a callable with two external helpers.

    Names are deliberately unrelated to any GoF pattern: detection must not
    depend on the spelling of the callable or the helpers.
    """
    body = ''.join(statements)
    if language == 'java':
        return ('class Holder {'
                ' static int produce(int n){ return n; }'
                ' static int consume(int n){ return n; }'
                ' static int run(boolean flag){' + body + '}'
                '}')
    if language == 'csharp':
        return ('class Holder {'
                ' static int produce(int n){ return n; }'
                ' static int consume(int n){ return n; }'
                ' static int run(bool flag){' + body + '}'
                '}')
    if language == 'typescript':
        return ('function produce(n:number){ return n; }'
                'function consume(n:number){ return n; }'
                'function run(flag:boolean){' + body + '}')
    return ('function produce(n){ return n; }'
            'function consume(n){ return n; }'
            'function run(flag){' + body + '}')


def declaration(language, keyword):
    if language in {'javascript', 'typescript'}:
        return keyword + ' '
    return 'int '


def run_status(graph):
    callables = [e.id for e in graph.entities.values()
                 if e.kind == 'CALLABLE' and e.id.rsplit('/', 1)[-1].startswith('CALLABLE:run@')]
    assert len(callables) == 1
    status = [f for f in graph.facts
              if f.relation == 'RETURN_FLOW_STATUS' and f.subject == callables[0]]
    assert len(status) == 1
    return status[0].object, status[0].attrs.get('reason')


def argument_origins(graph):
    return [f for f in graph.facts
            if f.relation == 'ARGUMENT_ORIGIN' and 'CALLABLE:run' in f.subject]


@pytest.mark.parametrize('language', LANGUAGES)
def test_block_scoped_shadowing_resolves_to_the_innermost_declaration(language):
    """The inner declaration is a different binding; the reads must not merge."""
    decl = declaration(language, 'let')
    graph = link_project([lower_source(source(language, [
        decl + 'value = produce(1);',
        'if (flag) { ' + decl + 'value = 0; consume(value); }',
        'return consume(value);',
    ]), language, 'shadow' + language)])

    status, _ = run_status(graph)
    assert status == 'supported'

    bindings = [e.id for e in graph.entities.values()
                if e.kind == 'STORAGE' and e.name == 'value' and 'CALLABLE:run' in e.id]
    assert len(bindings) == 2
    outer = [b for b in bindings if '@' not in b.rsplit('/', 1)[-1]]
    inner = [b for b in bindings if '@' in b.rsplit('/', 1)[-1]]
    assert len(outer) == 1
    assert len(inner) == 1

    reads = {f.object: f for f in argument_origins(graph) if f.object in bindings}
    assert set(reads) == set(bindings)

    # The inner binding holds the literal; the outer one the producer result.
    assert reads[inner[0]].attrs['modality'] == 'must'
    assert reads[outer[0]].attrs['modality'] == 'must'
    assert len(reads[inner[0]].attrs['origins']) == 1
    assert len(reads[outer[0]].attrs['origins']) == 1
    inner_origin = graph.entities[reads[inner[0]].attrs['origins'][0]]
    outer_origin = graph.entities[reads[outer[0]].attrs['origins'][0]]
    assert inner_origin.kind == 'VALUE'
    assert outer_origin.kind == 'CALL'
    assert reads[inner[0]].attrs['origins'] != reads[outer[0]].attrs['origins']


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_nested_declaration_seen_first_falls_back_to_refusal(language):
    """A nested declaration before the outer one cannot be separated yet.

    The inner declaration is processed when no callable-level binding exists, so
    the frontend allocates the plain ``STORAGE`` and the outer declaration later
    reuses it. ``return_flow`` must refuse that collapsed binding instead of
    merging the two write sets.
    """
    graph = link_project([lower_source(source(language, [
        'if (flag) { let value = 0; consume(value); }',
        'let value = produce(1);',
        'return consume(value);',
    ]), language, 'order' + language)])

    status, reason = run_status(graph)
    assert status == 'unsupported'
    assert reason == 'shadowed-binding'
    assert argument_origins(graph) == []


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_function_scoped_var_redeclaration_stays_supported(language):
    """``var`` is function-scoped, so both declarations are one binding."""
    graph = link_project([lower_source(source(language, [
        'var value = produce(1);',
        'if (flag) { var value = 0; }',
        'return consume(value);',
    ]), language, 'varscope' + language)])

    status, _ = run_status(graph)
    assert status == 'supported'
    reads = [f for f in argument_origins(graph) if f.object.endswith('STORAGE:value')]
    assert len(reads) == 1
    # Both writes reach the read: the branch really can change the value.
    assert reads[0].attrs['modality'] == 'may'
    assert len(reads[0].attrs['origins']) == 2


@pytest.mark.parametrize('language', LANGUAGES)
def test_plain_reassignment_in_an_arm_is_not_shadowing(language):
    """An assignment is not a declaration: one binding, two reaching writes."""
    decl = declaration(language, 'let')
    graph = link_project([lower_source(source(language, [
        decl + 'value = produce(1);',
        'if (flag) { value = 0; }',
        'return consume(value);',
    ]), language, 'reassign' + language)])

    status, _ = run_status(graph)
    assert status == 'supported'
    reads = [f for f in argument_origins(graph) if f.object.endswith('STORAGE:value')]
    assert len(reads) == 1
    assert reads[0].attrs['modality'] == 'may'
    assert len(reads[0].attrs['origins']) == 2


@pytest.mark.parametrize('language', LANGUAGES)
def test_declared_once_and_never_redeclared_stays_must(language):
    """The single-declaration flow P1.2 already proved must keep working."""
    decl = declaration(language, 'let')
    graph = link_project([lower_source(source(language, [
        decl + 'value = produce(1);',
        'return consume(value);',
    ]), language, 'single' + language)])

    status, _ = run_status(graph)
    assert status == 'supported'
    reads = [f for f in argument_origins(graph) if f.object.endswith('STORAGE:value')]
    assert len(reads) == 1
    assert reads[0].attrs['modality'] == 'must'
    assert len(reads[0].attrs['origins']) == 1


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_declaration_without_value_keeps_order(language):
    """A bare declaration must not be treated as a write of a known value."""
    graph = link_project([lower_source(source(language, [
        'let value;',
        'consume(value);',
        'value = produce(1);',
        'return consume(value);',
    ]), language, 'bare' + language)])

    status, _ = run_status(graph)
    assert status == 'supported'
    reads = [f for f in argument_origins(graph) if f.object.endswith('STORAGE:value')]
    assert len(reads) == 2
    ordered = sorted(reads, key=lambda f: graph.entities[f.subject].attrs['start_byte'])
    # Before the assignment the origin is unknown; after it, the producer.
    assert ordered[0].attrs['unknown'] is True
    assert ordered[1].attrs['modality'] == 'must'
    assert len(ordered[1].attrs['origins']) == 1


@pytest.mark.parametrize('language', ['java', 'csharp'])
def test_shadowing_in_a_bare_block_is_still_refused(language):
    """A non-region block was already refused; keep its conservative outcome."""
    decl = declaration(language, 'let')
    graph = link_project([lower_source(source(language, [
        decl + 'value = produce(1);',
        '{ ' + decl + 'value = 0; consume(value); }',
        'return consume(value);',
    ]), language, 'bareblock' + language)])

    status, reason = run_status(graph)
    assert status == 'unsupported'
    # Either reason is a refusal; the bare block has no region to walk.
    assert reason in {'shadowed-binding', 'nonlocal-or-nested-write'}
    assert argument_origins(graph) == []


def test_python_has_no_block_scope_and_is_not_refused_as_shadowing():
    """Python ``if`` does not create a scope, so the binding is genuinely one."""
    graph = link_project([lower_source('''def produce(n):
    return n

def consume(n):
    return n

def run(flag):
    value = produce(1)
    if flag:
        value = 0
    return consume(value)
''', 'python', 'pyscope.py')])

    status, reason = run_status(graph)
    assert status == 'supported'
    assert reason is None
    reads = [f for f in argument_origins(graph) if f.object.endswith('STORAGE:value')]
    assert len(reads) == 1
    assert reads[0].attrs['modality'] == 'may'
