"""BODY ordering in Python resource scopes and around exceptional suffixes.

The real QuerySession benchmark asks whether resolve_query precedes
compile_query on a statement path. Unrelated exceptional code later in the
method must not erase that witness, and supporting resource scopes must not
flatten exclusive branches or turn raise into fallthrough.
"""

import ast
from pathlib import Path
from textwrap import dedent, indent

import pytest

from ken.kql2.service import search


QUERY = '''language "kql/2";
module control.order;
pattern ResolvesBeforeCompile(in Callable $owner) {
  callable $owner { body {
    call $resolve { name: "resolve_query"; };
    call $compile { name: "compile_query"; };
  } }
}
query ordered {
  callable $f { name: "f"; }
  use ResolvesBeforeCompile(owner: $f);
  select $f.name;
}
'''


def run_order(tmp_path, source, query=QUERY):
    targets = "def resolve_query(): pass\ndef compile_query(*args, **kwargs): pass\n"
    (tmp_path / "sample.py").write_text(targets + dedent(source))
    return search(tmp_path, query, cache_mb=0, timeout_ms=10000)


@pytest.mark.parametrize(
    "body,expected",
    [
        pytest.param(
            """
            def f():
                resolve_query()
                compile_query()
            """,
            [["f"]],
            id="straight-line-baseline",
        ),
        pytest.param(
            """
            def f(flag):
                if flag:
                    resolve_query()
                else:
                    compile_query()
            """,
            [],
            id="exclusive-arms-baseline",
        ),
        pytest.param(
            """
            def f():
                resolve_query()
                return
                compile_query()
            """,
            [],
            id="return-baseline",
        ),
        pytest.param(
            """
            def f(lock):
                resolve_query()
                with lock:
                    inspect()
                compile_query()
            """,
            [["f"]],
            id="order-across-with",
        ),
        pytest.param(
            """
            def f(lock):
                with lock:
                    resolve_query()
                    compile_query()
            """,
            [["f"]],
            id="order-inside-with",
        ),
        pytest.param(
            """
            def f(lock, dirty):
                resolve_query()
                with lock:
                    if dirty:
                        raise RuntimeError("stale")
                compile_query()
            """,
            [["f"]],
            id="order-through-with-guard",
        ),
        pytest.param(
            """
            def f(lock, flag):
                with lock:
                    if flag:
                        resolve_query()
                    else:
                        compile_query()
            """,
            [],
            id="exclusive-arms-inside-with",
        ),
        pytest.param(
            """
            def f(lock):
                with lock:
                    resolve_query()
                    return
                compile_query()
            """,
            [],
            id="return-exits-with-body",
        ),
        pytest.param(
            """
            def f():
                resolve_query()
                raise RuntimeError("stop")
                compile_query()
            """,
            [],
            id="raise-has-no-fallthrough",
        ),
        pytest.param(
            """
            def f(flag):
                if flag:
                    resolve_query()
                    raise RuntimeError("stop")
                else:
                    compile_query()
            """,
            [],
            id="raise-does-not-join-exclusive-arm",
        ),
        pytest.param(
            """
            def f():
                resolve_query()
                compile_query()
                try:
                    inspect()
                except RuntimeError:
                    recover()
                finally:
                    cleanup()
            """,
            [["f"]],
            id="known-order-before-exceptional-suffix",
        ),
    ],
)
def test_order_preserves_statement_paths_without_global_partial_poisoning(
    tmp_path, body, expected
):
    result = run_order(tmp_path, body)
    assert result["rows"] == expected
    assert result["complete"]
    assert result["unknown_candidates"] == 0


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
            def f():
                try:
                    inspect()
                except ValueError:
                    resolve_query()
                except TypeError:
                    compile_query()
            """,
            id="sibling-handlers-are-exclusive",
        ),
        pytest.param(
            """
            def f():
                try:
                    inspect()
                except ValueError:
                    resolve_query()
                else:
                    compile_query()
            """,
            id="handler-and-success-else-are-exclusive",
        ),
        pytest.param(
            """
            def f():
                try:
                    resolve_query()
                finally:
                    raise RuntimeError("stop")
                compile_query()
            """,
            id="finally-raise-prevents-following-call",
        ),
        pytest.param(
            """
            def f():
                try:
                    resolve_query()
                    return
                finally:
                    cleanup()
                compile_query()
            """,
            id="finally-normal-exit-does-not-cancel-return",
        ),
    ],
)
def test_exception_regions_never_invent_a_connecting_path(tmp_path, source):
    result = run_order(tmp_path, source)
    # Unknown is still honest for exceptional regions the CFG cannot model.
    # The forbidden outcome is a positive witness fabricated by lexical order.
    assert result["rows"] == []


def test_real_query_session_resolves_before_compiling(tmp_path):
    root = Path(__file__).resolve().parents[2]
    source = (root / "src/ken/kql2/session.py").read_text()
    session = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == "QuerySession"
    )
    # Keep the actual benchmarked bodies, with local declarations for the call
    # targets so this focused test does not need the entire production project.
    methods = [
        ast.get_source_segment(source, method)
        for method in session.body
        if isinstance(method, ast.FunctionDef)
        and method.name in {"prepare_query", "search"}
    ]
    source = "class QuerySession:\n    def resolve_query(self, *args, **kwargs): pass\n"
    source += "\n".join(indent(dedent(method), "    ") for method in methods)
    query = QUERY.replace(
        'callable $f { name: "f"; }',
        'class $session { name: "QuerySession"; '
        'method $f { name: /^(prepare_query|search)$/; } }',
    )
    result = run_order(tmp_path, source, query)
    assert sorted(result["rows"]) == [["prepare_query"], ["search"]]
    assert result["complete"]
    assert result["unknown_candidates"] == 0
