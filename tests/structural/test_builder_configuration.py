"""Parameter-configured builders versus unconfigured state projections."""
import pytest
from .test_gof_executable import evaluate

SOURCES = {
 'python': 'class Product:\n def __init__(self, value): self.value=value\nclass Assembly:\n def configure(self, value): self.state=value\n def finish(self): return Product(self.state)\n',
 'javascript': 'class Product { constructor(value){this.value=value;} } class Assembly { configure(value){this.state=value;} finish(){return new Product(this.state);} }',
 'typescript': 'class Product { value:number; constructor(value:number){this.value=value;} } class Assembly { state:number; configure(value:number){this.state=value;} finish(){return new Product(this.state);} }',
 'java': 'class Product { int value; Product(int value){this.value=value;} } class Assembly { int state; void configure(int value){this.state=value;} Product finish(){return new Product(this.state);} }',
 'csharp': 'class Product { int value; public Product(int value){this.value=value;} } class Assembly { int state; void configure(int value){this.state=value;} Product finish(){return new Product(this.state);} }',
}


@pytest.mark.parametrize('language', SOURCES)
def test_parameter_configured_builder(language):
    assert evaluate(SOURCES[language], language, 'builder')


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('replacement', ['42', 'self.other', 'self.state'])
def test_projection_of_internal_state_is_not_parameter_configuration(language, replacement):
    target = 'self.state=value' if language=='python' else 'this.state=value'
    rhs = replacement if language=='python' else replacement.replace('self.', 'this.')
    assert not evaluate(SOURCES[language].replace(target, target.split('=')[0]+'='+rhs), language, 'builder')


def test_cpp_constructor_is_not_a_separate_builder_step():
    source = '''class Product { public: Product(int value) {} };
class Holder { public:
 Holder(int value) { state = value; }
 Product *copy() { return new Product(state); }
private: int state;
};'''
    assert not evaluate(source, 'cpp', 'builder')
