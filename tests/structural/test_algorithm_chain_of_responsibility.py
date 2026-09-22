"""Linked handlers: the actual forwarding call must belong to its decision arm."""
from __future__ import annotations

import pytest

from .contract_support import contract_matches

from .test_gof_executable import evaluate

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', noise: bool = True) -> str:
    if language == 'python':
        prefix = '        audit = 17 * 3\n        print(audit)\n' if noise else ''
        inner = '            print(19)\n' if noise else ''
        body = f'''{prefix}        if request < 0:
{inner}            return self.following.handle(request)
        return self.process(request)
'''
        if mutation == 'conditional-audit':
            body = '        if request < 0:\n            self.following.audit()\n        return self.following.handle(request)\n'
        elif mutation == 'call-in-condition':
            body = '        if self.following.handle(request) < 0:\n            return 1\n        return 0\n'
        elif mutation == 'wrong-request':
            body = body.replace('following.handle(request)', 'following.handle(0)')
        elif mutation == 'discard-result':
            body = body.replace('return self.following.handle(request)', 'self.following.handle(request)\n            return 0')
        elif mutation == 'early-handled':
            body = '        if request >= 0:\n            return self.process(request)\n        return self.following.handle(request)\n'
        elif mutation == 'process-and-forward':
            body = body.replace('return self.following.handle(request)', 'self.process(request)\n            return self.following.handle(request)')
        return f'''class Handler:
    def handle(self, request): raise NotImplementedError()
    def audit(self): return 0
class Link(Handler):
    def __init__(self, following: Handler):
        self.following = following
        self.handled = 0
    def process(self, request):
        self.handled = request
        return self.handled
    def handle(self, request):
{body}
'''
    prefix = ('int audit = 17 * 3; System.out.println(audit);' if language == 'java' else
              'const audit = 17 * 3; console.log(audit);') if noise else ''
    inner = ('System.out.println(19);' if language == 'java' else 'console.log(19);') if noise else ''
    body = f'{prefix} if(request < 0){{{inner} return this.following.handle(request);}} return this.process(request);'
    if mutation == 'conditional-audit':
        body = 'if(request < 0){this.following.audit();} return this.following.handle(request);'
    elif mutation == 'call-in-condition':
        body = 'if(this.following.handle(request) < 0){return 1;} return 0;'
    elif mutation == 'wrong-request':
        body = body.replace('following.handle(request)', 'following.handle(0)')
    elif mutation == 'discard-result':
        body = body.replace('return this.following.handle(request);', 'this.following.handle(request);return 0;')
    elif mutation == 'early-handled':
        body = 'if(request >= 0){return this.process(request);} return this.following.handle(request);'
    elif mutation == 'process-and-forward':
        body = body.replace('return this.following.handle(request);', 'this.process(request);return this.following.handle(request);')
    if language == 'java':
        return f'''interface Handler {{ int handle(int request); int audit(); }}
class Link implements Handler {{
    Handler following; int handled = 0;
    Link(Handler following) {{ this.following = following; }}
    public int audit() {{ return 0; }}
    int process(int request) {{ this.handled = request; return this.handled; }}
    public int handle(int request) {{ {body} }}
}}
'''
    return f'''interface Handler {{ handle(request: number): number; audit(): number; }}
class Link implements Handler {{
    following: Handler; handled: number = 0;
    constructor(following: Handler) {{ this.following = following; }}
    audit(): number {{ return 0; }}
    process(request: number): number {{ this.handled = request; return this.handled; }}
    handle(request: number): number {{ {body} }}
}}
'''


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', [False, True])
def test_linked_handler_tolerates_independent_work(language, noise):
    assert evaluate(source(language, noise=noise), language, 'chain-of-responsibility')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['conditional-audit', 'call-in-condition'])
def test_forwarding_itself_must_be_conditional(language, mutation):
    assert not evaluate(source(language, mutation), language, 'chain-of-responsibility')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['wrong-request', 'discard-result', 'process-and-forward'])
def test_desired_exclusive_handler_contract_preserves_request_and_result(language, mutation):
    assert contract_matches(source(language), language, 'chain-of-responsibility.single_exclusive_handler')
    assert not contract_matches(source(language, mutation), language, 'chain-of-responsibility.single_exclusive_handler')


@pytest.mark.parametrize('language', LANGUAGES)
def test_early_local_handling_still_controls_forwarding(language):
    assert evaluate(source(language, 'early-handled'), language, 'chain-of-responsibility')
