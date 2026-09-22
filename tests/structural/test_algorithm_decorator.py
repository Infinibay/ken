"""Decorator algorithm contracts distinguish decoration from incidental calls."""
import re

import pytest

from .contract_support import contract_matches

from .test_gof_executable import evaluate


LANGUAGES = ['python', 'java', 'typescript']


def source(language, body):
    if language == 'python':
        return ('class Contract:\n def run(self, value): return value\n'
                'class Subject(Contract):\n'
                ' def __init__(self, inner: Contract): self.inner=inner\n'
                ' def run(self, value):\n'
                + ''.join('  ' + line + '\n' for line in body.splitlines()))
    if language == 'java':
        return ('interface Contract {int run(int value);}'
                'class Subject implements Contract {Contract inner;'
                'Subject(Contract inner){this.inner=inner;}'
                'public int run(int value){' + body + '}}')
    return ('interface Contract {run(value:number):number;}'
            'class Subject implements Contract {inner:Contract;'
            'constructor(inner:Contract){this.inner=inner;}'
            'run(value:number):number{' + body + '}}')


def body(language, location='before'):
    if language == 'python':
        chunks = ['print("trace")', 'result=self.inner.run(value)', 'return result']
        noise = 'metric=3+4'
        separator = '\n'
    else:
        trace = 'System.out.println("trace");' if language == 'java' else 'console.log("trace");'
        declaration = 'int' if language == 'java' else 'let'
        chunks = [trace, f'{declaration} result=this.inner.run(value);', 'return result;']
        noise = f'{declaration} metric=3+4;'
        separator = ''
    chunks.insert({'before': 0, 'between': 1, 'after': 2}[location], noise)
    return separator.join(chunks)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('location', ['before', 'between', 'after'])
@pytest.mark.parametrize('renamed', [False, True])
def test_decoration_survives_independent_work(language, location, renamed):
    text = source(language, body(language, location))
    if renamed:
        names = {'Subject': 'Tracing', 'Contract': 'Port', 'run': 'execute', 'inner': 'component', 'result': 'answer'}
        text = re.sub(r'\b\w+\b', lambda m: names.get(m[0], m[0]), text)
    assert evaluate(text, language, 'decorator')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['no-decoration', 'no-forward', 'other-receiver', 'other-slot'])
def test_missing_decorator_collaboration_is_rejected(language, mutation):
    text = source(language, body(language))
    if mutation == 'no-decoration':
        text = text.replace('print("trace")', 'pass').replace('System.out.println("trace");', '').replace('console.log("trace");', '')
    elif mutation == 'no-forward':
        text = text.replace('self.inner.run(value)', '0').replace('this.inner.run(value)', '0')
    elif mutation == 'other-receiver':
        text = text.replace('inner.run', 'other.run')
    else:
        text = text.replace('inner.run', 'inner.other')
    assert not evaluate(text, language, 'decorator')


@pytest.mark.parametrize('language', LANGUAGES)
def test_unreachable_trace_does_not_add_a_responsibility(language):
    text = ('return self.inner.run(value)\nprint("trace")' if language == 'python' else
            'return this.inner.run(value);' + ('System.out.println("trace");' if language == 'java' else 'console.log("trace");'))
    assert not evaluate(source(language, text), language, 'decorator')


@pytest.mark.parametrize('language', LANGUAGES)
def test_arithmetic_result_decoration_needs_no_extra_call(language):
    text = 'return self.inner.run(value)+1' if language == 'python' else 'return this.inner.run(value)+1;'
    assert evaluate(source(language, text), language, 'decorator')


@pytest.mark.parametrize('language', LANGUAGES)
def test_transparent_tracing_variant_rejects_discarded_result(language):
    # Other Decorator variants may intentionally transform/discard results.
    text = body(language).replace('return result', 'return 0')
    assert contract_matches(source(language, body(language)), language, 'decorator.result_forwarding')
    assert not contract_matches(source(language, text), language, 'decorator.result_forwarding')


@pytest.mark.parametrize('language', LANGUAGES)
def test_functional_decorator_is_a_valid_variant(language):
    # Resolved by decorator#callable-wrapper (IR 1.54): the callable-wrapper
    # variant is implemented, so this is a normal regression, not a pending case.
    text = {
        'python': 'def traced(inner):\n def run(value):\n  print("trace")\n  return inner(value)\n return run\n',
        'java': 'interface Action {int run(int value);}class Factory {static Action traced(Action inner){return value->{System.out.println("trace");return inner.run(value);};}}',
        'typescript': 'function traced(inner:(value:number)=>number):(value:number)=>number{return value=>{console.log("trace");return inner(value);};}',
    }[language]
    assert evaluate(text, language, 'decorator')
