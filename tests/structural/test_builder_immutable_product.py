"""Builder ``immutable-product``: a copy-with-one-field-changed chain, in eight languages.

The variant is a published rule, so the test goes through the registry name
``builder#immutable-product``.

The query accepts two constructor shapes, because C-like and Go/Rust-like
languages record them differently: positional arguments (``ARGUMENT`` + ``VALUE``
+ ``LOADED_FROM``) and keyed/brace initialization (``HAS_INITIALIZER`` +
``STORES_VALUE``). Both mean "this successor carries this field".
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'builder#immutable-product'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}

HEAD = {
    'python': '''class Product:
    def __init__(self, name, size):
        self.name = name
        self.size = size
''',
    'javascript': '''class Product {
  constructor(name, size) { this.name = name; this.size = size; }
}
''',
    'typescript': '''class Product {
  constructor(public name: number, public size: number) {}
}
''',
    'java': '''class Product { Product(int name, int size) {} }
''',
    'csharp': '''class Product { public Product(int name, int size) {} }
''',
    'cpp': '''struct Product { Product(int n, int s) {} };
''',
    'go': '''package builder

type Product struct {
	name int
	size int
}
''',
    'rust': '''pub struct Product { pub name: i32, pub size: i32 }
''',
}

# `step` builds a successor that changes one field and carries the other;
# `finish` consumes the carried field.
BODY = {
    'python': '''class Builder:
    def __init__(self, name, size):
        self.name = name
        self.size = size
    def with_name(self, name):
        return Builder(name, self.size)
    def build(self):
        return Product(self.name, self.size)
''',
    'javascript': '''class Builder {
  constructor(name, size) { this.name = name; this.size = size; }
  withName(name) { return new Builder(name, this.size); }
  build() { return new Product(this.name, this.size); }
}
''',
    'typescript': '''class Builder {
  constructor(public name: number, public size: number) {}
  withName(name: number): Builder { return new Builder(name, this.size); }
  build(): Product { return new Product(this.name, this.size); }
}
''',
    'java': '''class Builder {
  int name; int size;
  Builder(int name, int size) { this.name = name; this.size = size; }
  Builder withName(int name) { return new Builder(name, this.size); }
  Product build() { return new Product(this.name, this.size); }
}
''',
    'csharp': '''class Builder {
  int name; int size;
  public Builder(int name, int size) { this.name = name; this.size = size; }
  public Builder WithName(int name) { return new Builder(name, this.size); }
  public Product Build() { return new Product(this.name, this.size); }
}
''',
    'cpp': '''struct Builder {
  int name; int size;
  Builder(int name, int size) : name(name), size(size) {}
  Builder with_name(int name) const { return Builder(name, this->size); }
  Product build() const { return Product(this->name, this->size); }
};
''',
    'go': '''type Builder struct {
	name int
	size int
}

func (b Builder) WithName(name int) Builder {
	return Builder{name: name, size: b.size}
}

func (b Builder) Build() Product {
	return Product{name: b.name, size: b.size}
}
''',
    'rust': '''pub struct Builder { pub name: i32, pub size: i32 }

impl Builder {
    pub fn with_name(&self, name: i32) -> Builder {
        Builder { name: name, size: self.size }
    }
    pub fn build(&self) -> Product {
        Product { name: self.name, size: self.size }
    }
}
''',
}

# A step that mutates itself and returns `self`/`this`/the receiver: not a successor.
MUTATING = {
    'python': '''class Builder:
    def __init__(self, name, size):
        self.name = name
        self.size = size
    def with_name(self, name):
        self.name = name
        return self
    def build(self):
        return Product(self.name, self.size)
''',
    'javascript': '''class Builder {
  constructor(name, size) { this.name = name; this.size = size; }
  withName(name) { this.name = name; return this; }
  build() { return new Product(this.name, this.size); }
}
''',
    'typescript': '''class Builder {
  constructor(public name: number, public size: number) {}
  withName(name: number): Builder { this.name = name; return this; }
  build(): Product { return new Product(this.name, this.size); }
}
''',
    'java': '''class Builder {
  int name; int size;
  Builder(int name, int size) { this.name = name; this.size = size; }
  Builder withName(int name) { this.name = name; return this; }
  Product build() { return new Product(this.name, this.size); }
}
''',
    'csharp': '''class Builder {
  int name; int size;
  public Builder(int name, int size) { this.name = name; this.size = size; }
  public Builder WithName(int name) { this.name = name; return this; }
  public Product Build() { return new Product(this.name, this.size); }
}
''',
    'cpp': '''struct Builder {
  int name; int size;
  Builder(int name, int size) : name(name), size(size) {}
  Builder& with_name(int name) { this->name = name; return *this; }
  Product build() const { return Product(this->name, this->size); }
};
''',
    'go': '''type Builder struct {
	name int
	size int
}

func (b *Builder) WithName(name int) *Builder {
	b.name = name
	return b
}

func (b Builder) Build() Product {
	return Product{name: b.name, size: b.size}
}
''',
    'rust': '''pub struct Builder { pub name: i32, pub size: i32 }

impl Builder {
    pub fn with_name(&mut self, name: i32) -> &mut Builder {
        self.name = name;
        self
    }
    pub fn build(&self) -> Product {
        Product { name: self.name, size: self.size }
    }
}
''',
}

# The successor drops the other field instead of carrying it.
NO_CARRY = {
    'python': '''class Builder:
    def __init__(self, name, size):
        self.name = name
        self.size = size
    def with_name(self, name):
        return Builder(name, 0)
    def build(self):
        return Product(self.name, self.size)
''',
    'javascript': '''class Builder {
  constructor(name, size) { this.name = name; this.size = size; }
  withName(name) { return new Builder(name, 0); }
  build() { return new Product(this.name, this.size); }
}
''',
    'typescript': '''class Builder {
  constructor(public name: number, public size: number) {}
  withName(name: number): Builder { return new Builder(name, 0); }
  build(): Product { return new Product(this.name, this.size); }
}
''',
    'java': '''class Builder {
  int name; int size;
  Builder(int name, int size) { this.name = name; this.size = size; }
  Builder withName(int name) { return new Builder(name, 0); }
  Product build() { return new Product(this.name, this.size); }
}
''',
    'csharp': '''class Builder {
  int name; int size;
  public Builder(int name, int size) { this.name = name; this.size = size; }
  public Builder WithName(int name) { return new Builder(name, 0); }
  public Product Build() { return new Product(this.name, this.size); }
}
''',
    'cpp': '''struct Builder {
  int name; int size;
  Builder(int name, int size) : name(name), size(size) {}
  Builder with_name(int name) const { return Builder(name, 0); }
  Product build() const { return Product(this->name, this->size); }
};
''',
    'go': '''package builder

type Product struct {
	name int
	size int
}

type Builder struct {
	name int
	size int
}

func (b Builder) WithName(name int) Builder {
	return Builder{name: name, size: 0}
}

func (b Builder) Build() Product {
	return Product{name: b.name, size: b.size}
}
''',
    'rust': '''pub struct Product { pub name: i32, pub size: i32 }

pub struct Builder { pub name: i32, pub size: i32 }

impl Builder {
    pub fn with_name(&self, name: i32) -> Builder {
        Builder { name: name, size: 0 }
    }
    pub fn build(&self) -> Product {
        Product { name: self.name, size: self.size }
    }
}
''',
}


def source(language, body):
    """Go fixtures that already declare their package stand alone."""
    if body.startswith('package'):
        return body
    return HEAD[language] + body


def detect(language, body):
    graph = link_project([lower_source(source(language, body), language,
                                       f'builder.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_successor_builder_carrying_a_field_is_detected(language):
    matches = detect(language, BODY[language])
    assert matches, language
    bindings = matches[0]['bindings']
    assert bindings['$builder'].endswith('/CLASS:Builder')
    assert bindings['$product'].endswith('/CLASS:Product')
    assert bindings['$finish'].startswith(bindings['$builder'].rsplit('/', 1)[0] + '/')


@pytest.mark.parametrize('language', LANGUAGES)
def test_mutating_step_returning_the_receiver_is_rejected(language):
    """A fluent self-mutation is not a copied successor."""
    assert not detect(language, MUTATING[language])


@pytest.mark.parametrize('language', LANGUAGES)
def test_successor_that_drops_the_other_field_is_rejected(language):
    """The step must carry the field it did not change."""
    assert not detect(language, NO_CARRY[language])


def test_variant_is_ready_for_all_eight_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'builder')
    row = next(v for v in rule.variants if v['id'] == 'immutable-product')
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'RETURNS_NEW' in row['query'] and 'LOADED_FROM' in row['query']
