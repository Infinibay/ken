"""Proxy guard/delegation contracts, without claiming policy authorization."""
import re

import pytest

from .test_gof_executable import evaluate


LANGUAGES = ['python', 'java', 'typescript']


def source(language, body):
    if language == 'python':
        return ('class Contract:\n def run(self, allowed): return 0\n'
                ' def audit(self): return 0\n'
                'class Subject(Contract):\n'
                ' def __init__(self, inner: Contract): self.inner=inner\n'
                ' def run(self, allowed):\n'
                + ''.join('  ' + line + '\n' for line in body.splitlines()))
    if language == 'java':
        return ('interface Contract {int run(boolean allowed);int audit();}'
                'class Subject implements Contract {Contract inner;'
                'Subject(Contract inner){this.inner=inner;}'
                'public int audit(){return 0;} public int run(boolean allowed){' + body + '}}')
    return ('interface Contract {run(allowed:boolean):number;audit():number;}'
            'class Subject implements Contract {inner:Contract;'
            'constructor(inner:Contract){this.inner=inner;}'
            'audit():number{return 0;} run(allowed:boolean):number{' + body + '}}')


def guarded(language, placement='none'):
    if language == 'python':
        before = 'count=2+3\nprint(count)\n' if placement in {'before', 'both'} else ''
        inside = ' print(4)\n' if placement in {'inside', 'both'} else ''
        return before + 'if allowed:\n' + inside + ' return self.inner.run(allowed)\nreturn 0'
    before = ('int count=2+3;System.out.println(count);' if language == 'java' else
              'const count=2+3;console.log(count);') if placement in {'before', 'both'} else ''
    inside = ('System.out.println(4);' if language == 'java' else 'console.log(4);') if placement in {'inside', 'both'} else ''
    return before + 'if(allowed){' + inside + 'return this.inner.run(allowed);}return 0;'


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('placement', ['before', 'inside', 'both'])
@pytest.mark.parametrize('renamed', [False, True])
def test_guarded_proxy_survives_independent_work(language, placement, renamed):
    text = source(language, guarded(language, placement))
    if renamed:
        names = {'Subject': 'Gate', 'Contract': 'Service', 'inner': 'target', 'run': 'request', 'allowed': 'enabled'}
        text = re.sub(r'\b\w+\b', lambda m: names.get(m[0], m[0]), text)
    assert evaluate(text, language, 'proxy')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['no-guard', 'other-receiver', 'other-slot'])
def test_missing_guarded_forwarding_is_rejected(language, mutation):
    body = guarded(language, 'both')
    if mutation == 'no-guard':
        body = 'print(4)\nreturn self.inner.run(allowed)' if language == 'python' else 'return this.inner.run(allowed);'
    elif mutation == 'other-receiver':
        body = body.replace('self.inner.run', 'self.other.run').replace('this.inner.run', 'this.other.run')
    else:
        body = body.replace('inner.run(allowed)', 'inner.audit()')
    assert not evaluate(source(language, body), language, 'proxy')


@pytest.mark.parametrize('language', LANGUAGES)
def test_conditional_audit_cannot_lend_guard_to_unconditional_forward(language):
    body = ('if allowed:\n self.inner.audit()\nreturn self.inner.run(allowed)' if language == 'python' else
            'if(allowed){this.inner.audit();}return this.inner.run(allowed);')
    assert not evaluate(source(language, body), language, 'proxy')


@pytest.mark.parametrize('language', LANGUAGES)
def test_invocation_in_guard_condition_is_not_controlled_by_that_guard(language):
    body = ('if self.inner.run(allowed):\n return 1\nreturn 0' if language == 'python' else
            'if(this.inner.run(allowed)>0){return 1;}return 0;')
    assert not evaluate(source(language, body), language, 'proxy')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Early denial controls later delegation without lexical branch containment')
def test_early_denial_is_a_valid_guarded_access_variant(language):
    body = ('if not allowed:\n return 0\nreturn self.inner.run(allowed)' if language == 'python' else
            'if(!allowed){return 0;}return this.inner.run(allowed);')
    assert evaluate(source(language, body), language, 'proxy')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Conditional candidate does not prove all delegation paths obey access policy')
def test_access_enforcement_variant_rejects_unconditional_bypass(language):
    body = guarded(language).replace('return 0', 'return self.inner.run(allowed)' if language == 'python' else 'return this.inner.run(allowed)')
    assert not evaluate(source(language, body), language, 'proxy')
