"""Factory Method definitions and a separate client-flow refinement."""
import re

import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


SOURCES = {
    'python': '''class Product: pass
def consume(product: Product): return product
class Base:
 def make(self) -> Product: pass
 def execute(self):
  return consume(self.make())
class Factory(Base):
 def make(self) -> Product:
  result = Product()
  return result
''',
    'java': '''class Product {}
abstract class Base {
 abstract Product make();
 Product consume(Product product){return product;}
 Product execute(){ return consume(this.make()); }
}
class Factory extends Base {
 Product make(){ Product result = new Product(); return result; }
}''',
    'typescript': '''class Product {}
function consume(product: Product): Product {return product;}
abstract class Base {
 abstract make(): Product;
 execute(): Product { return consume(this.make()); }
}
class Factory extends Base {
 make(): Product { let result = new Product(); return result; }
}''',
}

CLIENT_QUERY = '''query factory_client {
 match "factory-method"(factory:$factory, product:$product);
 require $factory OVERRIDES $slot;
 require $creation TARGET $slot;
 require $creation RESULT $value;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $value;
 emit $factory, $creation, $consumer;
}'''


def instrument(source, language):
    if language == 'python':
        return source.replace('  return result', '  metric = 1 + 2\n  print(metric)\n  return result').replace('  return consume', '  print(123)\n  return consume')
    noise = 'int metric = 1 + 2; System.out.println(metric);' if language == 'java' else 'const metric = 1 + 2; console.log(metric);'
    return source.replace('return result;', noise + ' return result;').replace('return consume', ('System.out.println(123);' if language == 'java' else 'console.log(123);') + ' return consume')


def detect(source, language, client=False):
    graph = link_project([lower_source(source, language, 'method.' + {'python': 'py', 'java': 'java', 'typescript': 'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    rule = SavedRule('factory-client', CLIENT_QUERY) if client else named_rule('factory-method', registry)
    result = execute_rules(graph, [rule], registry=registry)
    assert result['complete'], result['outcomes']
    return graph, result['matches']


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mode', ['baseline', 'noise', 'renamed'])
def test_product_origin_and_extension_slot_survive_noise(language, mode):
    source = SOURCES[language] if mode == 'baseline' else instrument(SOURCES[language], language)
    if mode == 'renamed':
        for old, new in [('Factory', 'Assembler'), ('Product', 'Document'), ('make', 'release')]:
            source = re.sub(r'\b' + old + r'\b', new, source)
    graph, matches = detect(source, language)
    assert matches
    assert {graph.entities[m['bindings']['$creator']].name for m in matches} == {'Assembler' if mode == 'renamed' else 'Factory'}


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['rebound-product', 'no-slot', 'discarded-construction'])
def test_missing_slot_or_return_origin_is_rejected(language, mutation):
    source = instrument(SOURCES[language], language)
    if mutation == 'no-slot':
        source = source.replace('class Factory(Base)', 'class Factory').replace('class Factory extends Base', 'class Factory')
    elif mutation == 'rebound-product':
        source = source.replace('  return result', '  result = None\n  return result') if language == 'python' else source.replace('return result;', 'result = null; return result;')
    else:
        source = source.replace('return result', 'return None' if language == 'python' else 'return null')
    assert not detect(source, language)[1]


@pytest.mark.parametrize('language', SOURCES)
def test_saved_value_survives_rebinding_of_original_local(language):
    source = instrument(SOURCES[language], language)
    if language == 'python':
        source = source.replace('  return result', '  saved = result\n  result = None\n  return saved')
    else:
        declaration = 'Product' if language == 'java' else 'const'
        source = source.replace('return result;', f'{declaration} saved = result; result = null; return saved;')
    assert detect(source, language)[1]


@pytest.mark.parametrize('language', SOURCES)
def test_client_consumes_result_of_base_extension_slot(language):
    assert detect(instrument(SOURCES[language], language), language, client=True)[1]


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['fixed-product', 'discarded-slot-result'])
def test_client_refinement_rejects_bypass_without_erasing_factory(language, mutation):
    source = instrument(SOURCES[language], language)
    receiver = 'self' if language == 'python' else 'this'
    replacement = 'Product()' if language == 'python' else 'new Product()'
    source = source.replace(f'consume({receiver}.make())', f'consume({replacement})')
    if mutation == 'discarded-slot-result':
        source = source.replace('  return consume', '  self.make()\n  return consume') if language == 'python' else source.replace('return consume', 'this.make(); return consume')
    assert detect(source, language)[1]
    assert not detect(source, language, client=True)[1]
