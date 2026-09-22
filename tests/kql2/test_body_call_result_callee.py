"""Can a captured call result be the callee of the next ``call`` clause?

``dispatch-table.adapted`` invokes the value an adapter returns
(``self.normalize(table[key])(data)``), and the KQL 2 gap list records that
composition as still open (catalog-extensions.md F2 item 5). These two probes
fix the observable contract of the spelling:

    let $adapted = call $adapter { ... } as $lookup;
    call $adapted { ... } as $invocation;

Only the first probe (positive) has to match for the composition to be
expressible; the negative probe states that a call result merely *held* is not
an invocation.
"""
import pathlib
import tempfile

from ken.kql2.service import search


POSITIVE = '''class Router:
 def normalize(self, handler):
  return handler
 def dispatch(self, context):
  return self.normalize(context)(context)
'''

NEGATIVE = '''class Router:
 def normalize(self, handler):
  return handler
 def dispatch(self, context):
  return self.normalize(context)
'''

QUERY = '''language "kql/2";
module t;

pattern detect(out TypeDecl $unit, out Callable $adapter, out Call $invocation) {
  type $unit {
    method $dispatch {
      arity: 1;
      param $context { }
      body {
        let $adapted = call $adapter { argument $context at 0; } as $lookup;
        call $adapted { argument $context at 0; } as $invocation;
      }
    }
  }
}

query results {
  use detect(unit: $unit, adapter: $adapter, invocation: $invocation);
  select $unit, $adapter, $invocation;
}
'''


def run(source):
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / 'sample.py').write_text(source)
    return search(directory, QUERY, cache_mb=0)


def test_call_result_used_as_callee():
    out = run(POSITIVE)
    print('POSITIVE rows', len(out['rows']))
    for key in ('reason', 'capability', 'diagnostics', 'unknown', 'outcomes'):
        if out.get(key):
            print(key, out[key])
    assert len(out['rows']) == 1


def test_call_result_merely_held_is_not_an_invocation():
    out = run(NEGATIVE)
    print('NEGATIVE rows', len(out['rows']))
    assert out['rows'] == []
