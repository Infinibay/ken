"""``construct`` describes a source construction, credited by type and by carry.

Not every language constructs through a callable symbol: Go and Rust use keyed
literals and struct expressions, where the evidence is the produced type plus the
place whose value it carries. ``returns_value`` then links the callable's returned
value — including an implicit tail expression — to that construction.
"""
import pytest

from ken.kql2.service import search

QUERY = '''language "kql/2"; module t; query q {
 type $product { }
 type $assembly {
   field $state { }
   method $finish {
     name: "finish";
     body {
       let $built = construct $product { initializer $state; } as $building;
     }
   }
 }
 where returns_value($finish, $built);
 select $building.kind;
}'''


def assembled(tmp_path, extension, source):
    (tmp_path / f'a.{extension}').write_text(source)
    return search(tmp_path, QUERY, cache_mb=0)


# Rust (expression body and explicit return alike) and C# do not publish the
# construction carry yet, so they are not claimed here.
@pytest.mark.parametrize('extension,source', [
    ('go', 'package a\ntype Product struct{Value int}\ntype Assembly struct{state int}\n'
           'func(a *Assembly) finish() *Product{return &Product{Value:a.state}}\n'),
    ('py', 'class Product:\n def __init__(self, value): self.value = value\n'
           'class Assembly:\n def finish(self): return Product(self.state)\n'),
    ('java', 'class Product { Product(int value) {} } class Assembly {'
             ' Product finish() { return new Product(this.state); } }'),
    ('ts', 'class Product { constructor(value: number) {} } class Assembly {'
           ' state: number; finish() { return new Product(this.state); } }'),
    ('cpp', 'class Product { public: Product(int value) {} }; class Assembly {'
            ' int state; public: Product finish() { return Product(state); } };'),
])
def test_construction_is_credited_by_type_and_carried_place(tmp_path, extension, source):
    result = assembled(tmp_path, extension, source)
    # The construction is a call operation in the source; the type and the carried
    # place are what credit it, not a resolved callable symbol.
    assert result['rows'] == [['call']]


def test_a_construction_that_carries_another_place_is_not_a_match(tmp_path):
    source = ('class Product:\n def __init__(self, value): self.value = value\n'
              'class Assembly:\n def finish(self): return Product(0)\n')
    assert assembled(tmp_path, 'py', source)['rows'] == []


def test_a_callable_that_returns_something_else_is_not_a_match(tmp_path):
    source = ('class Product:\n def __init__(self, value): self.value = value\n'
              'class Assembly:\n def finish(self):\n  Product(self.state)\n  return 0\n')
    assert assembled(tmp_path, 'py', source)['rows'] == []


def test_an_unnamed_type_is_bound_by_the_construction(tmp_path):
    """``construct $type`` may introduce the type: "there is a type this builds"."""
    (tmp_path / 'a.py').write_text('class Product:\n def __init__(self, value): self.value = value\n'
                                   'class Assembly:\n def finish(self): return Product(self.state)\n')
    query = QUERY.replace('select $building.kind;', 'select $product.name;')
    assert search(tmp_path, query, cache_mb=0)['rows'] == [['Product']]


def test_construct_requires_a_bound_initializer_place(tmp_path):
    from ken.kql2.compiler import CompileError
    (tmp_path / 'a.py').write_text('class Assembly:\n def finish(self):\n  return 0\n')
    query = QUERY.replace('initializer $state;', 'initializer $missing;')
    with pytest.raises(CompileError):
        search(tmp_path, query, cache_mb=0)
