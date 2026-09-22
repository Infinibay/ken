"""Adapter contracts: nominal collaboration versus actual argument/result flow."""
import re

import pytest

from .contract_support import contract_matches

from .test_gof_executable import evaluate


LANGUAGES = ['python', 'java', 'typescript']


def source(language, before='', after='', argument='converted', returned='result+1'):
    if language == 'python':
        return ('class Contract:\n def request(self, value): return 0\n'
                'class Legacy:\n def perform(self, value): return value\n'
                'class Subject(Contract):\n'
                ' def __init__(self, service: Legacy): self.service=service\n'
                ' def request(self, value):\n'
                + ''.join('  ' + line + '\n' for line in before.splitlines())
                + '  converted=value*2\n'
                + f'  result=self.service.perform({argument})\n'
                + ''.join('  ' + line + '\n' for line in after.splitlines())
                + f'  return {returned}\n')
    if language == 'java':
        return ('interface Contract {int request(int value);}'
                'class Legacy {int perform(int value){return value;}}'
                'class Subject implements Contract {Legacy service;'
                'Subject(Legacy service){this.service=service;}'
                'public int request(int value){' + before + 'int converted=value*2;'
                + f'int result=this.service.perform({argument});' + after
                + 'return ' + returned + ';}}')
    return ('interface Contract {request(value:number):number;}'
            'class Legacy {perform(value:number):number{return value;}}'
            'class Subject implements Contract {service:Legacy;'
            'constructor(service:Legacy){this.service=service;}'
            'request(value:number):number{' + before + 'const converted=value*2;'
            + f'let result=this.service.perform({argument});' + after
            + 'return ' + returned + ';}}')


def noise(language):
    return {'python': 'metric=3+4\nprint(metric)',
            'java': 'int metric=3+4;System.out.println(metric);',
            'typescript': 'const metric=3+4;console.log(metric);'}[language]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('placement', ['before', 'after', 'both'])
@pytest.mark.parametrize('renamed', [False, True])
def test_adapter_with_input_output_conversion_and_noise(language, placement, renamed):
    before = noise(language) if placement in {'before', 'both'} else ''
    after = noise(language).replace('metric', 'later') if placement in {'after', 'both'} else ''
    text = source(language, before=before, after=after)
    if renamed:
        names = {'Subject': 'Translation', 'Legacy': 'Backend', 'Contract': 'Port',
                 'request': 'read', 'perform': 'fetch', 'service': 'provider'}
        text = re.sub(r'\b\w+\b', lambda m: names.get(m[0], m[0]), text)
    assert evaluate(text, language, 'adapter')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['unused-service', 'other-receiver', 'no-target-slot'])
def test_missing_adapter_collaboration_is_rejected(language, mutation):
    text = source(language, before=noise(language))
    if mutation == 'unused-service':
        text = text.replace('self.service.perform(converted)', '0').replace('this.service.perform(converted)', '0')
    elif mutation == 'other-receiver':
        text = text.replace('service.perform', 'unknown.perform')
    else:
        # Change only the target declaration, leaving the concrete method intact.
        text = text.replace('request', 'different', 1)
    assert not evaluate(text, language, 'adapter')


def unrelated_contract_source(language):
    if language == 'python':
        return ('class Contract:\n def request(self): return 0\n def perform(self): return 0\n'
                'class Marker: pass\nclass Subject(Contract, Marker):\n'
                ' def __init__(self, service: Contract): self.service=service\n'
                ' def request(self): return self.service.perform()\n')
    if language == 'java':
        return ('interface Contract {int request();int perform();}interface Marker {}'
                'class Subject implements Contract,Marker {Contract service;'
                'Subject(Contract service){this.service=service;}'
                'public int perform(){return 0;}public int request(){return this.service.perform();}}')
    return ('interface Contract {request():number;perform():number;}interface Marker {}'
            'class Subject implements Contract,Marker {service:Contract;'
            'constructor(service:Contract){this.service=service;}'
            'perform():number{return 0;}request():number{return this.service.perform();}}')


@pytest.mark.parametrize('language', LANGUAGES)
def test_unrelated_marker_cannot_supply_different_target_contract(language):
    # Both methods belong to Contract. Adding Marker must not manufacture
    # evidence that this delegation adapts the unrelated Marker contract.
    assert not evaluate(unrelated_contract_source(language), language, 'adapter')


@pytest.mark.parametrize('language', LANGUAGES)
def test_input_conversion_contract_rejects_discarded_input(language):
    assert contract_matches(source(language), language, 'adapter.input_conversion')
    assert not contract_matches(source(language, argument='0'), language, 'adapter.input_conversion')


@pytest.mark.parametrize('language', LANGUAGES)
def test_output_conversion_contract_rejects_discarded_result(language):
    assert contract_matches(source(language), language, 'adapter.output_conversion')
    assert not contract_matches(source(language, returned='0'), language, 'adapter.output_conversion')


@pytest.mark.parametrize('language', LANGUAGES)
def test_conversion_does_not_require_renaming_operation(language):
    assert evaluate(source(language).replace('perform', 'request'), language, 'adapter')
