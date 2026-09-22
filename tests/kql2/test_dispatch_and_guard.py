"""Guard, dispatch-count and container-carried-argument primitives of the KQL 2 catalogue.

Three extensions landed with the Proxy migration:

* ``guarded_write($field, $access)`` -- the accessor writes that storage under a guard
  that references the storage itself, whatever the absence-test spelling is
  (``is None``, ``is_none()``, ``=== null``, ``== None``).
* ``require one dispatch of $method`` -- the callable dispatches its own operation from
  exactly one call site.
* ``argument $construction at any`` -- the argument receives the *result* of the named
  construction call, which is how a language writes ``Some(RealSubject { })``.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def rows(tmp_path, text, language, query, name='source'):
    extension = {'python': 'py', 'rust': 'rs'}[language]
    (tmp_path / f'{name}.{extension}').write_text(text)
    result = search(tmp_path, query, cache_mb=0)
    assert result['complete'], result
    return result['rows']


DISPATCH = ('language "kql/2"; module t; query q { '
            'type $unit { method $method { constructor: false; } } '
            'require one dispatch of $method; select $unit; }')

ONE = 'class A:\n    def run(self):\n        return self.run()\n'
TWO = 'class A:\n    def run(self):\n        self.run()\n        return self.run()\n'
OTHER = 'class A:\n    def run(self):\n        return self.other()\n'


@pytest.mark.parametrize('text,detected', [(ONE, True), (TWO, False), (OTHER, False)])
def test_one_dispatch_counts_the_call_sites_of_the_operation(tmp_path, text, detected):
    assert bool(rows(tmp_path, text, 'python', DISPATCH)) is detected


def test_dispatch_requires_a_selected_callable(tmp_path):
    query = ('language "kql/2"; module t; query q { '
             'type $unit { } require one dispatch of $unit; select $unit; }')
    with pytest.raises(Exception):
        rows(tmp_path, ONE, 'python', query)


GUARD = ('language "kql/2"; module t; query q { '
         'type $unit { field $field { } method $access { constructor: false; } } '
         'where guarded_write($field, $access); select $unit; }')

GUARDED = ('class Proxy:\n    def __init__(self, inner):\n        self.inner = inner\n'
           '    def run(self):\n        if self.inner is None:\n'
           '            self.inner = Other()\n        return self.inner.go()\n')
RUST_GUARDED = ('struct Proxy { subject: Option<Real> }\n'
                'impl Proxy {\n    fn run(&mut self) -> i32 {\n'
                '        if self.subject.is_none() { self.subject = Some(Real { }); }\n'
                '        self.subject.as_ref().unwrap().run()\n    }\n}\n')
UNGUARDED = ('class Proxy:\n    def __init__(self, inner):\n        self.inner = inner\n'
             '    def run(self):\n        self.inner = Other()\n        return self.inner.go()\n')
OTHER_FLAG = ('class Proxy:\n    def __init__(self, inner):\n        self.inner = inner\n'
              '    def run(self):\n        if flag:\n            self.inner = Other()\n'
              '        return self.inner.go()\n')


@pytest.mark.parametrize('language,text,detected', [
    ('python', GUARDED, True), ('rust', RUST_GUARDED, True),
    ('python', UNGUARDED, False), ('python', OTHER_FLAG, False)])
def test_guarded_write_covers_every_absence_test_and_no_other_guard(tmp_path, language, text,
                                                                   detected):
    assert bool(rows(tmp_path, text, language, GUARD)) is detected


CARRIED = ('language "kql/2"; module t;\n'
           'pattern Carried(out TypeDecl $unit, out Call $creation, out TypeDecl $created,\n'
           '                out Call $wrapper) {\n'
           '  type $unit {\n'
           '    field $slot { }\n'
           '    method $method {\n'
           '      constructor: false;\n'
           '      body {\n'
           '        let $local = construct $created { } as $creation;\n'
           '        call $wrapper { argument $creation at any; };\n'
           '        $slot = $wrapper as $write;\n'
           '      }\n'
           '    }\n'
           '  }\n'
           '}\n'
           'query q { use Carried(unit: $selected); select $selected; }\n')

REAL = 'class Real:\n    pass\n\n'
WRAPPED = REAL + 'class Holder:\n    def use(self):\n        self.slot = Wrapper(Real())\n'
NOT_CARRIED = REAL + 'class Holder:\n    def use(self):\n        self.slot = Real()\n'


@pytest.mark.parametrize('text,detected', [(WRAPPED, True), (NOT_CARRIED, False)])
def test_argument_carries_the_result_of_the_named_construction(tmp_path, text, detected):
    assert bool(rows(tmp_path, text, 'python', CARRIED)) is detected
