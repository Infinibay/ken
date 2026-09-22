"""KQL 2 must be able to *name* the construction an expression-bodied callback builds.

The Java ``once-primitive`` fixture hands ``AtomicReference::updateAndGet`` a
lambda whose whole body is a conditional expression::

    guard.updateAndGet(prev -> prev != null ? prev : new Config())

There is no statement to hang a ``construct`` clause on: the allocation exists
only as an operand of that expression.  This module pins the spelling that
reaches it, together with the three near-misses the Java arm must reject (a
per-call cell, a crossed cell, and a construction the accessor does not return).
"""
import pathlib
import tempfile

from ken.kql2.service import search
from tests.structural.test_singleton_once_primitive import source

PATTERN = '''language "kql/2";
module ken.catalog.singleton.variants.once_primitive.java;

pattern detect(out TypeDecl $unit, out Callable $accessor, out Callable $thunk, out Call $construction, out Field $cell) {
  callable $thunk {
    param $previous {}
    body { let $created = construct $unit {} as $construction; }
  }
  type $unit { }
  type $holder {
    field $cell { }
    method $accessor {
      body {
        let $call = call $local_call { receiver: $cell; argument $thunk at 0; };
        return $call;
      }
    }
  }
}

query results {
  use detect(unit: $unit, accessor: $accessor, thunk: $thunk, construction: $construction, cell: $cell);
  select $unit, $accessor, $thunk, $construction, $cell;
}
'''

EXTENSIONS = {'java': 'java', 'go': 'go', 'cpp': 'cpp', 'rust': 'rs', 'csharp': 'cs'}


def _search(language, mode, pattern=PATTERN):
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / f'singleton.{EXTENSIONS[language]}').write_text(source(language, mode))
    return search(directory, pattern, cache_mb=0)


def _bindings(out):
    return [[str(value) for value in row] for row in out['rows']]


def test_java_arm_binds_the_lambdas_construction():
    out = _search('java', 'positive')
    rows = _bindings(out)
    assert len(rows) == 1, (out.get('reason'), out.get('capability'), rows)
    unit, accessor, thunk, construction, cell = rows[0]
    assert unit.endswith('CLASS:Config'), unit
    assert 'CALLABLE:current' in accessor, accessor
    assert 'CALLABLE:anonymous' in thunk, thunk
    # the construction is the ``new Config()`` operand of the lambda's ternary
    assert construction.endswith('CALL:301@301:313'), construction
    assert cell.endswith('STORAGE:guard'), cell


def test_java_reset_still_matches():
    # pinned boundary: re-assigning the cell after the call is not rejected yet
    assert _bindings(_search('java', 'reset')), 'reset'


def test_java_near_misses_are_rejected():
    for mode in ('local', 'crossed', 'fresh'):
        out = _search('java', mode)
        assert not out['rows'], (mode, _bindings(out))


# The construction clause stands on its own: it reads the callable's body, not the
# call that carries the callable, so a pattern that only names the thunk still sees
# the ``new Config()`` the lambda is an operand of.
THUNK_ONLY = '''language "kql/2";
module t;

pattern detect(out TypeDecl $unit, out Callable $thunk, out Call $construction) {
  callable $thunk {
    param $previous {}
    body { let $created = construct $unit {} as $construction; }
  }
  type $unit { }
}

query results {
  use detect(unit: $unit, thunk: $thunk, construction: $construction);
  select $unit, $thunk, $construction;
}
'''


def test_the_construction_clause_reads_the_expression_body_on_its_own():
    rows = _bindings(_search('java', 'positive', THUNK_ONLY))
    assert len(rows) == 1, rows
    unit, thunk, construction = rows[0]
    assert unit.endswith('CLASS:Config'), unit
    assert 'CALLABLE:anonymous' in thunk, thunk
    assert construction.endswith('CALL:301@301:313'), construction
