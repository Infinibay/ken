"""BODY witnesses follow one statement path and its reaching values.

These are source CFG assertions, not proofs that a branch or exception occurs
at runtime. Generator paths include ordinary resumption; externally injected
``throw`` and ``close`` are outside this contract.
"""

from textwrap import dedent

import pytest

from ken.kql2.service import search


RETURNED = '''
    let $value = call $site { name: "mark_safe"; };
    return $value;
'''
YIELDED = RETURNED.replace("return $value;", "yield $value;")
ORDERED = '''
    call $resolve { name: "resolve_query"; };
    call $compile { name: "compile_query"; };
'''


def run_body(tmp_path, source, body=RETURNED):
    declarations = (
        "def mark_safe(value): return value\n"
        "def inspect(value): pass\n"
        "def resolve_query(): pass\n"
        "def compile_query(): pass\n"
    )
    (tmp_path / "sample.py").write_text(declarations + dedent(source))
    query = '''language "kql/2"; module regression.path_values;
      query witnesses {
        callable $owner { name: "f"; body { %s } }
        select $owner.name;
      }
    ''' % body
    return search(tmp_path, query, cache_mb=0, timeout_ms=10000)


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            """
            def f(value, flag):
                if flag:
                    made = mark_safe(value)
                    alias = made
                else:
                    alias = None
                return alias
            """,
            [["f"]],
            id="branch-result-reaches-joined-return-through-alias",
        ),
        pytest.param(
            """
            def f(value, flag):
                made = mark_safe(value)
                if flag:
                    alias = made
                else:
                    alias = None
                return alias
            """,
            [["f"]],
            id="conditional-copy-retains-one-source-path",
        ),
        pytest.param(
            """
            def f(value, flag):
                made = mark_safe(value)
                if flag:
                    alias = made
                    made = None
                else:
                    alias = None
                return alias
            """,
            [["f"]],
            id="overwriting-original-keeps-earlier-alias",
        ),
        pytest.param(
            """
            def f(value, flag):
                made = mark_safe(value)
                if flag:
                    alias = made
                else:
                    alias = made
                return alias
            """,
            [["f"]],
            id="both-arms-copy-the-same-value",
        ),
        pytest.param(
            """
            def f(value, flag):
                if flag:
                    made = mark_safe(value)
                    alias = None
                else:
                    made = None
                    alias = made
                return alias
            """,
            [],
            id="alias-cannot-borrow-definition-from-exclusive-arm",
        ),
        pytest.param(
            """
            def f(value, flag):
                made = mark_safe(value)
                if flag:
                    alias = made
                    alias = None
                else:
                    alias = None
                return alias
            """,
            [],
            id="every-reaching-alias-is-overwritten",
        ),
        pytest.param(
            """
            def f(value, flag):
                made = mark_safe(value)
                if flag:
                    made = None
                    alias = made
                else:
                    alias = None
                return alias
            """,
            [],
            id="copy-after-overwrite-has-no-original-value",
        ),
    ],
)
def test_conditional_aliases_use_the_values_on_the_witness_path(tmp_path, source, expected):
    result = run_body(tmp_path, source)
    assert result["rows"] == expected
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


@pytest.mark.parametrize(
    "source,body,expected",
    [
        pytest.param(
            """
            def f(value):
                yield mark_safe(value)
            """,
            YIELDED, [["f"]], id="inline-call-result-is-yielded",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                alias = made
                yield alias
            """,
            YIELDED, [["f"]], id="yield-follows-value-alias",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                yield None
                yield made
            """,
            YIELDED, [["f"]], id="resumed-generator-keeps-reaching-value",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                yield made
                alias = made
                return alias
            """,
            RETURNED, [["f"]], id="return-after-resumption-is-a-return",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                yield made
                made = None
                return made
            """,
            RETURNED, [], id="yield-does-not-satisfy-returned-value",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                return made
                yield None
            """,
            YIELDED, [], id="return-does-not-satisfy-yielded-value",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                alias = made
                alias = None
                yield alias
            """,
            YIELDED, [], id="yielded-alias-overwrite-kills-flow",
        ),
        pytest.param(
            """
            def f():
                resolve_query()
                yield None
                compile_query()
            """,
            ORDERED, [["f"]], id="ordinary-resumption-connects-call-order",
        ),
        pytest.param(
            """
            def f():
                resolve_query()
                yield None
                return
                compile_query()
            """,
            ORDERED, [], id="return-after-yield-prevents-fallthrough",
        ),
    ],
)
def test_generator_paths_preserve_values_and_distinguish_yield_from_return(
    tmp_path, source, body, expected
):
    result = run_body(tmp_path, source, body)
    assert result["rows"] == expected
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


@pytest.mark.parametrize(
    "source,body,expected",
    [
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    made = mark_safe(value)
                    alias = made
                    return alias
            """,
            RETURNED, [["f"]], id="value-witness-inside-handler",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    alias = mark_safe(value)
                else:
                    alias = None
                return alias
            """,
            RETURNED, [["f"]], id="handler-value-reaches-following-return",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    inspect(value)
                except ValueError:
                    return made
            """,
            RETURNED, [["f"]], id="value-before-try-reaches-handler",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    made = mark_safe(value)
                    inspect(value)
                except ValueError:
                    return made
            """,
            RETURNED, [["f"]], id="completed-prefix-value-reaches-later-exception",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    made = inspect(value)
                except ValueError:
                    return made
            """,
            RETURNED, [["f"]], id="failed-assignment-retains-previous-value",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    made = mark_safe(value)
                except ValueError:
                    return made
            """,
            RETURNED, [], id="failed-call-does-not-produce-its-result",
        ),
        pytest.param(
            """
            def f(value):
                made = None
                try:
                    made = mark_safe(value)
                except ValueError:
                    return made
            """,
            RETURNED, [], id="failed-rhs-does-not-overwrite-existing-value",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    made = mark_safe(value)
                else:
                    return made
            """,
            RETURNED, [], id="handler-and-success-else-cannot-share-value",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    made = mark_safe(value)
                except TypeError:
                    return made
            """,
            RETURNED, [], id="sibling-handlers-cannot-share-value",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                    inspect(value)
                except ValueError:
                    compile_query()
            """,
            ORDERED, [["f"]], id="completed-prefix-connects-to-handler",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    resolve_query()
                else:
                    compile_query()
            """,
            ORDERED, [], id="handler-and-else-remain-exclusive",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    resolve_query()
                except TypeError:
                    compile_query()
            """,
            ORDERED, [], id="sibling-handlers-remain-exclusive",
        ),
    ],
)
def test_except_without_finally_preserves_the_completed_prefix(
    tmp_path, source, body, expected
):
    result = run_body(tmp_path, source, body)
    assert result["rows"] == expected
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


def test_finally_override_cannot_become_a_returned_value_witness(tmp_path):
    result = run_body(tmp_path, """
        def f(value):
            try:
                made = mark_safe(value)
                return made
            except ValueError:
                return None
            finally:
                return None
    """)
    # Finally can remain outside complete CFG coverage, but cannot add a row.
    assert result["rows"] == []
    assert result["complete"]


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("-value", id="unary-protocol"),
        pytest.param("for item in value:\n    pass", id="iteration-protocol"),
        pytest.param("left, right = value", id="unpacking-protocol"),
        pytest.param("made = missing", id="binding-read"),
        pytest.param("if value:\n    pass", id="truth-protocol"),
        pytest.param("made = value or None", id="boolean-operator"),
        pytest.param('made = f"{value}"', id="formatting-protocol"),
        pytest.param("yield from value", id="delegated-generator-iteration"),
    ],
)
def test_potentially_raising_evaluations_have_handler_routes(tmp_path, statement):
    protected = "\n".join("        " + line for line in statement.splitlines())
    source = (
        "def f(value):\n    try:\n" + protected + "\n"
        "    except ValueError:\n"
        "        made = mark_safe(value)\n"
        "        return made\n"
    )
    result = run_body(tmp_path, source)
    assert result["rows"] == [["f"]]
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


def test_nested_typed_handler_preserves_an_outer_exception_route(tmp_path):
    result = run_body(tmp_path, """
        def f(value):
            try:
                try:
                    inspect(value)
                except TypeError:
                    pass
            except ValueError:
                made = mark_safe(value)
                return made
    """)
    assert result["rows"] == [["f"]]
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


@pytest.mark.parametrize("loop", ["while resolve_query()", "for item in resolve_query()"])
def test_loop_reevaluation_can_fail_after_a_completed_call(tmp_path, loop):
    result = run_body(tmp_path, f"""
        def f(value):
            try:
                {loop}:
                    pass
            except ValueError:
                compile_query()
    """, ORDERED)
    assert result["rows"] == [["f"]]
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


@pytest.mark.parametrize(
    "source,body",
    [
        pytest.param(
            """
            def f(value):
                try:
                    compile_query()
                except resolve_query():
                    pass
            """,
            ORDERED,
            id="header-cannot-precede-the-protected-body",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    compile_query()
                except resolve_query():
                    pass
            """,
            ORDERED,
            id="later-header-cannot-precede-an-earlier-handler",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    return None
                except mark_safe(value):
                    pass
            """,
            'call $site { name: "mark_safe"; }; return null;',
            id="normal-return-does-not-evaluate-an-exception-header",
        ),
    ],
)
def test_dynamic_exception_headers_cannot_create_source_witnesses(tmp_path, source, body):
    result = run_body(tmp_path, source, body)
    assert result["rows"] == []
    assert result["complete"]
    assert result["unknown_candidates"] > 0


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
            def f(value):
                for item in [1]:
                    try:
                        inspect(value)
                    except ValueError as made:
                        made = mark_safe(value)
                        break
                else:
                    return None
                return made
            """,
            id="break-cleans-the-handler-alias",
        ),
        pytest.param(
            """
            def f(value):
                for item in [1]:
                    try:
                        inspect(value)
                    except ValueError as made:
                        made = mark_safe(value)
                        continue
                return made
            """,
            id="continue-cleans-the-handler-alias",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    try:
                        inspect(value)
                    except ValueError as made:
                        made = mark_safe(value)
                        raise RuntimeError()
                except TypeError:
                    return made
            """,
            id="raise-cleans-the-handler-alias",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    try:
                        inspect(value)
                    except ValueError as made:
                        made = mark_safe(value)
                        inspect(value)
                except TypeError:
                    return made
            """,
            id="failed-evaluation-cleans-the-handler-alias",
        ),
    ],
)
def test_every_handler_exit_forgets_its_exception_alias(tmp_path, source):
    result = run_body(tmp_path, source)
    assert result["rows"] == []
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] > 0


def test_unhandled_raise_does_not_move_its_operand_before_the_handler_body(tmp_path):
    reversed_order = '''
        call $compile { name: "compile_query"; };
        call $resolve { name: "resolve_query"; };
    '''
    result = run_body(tmp_path, """
        def f(value):
            try:
                inspect(value)
            except ValueError:
                resolve_query()
                raise compile_query()
    """, reversed_order)
    assert result["rows"] == []
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0
