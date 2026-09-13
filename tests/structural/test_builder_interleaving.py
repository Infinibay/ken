"""Metamorphic Builder tests: harmless work may intervene; product flow must survive."""
import re

import pytest

from ken.structural import lower_instructions
from .test_stored_product_builder import LANGUAGES, source, detect


def instrument(language, text, mode):
    """Add source-level logging of the input and independent local calculations."""
    if language == 'python':
        point = '  self.product.part.value=value\n'
        before = '  audit(value)\n  measurement=1+2\n'
        after = '  audit(value)\n'
        text += '\ndef audit(value):\n print(value)\n'
    else:
        point = ('self' if language == 'rust' else 'this') + '.product.part.value=value;'
        call = 'audit(value);' if language in {'javascript', 'typescript', 'rust'} else 'Builder.audit(value);'
        local = 'let measurement=1+2;' if language in {'javascript','typescript','rust'} else 'int measurement=1+2;'
        before, after = call + local, call
        if language == 'javascript': text += '\nfunction audit(value){console.log(value);}'
        elif language == 'typescript': text += '\nfunction audit(value:number){console.log(value);}'
        elif language == 'rust': text += '\nfn audit(value:&str){eprintln!("{}",value);}'
        else:
            method = 'public static void audit('+('Object' if language == 'java' else 'object')+' value){'+('System.out.println' if language == 'java' else 'System.Console.WriteLine')+'(value);}'
            text = text.replace('class Builder {', 'class Builder {' + method, 1)
    assert point in text
    text = text.replace(point, (before if mode in {'before','both','renamed'} else '') + point + (after if mode in {'after','both','renamed'} else ''), 1)
    if mode == 'renamed':
        for a, b in [('Builder','Assembler'),('Product','Document'),('configure','apply'),('finish','release')]:
            text = re.sub(r'\b'+a+r'\b',b,text)
    return text


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['before','after','both','renamed'])
def test_builder_survives_intermediate_logging_and_independent_arithmetic(language, mode):
    baseline = source(language, nested=True, clone=language == 'rust')
    original, original_matches = detect(baseline, language)
    assert original_matches['matches']
    graph, result = detect(instrument(language, baseline, mode), language)
    assert result['matches'], (language, mode, result)
    assert len(result['matches']) == len(original_matches['matches'])
    expected = 'Assembler' if mode == 'renamed' else 'Builder'
    assert {graph.entities[m['bindings']['$builder']].name for m in result['matches']} == {expected}
    # The new representation must handle these actual bodies, even where the
    # adapter reports native/partial forms. Pattern evaluation still uses KenQL.
    lower_instructions(graph).verify()


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['other-finish','overwritten','rebound'])
def test_logging_does_not_hide_broken_product_flow(language, mutation):
    text = source(language, mutation, nested=True, clone=language == 'rust')
    # A rebinding mutation still contains the actual configuration assignment.
    graph, result = detect(instrument(language, text, 'both'), language)
    assert not result['matches'], (language, mutation, result)


@pytest.mark.parametrize('language', LANGUAGES)
def test_logging_in_finish_preserves_the_returned_product(language):
    text = source(language, nested=True, clone=language == 'rust')
    text = instrument(language, text, 'both')
    if language == 'python': text = text.replace('  return self.product', '  audit(1)\n  return self.product')
    elif language == 'rust': text = text.replace('self.product.clone()', 'audit("finish");self.product.clone()')
    else: text = text.replace('return this.product;', ('audit(1);' if language in {'javascript','typescript'} else 'Builder.audit(1);')+'return this.product;')
    _, result = detect(text, language)
    assert result['matches']
