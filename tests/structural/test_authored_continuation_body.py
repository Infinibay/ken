"""Continuation source authoring preserves entry binding and returned closure."""
import pytest
from .test_closure_ownership import WRAPPERS, wrapper_matches

@pytest.mark.parametrize('language', WRAPPERS)
@pytest.mark.parametrize('mutation', ['positive', 'before_definition', 'after_definition', 'shadowed'])
def test_continuation_entry_binding_is_preserved(language, mutation):
    if language == 'python':
        before = ' next=other\n' if mutation == 'before_definition' else ''
        after = ' next=other\n' if mutation == 'after_definition' else ''
        parameter = 'next' if mutation == 'shadowed' else 'x'
        source = f'def wrap(next):\n{before} def handler({parameter}):\n  return next(x)\n{after} return handler\n'
    elif language == 'go':
        before = 'next=other;' if mutation == 'before_definition' else ''
        after = 'next=other;' if mutation == 'after_definition' else ''
        params = 'next func(int) int' if mutation == 'shadowed' else 'x int'
        source = f'package p; func wrap(next func(int) int) func(int) int {{ {before} handler := func({params}) int {{ return next(1) }}; {after} return handler }}'
    else:
        before = 'next=other;' if mutation == 'before_definition' else ''
        after = 'next=other;' if mutation == 'after_definition' else ''
        parameter = 'next' if mutation == 'shadowed' else 'x'
        source = f'function wrap(next) {{ {before} function handler({parameter}) {{ return next(1); }} {after} return handler; }}'
    assert bool(wrapper_matches(source, language)) is (mutation == 'positive')

@pytest.mark.parametrize('language', ['python','javascript','typescript'])
def test_unrelated_variable_writes_do_not_replace_continuation(language):
    source = ('def wrap(next):\n noise=1\n def handler(x):\n  noise=2\n  return next(x)\n noise=3\n return handler\n'
              if language == 'python' else
              'function wrap(next) { let noise=1; function handler(x) { let noise=2; return next(x); } noise=3; return handler; }')
    assert wrapper_matches(source, language)
