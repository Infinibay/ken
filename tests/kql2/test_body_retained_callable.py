"""A call may invoke the callable retained in a place, not only a symbol.

``call $place { ... }`` where ``$place`` is a field, variable or parameter matches a
call whose ``CALLEE_VALUE`` is that place: the callback a wrapper or a context holds.
The clause does not resolve a method symbol, so it works for callbacks, closures and
function-typed fields in every language that publishes the value relation.
"""
import pytest

from ken.kql2.service import search

QUERY = '''language "kql/2"; module t; query q {
 type $holder {
   field $action { }
   method $run {
     name: "run";
     body {
       call $action { argument $input at 0; };
     }
   }
 }
 select $run.name;
}'''

TYPE_QUERY = QUERY.replace('method $run {\n     name: "run";',
                           'method $run {\n     name: "run";\n     param $input { }')


@pytest.mark.parametrize('extension,source', [
    ('py', 'class Holder:\n def __init__(self, action): self.action = action\n'
           ' def run(self, value): return self.action(value)\n'),
    ('js', 'class Holder { constructor(action) { this.action = action; }'
           ' run(value) { return this.action(value); } }'),
    ('ts', 'class Holder { action: (v: number) => number;'
           ' run(value: number) { return this.action(value); } }'),
])
def test_a_retained_callable_is_invoked(tmp_path, extension, source):
    (tmp_path / f'a.{extension}').write_text(source)
    assert search(tmp_path, TYPE_QUERY, cache_mb=0)['rows'] == [['run']]


def test_a_method_call_on_another_object_is_not_the_retained_value(tmp_path):
    (tmp_path / 'a.py').write_text('class Helper:\n def action(self, value): return value\n'
                                   'class Holder:\n def run(self, value): return Helper().action(value)\n')
    assert search(tmp_path, TYPE_QUERY, cache_mb=0)['rows'] == []


def test_a_place_that_is_never_invoked_is_not_a_match(tmp_path):
    (tmp_path / 'a.py').write_text('class Holder:\n def __init__(self, action): self.action = action\n'
                                   ' def run(self, value): return value\n')
    assert search(tmp_path, TYPE_QUERY, cache_mb=0)['rows'] == []
