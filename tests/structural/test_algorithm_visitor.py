"""Visitor algorithm contracts over source, including unproven strong variants."""
import re

import pytest

from .contract_support import contract_matches

from .test_gof_executable import evaluate


LANGUAGES = ['python', 'java', 'typescript']


def source(language, before='', after='', dispatch=None, result='result'):
    if language == 'python':
        call = dispatch or 'visitor.visit(self)'
        return ('class Subject:\n'
                ' def accept(self, visitor: Visitor):\n'
                + ''.join('  ' + line + '\n' for line in before.splitlines())
                + f'  result={call}\n'
                + ''.join('  ' + line + '\n' for line in after.splitlines())
                + f'  return {result}\n'
                'class Visitor:\n'
                ' def visit(self, element: Subject): return 7\n'
                ' def audit(self, element: object): print(element)\n')
    if language == 'java':
        return ('class Subject {int accept(Visitor visitor){' + before
                + 'int result=' + (dispatch or 'visitor.visit(this)') + ';'
                + after + 'return ' + result + ';}}'
                'class Visitor {int visit(Subject element){return 7;}'
                'void audit(Object element){System.out.println(element);}}')
    return ('class Subject {accept(visitor:Visitor):number{' + before
            + 'let result=' + (dispatch or 'visitor.visit(this)') + ';'
            + after + 'return ' + result + ';}}'
            'class Visitor {visit(element:Subject):number{return 7;}'
            'audit(element:object):void{console.log(element);}}')


def noise(language):
    if language == 'python':
        return 'count=2+3\nprint(count)'
    if language == 'java':
        return 'int count=2+3;System.out.println(count);'
    return 'const count=2+3;console.log(count);'


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('placement', ['before', 'after', 'both'])
@pytest.mark.parametrize('renamed', [False, True])
def test_visitor_result_survives_independent_interleaving(language, placement, renamed):
    before = noise(language) if placement in {'before', 'both'} else ''
    after = noise(language).replace('count', 'later') if placement in {'after', 'both'} else ''
    text = source(language, before, after)
    if renamed:
        names = {'Subject': 'Term', 'Visitor': 'Evaluation', 'accept': 'apply',
                 'visitor': 'operation', 'visit': 'evaluate', 'result': 'answer'}
        text = re.sub(r'\b\w+\b', lambda m: names.get(m[0], m[0]), text)
    assert evaluate(text, language, 'visitor')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['other-element', 'other-visitor', 'wrong-element-contract'])
def test_missing_dispatch_identity_is_rejected(language, mutation):
    text = source(language, before=noise(language))
    if mutation == 'other-element':
        text = text.replace('visitor.visit(self)', 'visitor.visit(None)').replace('visitor.visit(this)', 'visitor.visit(null)')
    elif mutation == 'other-visitor':
        text = text.replace('visitor.visit', 'other.visit')
    else:
        text = text.replace('element: Subject', 'element: object').replace('Subject element', 'Object element').replace('element:Subject', 'element:object')
    assert not evaluate(text, language, 'visitor')


@pytest.mark.parametrize('language', LANGUAGES)
def test_replacing_received_visitor_breaks_received_visitor_contract(language):
    replacement = 'visitor=Visitor()' if language == 'python' else 'visitor=new Visitor();'
    assert not evaluate(source(language, before=replacement), language, 'visitor')


@pytest.mark.parametrize('language', LANGUAGES)
def test_self_argument_must_belong_to_typed_visit_call(language):
    # audit accepts only the general object contract; visit requires Subject but
    # receives null. Combining those two calls cannot establish typed self dispatch.
    before = 'visitor.audit(self)' if language == 'python' else 'visitor.audit(this);'
    dispatch = 'visitor.visit(None)' if language == 'python' else 'visitor.visit(null)'
    assert not evaluate(source(language, before=before, dispatch=dispatch), language, 'visitor')


@pytest.mark.parametrize('language', LANGUAGES)
def test_result_forwarding_variant_rejects_replaced_result(language):
    # Discarding a result is legal for other Visitor variants. This expected
    # failure is an unavailable stronger query contract, not a broad-rule FP.
    overwrite = 'result=0' if language == 'python' else 'result=0;'
    assert contract_matches(source(language), language, 'visitor.result_forwarding')
    assert not contract_matches(source(language, after=overwrite), language, 'visitor.result_forwarding')
