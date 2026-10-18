"""Public BODY contracts for pending completions and explicit resumption.

These assert source control-flow witnesses, not feasibility of arbitrary Python
exception types. Runtime examples fix the meaning of the nonlocal transfers;
the query examples additionally check value provenance on those paths.
"""

from textwrap import dedent

import pytest

from ken.kql2.service import search


RETURNED = '''
    let $value = call $site { name: "mark_safe"; };
    return $value;
'''
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
        "def cleanup(): pass\n"
    )
    (tmp_path / "sample.py").write_text(declarations + dedent(source))
    query = '''language "kql/2"; module regression.completion_paths;
      query witnesses {
        callable $owner { name: "f"; body { %s } }
        select $owner.name;
      }
    ''' % body
    return search(tmp_path, query, cache_mb=0, timeout_ms=10000)


def assert_witness(result, expected):
    assert result["rows"] == ([["f"]] if expected else [])
    assert result["complete"] and result["coverage_complete"]
    assert result["unknown_candidates"] == 0


@pytest.mark.parametrize(
    "source,body,expected",
    [
        pytest.param(
            """
            def f(value):
                try:
                    made = mark_safe(value)
                finally:
                    alias = made
                return alias
            """, RETURNED, True, id="normal-completion-keeps-finalizer-alias",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return made
                finally:
                    made = None
            """, RETURNED, True, id="pending-return-freezes-operand-before-cleanup",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return None
                finally:
                    return made
            """, RETURNED, True, id="finalizer-return-replaces-pending-return",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return made
                finally:
                    return None
            """, RETURNED, False, id="overridden-return-is-not-a-witness",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return made
                finally:
                    raise RuntimeError()
            """, RETURNED, False, id="finalizer-raise-cancels-pending-return",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return made
                finally:
                    inspect(value)
            """, RETURNED, True, id="finalizer-call-can-complete-before-return",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                finally:
                    compile_query()
            """, ORDERED, True, id="normal-body-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                    return None
                finally:
                    compile_query()
            """, ORDERED, True, id="return-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                    raise RuntimeError()
                finally:
                    compile_query()
            """, ORDERED, True, id="unhandled-raise-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    resolve_query()
                finally:
                    compile_query()
            """, ORDERED, True, id="handler-completion-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except ValueError:
                    resolve_query()
                    raise RuntimeError()
                finally:
                    compile_query()
            """, ORDERED, True, id="handler-raise-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                for item in value:
                    try:
                        resolve_query()
                        break
                    finally:
                        compile_query()
            """, ORDERED, True, id="break-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                for item in value:
                    try:
                        resolve_query()
                        continue
                    finally:
                        compile_query()
            """, ORDERED, True, id="continue-enters-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                for item in value:
                    try:
                        resolve_query()
                        return None
                    finally:
                        break
                compile_query()
            """, ORDERED, True, id="finalizer-break-replaces-pending-return",
        ),
        pytest.param(
            """
            def f(value):
                for item in value:
                    try:
                        resolve_query()
                        return None
                    finally:
                        continue
                    compile_query()
            """, ORDERED, False, id="finalizer-continue-does-not-fall-through-loop-body",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    try:
                        resolve_query()
                        return None
                    finally:
                        cleanup()
                finally:
                    compile_query()
            """, ORDERED, True, id="nested-finalizers-unwind-in-order",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    try:
                        return made
                    finally:
                        return None
                finally:
                    cleanup()
            """, RETURNED, False, id="outer-finalizer-cannot-restore-overridden-return",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                    raise RuntimeError()
                finally:
                    cleanup()
                compile_query()
            """, ORDERED, False, id="unhandled-raise-resumes-after-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                    return None
                finally:
                    cleanup()
                compile_query()
            """, ORDERED, False, id="pending-return-does-not-fall-through-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                    raise RuntimeError()
                finally:
                    return None
                compile_query()
            """, ORDERED, False, id="finalizer-return-does-not-fall-through-after-raise",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    resolve_query()
                except RuntimeError:
                    compile_query()
                finally:
                    raise RuntimeError()
            """, ORDERED, False, id="finalizer-failure-cannot-reenter-its-own-handlers",
        ),
    ],
)
def test_finally_routes_preserve_or_replace_the_pending_completion(
    tmp_path, source, body, expected
):
    assert_witness(run_body(tmp_path, source, body), expected)


@pytest.mark.parametrize(
    "source,body,expected",
    [
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except* ValueError:
                    resolve_query()
                except* TypeError:
                    compile_query()
            """, ORDERED, True, id="split-group-can-run-both-handlers",
        ),
        pytest.param(
            """
            def f(value):
                made = None
                alias = None
                try:
                    inspect(value)
                except* ValueError:
                    made = mark_safe(value)
                except* TypeError:
                    alias = made
                return alias
            """, RETURNED, True, id="later-star-handler-observes-earlier-completed-value",
        ),
        pytest.param(
            """
            def f(value):
                made = None
                alias = None
                try:
                    inspect(value)
                except* ValueError:
                    made = mark_safe(value)
                    made = None
                except* TypeError:
                    alias = made
                return alias
            """, RETURNED, False, id="later-star-handler-observes-overwrite",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except* ValueError:
                    resolve_query()
                    raise RuntimeError()
                except* TypeError:
                    compile_query()
            """, ORDERED, True, id="first-star-handler-raise-still-runs-later-handler",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except* ValueError:
                    resolve_query()
                    raise RuntimeError()
                except* TypeError:
                    cleanup()
                compile_query()
            """, ORDERED, False, id="raised-star-handler-part-prevents-normal-continuation",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    try:
                        inspect(value)
                    except* ValueError:
                        resolve_query()
                        raise RuntimeError()
                    except* TypeError:
                        cleanup()
                except RuntimeError:
                    compile_query()
            """, ORDERED, True, id="merged-star-handler-failure-reaches-outer-handler",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except* ValueError:
                    resolve_query()
                else:
                    compile_query()
            """, ORDERED, False, id="star-handler-and-success-else-remain-exclusive",
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
            """, ORDERED, False, id="ordinary-except-siblings-still-remain-exclusive",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    inspect(value)
                except* ValueError:
                    resolve_query()
                finally:
                    compile_query()
            """, ORDERED, True, id="star-handler-runs-finalizer",
        ),
    ],
)
def test_exception_group_handlers_keep_their_order_and_pending_failure(
    tmp_path, source, body, expected
):
    assert_witness(run_body(tmp_path, source, body), expected)


@pytest.mark.parametrize(
    "source,body,expected",
    [
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                except ValueError:
                    compile_query()
            """,
            'yield null; resume throw; call $done { name: "compile_query"; };',
            True, id="throw-enters-handler-at-suspension",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                except ValueError:
                    compile_query()
            """,
            'yield null; call $done { name: "compile_query"; };',
            False, id="default-resumption-does-not-inject-exception",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                except ValueError:
                    compile_query()
            """,
            'yield null; resume next; call $done { name: "compile_query"; };',
            False, id="explicit-next-does-not-inject-exception",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    yield None
                except ValueError:
                    return made
            """,
            'let $value = call $site { name: "mark_safe"; }; '
            'yield null; resume throw; return $value;',
            True, id="throw-preserves-value-made-before-suspension",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                finally:
                    compile_query()
            """,
            'yield null; resume close; call $done { name: "compile_query"; };',
            True, id="close-enters-finalizer-at-suspension",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                finally:
                    cleanup()
                compile_query()
            """,
            'yield null; resume close; call $done { name: "compile_query"; };',
            False, id="unhandled-close-does-not-run-normal-tail",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                finally:
                    cleanup()
                compile_query()
            """,
            'yield null; resume throw; call $done { name: "compile_query"; };',
            False, id="unhandled-throw-does-not-run-normal-tail",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                finally:
                    cleanup()
                compile_query()
            """,
            'yield null; resume next; call $done { name: "compile_query"; };',
            True, id="next-runs-normal-tail-after-finalizer",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                except GeneratorExit:
                    compile_query()
                    return
            """,
            'yield null; resume close; call $done { name: "compile_query"; };',
            True, id="close-can-be-handled-with-a-normal-return",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                except ValueError:
                    yield None
                    compile_query()
            """,
            'yield null; resume throw; yield null; resume next; '
            'call $done { name: "compile_query"; };',
            True, id="throw-handler-can-yield-and-be-resumed-normally",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                finally:
                    compile_query()
                    yield None
            """,
            'yield null; resume close; call $done { name: "compile_query"; };',
            True, id="close-runs-cleanup-before-an-illegal-yield",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    yield None
                finally:
                    yield None
            """,
            'yield null; resume close; yield null;',
            False, id="close-cannot-successfully-deliver-a-second-yield",
        ),
        pytest.param(
            """
            def f(value):
                try:
                    try:
                        yield None
                    finally:
                        resolve_query()
                finally:
                    compile_query()
            """,
            'yield null; resume close; ' + ORDERED,
            True, id="close-unwinds-nested-finalizers-in-order",
        ),
        pytest.param(
            """
            def f(value):
                yield None
                compile_query()
            """,
            'yield null; resume throw; call $done { name: "compile_query"; };',
            False, id="unhandled-throw-without-protected-block-terminates",
        ),
        pytest.param(
            """
            def f(value):
                yield None
                compile_query()
            """,
            'yield null; resume close; call $done { name: "compile_query"; };',
            False, id="unhandled-close-without-protected-block-terminates",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return made
                finally:
                    yield None
            """,
            'let $value = call $site { name: "mark_safe"; }; '
            'yield null; resume next; return $value;',
            True, id="normal-resumption-preserves-return-pending-across-finalizer-yield",
        ),
        pytest.param(
            """
            def f(value):
                made = mark_safe(value)
                try:
                    return made
                finally:
                    yield None
            """,
            'let $value = call $site { name: "mark_safe"; }; '
            'yield null; resume close; return $value;',
            False, id="close-at-finalizer-yield-cancels-earlier-pending-return",
        ),
    ],
)
def test_generator_resumption_mode_is_explicit_and_path_local(
    tmp_path, source, body, expected
):
    assert_witness(run_body(tmp_path, source, body), expected)


@pytest.mark.parametrize("mode", ["throw", "close"])
def test_delegated_generator_injection_keeps_protocol_uncertainty(tmp_path, mode):
    result = run_body(tmp_path, """
        def f(value):
            try:
                yield from value
            except ValueError:
                compile_query()
    """, f'yield from _; resume {mode}; call $done {{ name: "compile_query"; }};')
    assert result["rows"] == []
    assert result["complete"]
    assert result["unknown_candidates"] > 0


def test_runtime_oracle_finally_freezes_then_replaces_pending_return():
    original = object()

    def preserved():
        made = original
        try:
            return made
        finally:
            made = None

    def replaced():
        try:
            return original
        finally:
            return None

    assert preserved() is original
    assert replaced() is None


def test_runtime_oracle_star_handlers_finish_before_merged_exception_escapes():
    events = []
    with pytest.raises(RuntimeError, match="raised by first handler"):
        try:
            raise ExceptionGroup("split", [ValueError(), TypeError()])
        except* ValueError:
            events.append("first")
            raise RuntimeError("raised by first handler")
        except* TypeError:
            events.append("second")
        finally:
            events.append("finally")
    assert events == ["first", "second", "finally"]


def test_runtime_oracle_close_and_throw_enter_cleanup_from_suspension():
    events = []

    def generator():
        try:
            yield None
        except ValueError:
            events.append("handled")
        finally:
            events.append("finally")
        events.append("tail")

    closed = generator()
    next(closed)
    closed.close()
    assert events == ["finally"]
    events.clear()
    thrown = generator()
    next(thrown)
    with pytest.raises(StopIteration):
        thrown.throw(ValueError())
    assert events == ["handled", "finally", "tail"]


def test_runtime_oracle_failed_close_leaves_a_suspended_generator():
    events = []

    def generator():
        try:
            yield None
        finally:
            events.append("cleanup")
            yield None
            events.append("tail")

    suspended = generator()
    next(suspended)
    with pytest.raises(RuntimeError, match="ignored GeneratorExit"):
        suspended.close()
    assert events == ["cleanup"]
    with pytest.raises(GeneratorExit):
        next(suspended)
    assert events == ["cleanup", "tail"]
