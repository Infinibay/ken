"""Builder director/lifecycle contracts, complementary to stored-product tests."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


SOURCES = {
    'python': '''class Product:
 def __init__(self, x, y): self.x=x; self.y=y
class Assembly:
 def first(self, value): self.x=value
 def second(self, value): self.y=value
 def finish(self): return Product(self.x, self.y)
def direct(parts: Assembly, other: Assembly):
 parts.first(1)
 parts.second(2)
 return parts.finish()
''',
    'java': '''class Product { int x,y; Product(int x,int y){this.x=x;this.y=y;} }
class Assembly {
 int x,y;
 void first(int value){this.x=value;}
 void second(int value){this.y=value;}
 Product finish(){return new Product(this.x,this.y);}
}
class Director { Product direct(Assembly parts, Assembly other){
 parts.first(1); parts.second(2); return parts.finish();
} }''',
    'typescript': '''class Product { constructor(public x:number,public y:number){} }
class Assembly {
 x:number=0; y:number=0;
 first(value:number){this.x=value;}
 second(value:number){this.y=value;}
 finish():Product{return new Product(this.x,this.y);}
}
function direct(parts:Assembly, other:Assembly):Product {
 parts.first(1); parts.second(2); return parts.finish();
}''',
}

IMMUTABLE = {
    'python': '''class Product:
 def __init__(self,x,y): self.x=x; self.y=y
class Assembly:
 def __init__(self,x,y): self.x=x; self.y=y
 def first(self,value): return Assembly(value,self.y)
 def second(self,value): return Assembly(self.x,value)
 def finish(self): return Product(self.x,self.y)
def direct(parts:Assembly):
 first=parts.first(1)
 second=first.second(2)
 return second.finish()
''',
    'java': '''class Product { Product(int x,int y){} }
class Assembly {
 final int x,y;
 Assembly(int x,int y){this.x=x;this.y=y;}
 Assembly first(int value){return new Assembly(value,this.y);}
 Assembly second(int value){return new Assembly(this.x,value);}
 Product finish(){return new Product(this.x,this.y);}
}
class Director { Product direct(Assembly parts){
 Assembly first=parts.first(1); Assembly second=first.second(2);
 return second.finish();
} }''',
    'typescript': '''class Product { constructor(public x:number,public y:number){} }
class Assembly {
 constructor(readonly x:number,readonly y:number){}
 first(value:number):Assembly{return new Assembly(value,this.y);}
 second(value:number):Assembly{return new Assembly(this.x,value);}
 finish():Product{return new Product(this.x,this.y);}
}
function direct(parts:Assembly):Product {
 const first=parts.first(1); const second=first.second(2);
 return second.finish();
}''',
}

DIRECTED_STATE_QUERY = '''query directed_state {
 match "builder#director"(builder:$builder,finish:$finish,product:$product);
 match "builder#mutable-product"(builder:$builder,finish:$finish,product:$product);
 emit $builder,$finish,$product;
}'''


def instrument(source, language):
    if language == 'python':
        return source.replace(' parts.second(2)', ' metric=1+2\n print(metric)\n parts.second(2)')
    noise = 'int metric=1+2; System.out.println(metric);' if language == 'java' else 'const metric=1+2; console.log(metric);'
    return source.replace('parts.second(2);', noise + ' parts.second(2);')


def detect(source, language, rule_id='builder#director'):
    graph = link_project([lower_source(source, language, 'builder.' + {'python': 'py', 'java': 'java', 'typescript': 'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    rule = SavedRule('directed-state', DIRECTED_STATE_QUERY) if rule_id == 'directed-state' else named_rule(rule_id, registry)
    result = execute_rules(graph, [rule], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('noise', [False, True])
def test_director_keeps_steps_and_finish_on_same_instance(language, noise):
    source = instrument(SOURCES[language], language) if noise else SOURCES[language]
    assert detect(source, language)


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['other-step', 'other-finish', 'one-distinct-step', 'discard-finish'])
def test_director_requires_correlated_distinct_steps_and_return(language, mutation):
    source = instrument(SOURCES[language], language)
    if mutation == 'other-step':
        source = source.replace('parts.second(2)', 'other.second(2)')
    elif mutation == 'other-finish':
        source = source.replace('return parts.finish()', 'return other.finish()')
    elif mutation == 'one-distinct-step':
        source = source.replace('parts.second(2)', 'parts.first(2)')
    else:
        source = source.replace('return parts.finish()', 'parts.finish()\n return None' if language == 'python' else 'parts.finish(); return null')
    assert not detect(source, language)


@pytest.mark.parametrize('language', SOURCES)
def test_composed_state_contract_rejects_constant_product(language):
    source = instrument(SOURCES[language], language).replace('Product(self.x, self.y)', 'Product(0, 0)').replace('Product(this.x,this.y)', 'Product(0,0)')
    assert detect(source, language)
    assert not detect(source, language, 'directed-state')


@pytest.mark.parametrize('language', SOURCES)
def test_composed_director_and_state_flow_contract(language):
    assert detect(instrument(SOURCES[language], language), language, 'directed-state')


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.xfail(strict=True, reason='Director receiver equality does not invalidate reassigned bindings')
def test_director_rebinding_does_not_mix_build_lifetimes(language):
    source = instrument(SOURCES[language], language)
    source = source.replace(' return parts.finish()', ' parts=other\n return parts.finish()') if language == 'python' else source.replace('return parts.finish()', 'parts=other; return parts.finish()')
    assert not detect(source, language)


@pytest.mark.parametrize('language', IMMUTABLE)
def test_immutable_configuration_reaches_finish_on_successor(language):
    # Resolved by builder#immutable-product (IR 1.52): the successor-builder
    # variant is implemented, so this is a normal regression, not a pending case.
    assert detect(IMMUTABLE[language], language, 'builder')
