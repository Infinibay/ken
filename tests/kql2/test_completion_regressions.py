"""Composition contrasts for injected exceptions and pending completions."""

from textwrap import dedent

import pytest

from ken.kql2.service import search


def run_body(tmp_path, source, body):
    declarations = (
        "def mark_safe(value): return value\n"
        "def compile_query(): pass\n"
        "def resolve_query(): pass\n"
    )
    (tmp_path / "sample.py").write_text(declarations + dedent(source))
    query = '''language "kql/2"; module regression.completion_composition;
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


@pytest.mark.parametrize("mode,header", [("throw", "ValueError"), ("close", "GeneratorExit")])
@pytest.mark.parametrize("initial,updated,expected", [
    ("made", "None", True),
    ("None", "made", False),
])
def test_handled_injection_keeps_the_frozen_return_operand(
    tmp_path, mode, header, initial, updated, expected,
):
    result = run_body(tmp_path, f'''
        def f(value):
            made = mark_safe(value)
            alias = {initial}
            try:
                return alias
            finally:
                try:
                    yield None
                except {header}:
                    alias = {updated}
    ''', 'let $value = call $safe { name: "mark_safe"; }; '
         f'yield null; resume {mode}; return $value;')
    assert_witness(result, expected)


@pytest.mark.parametrize("initial,replacement,expected", [
    ("made", "None", True),
    ("None", "made", False),
])
def test_canceled_inner_return_keeps_the_original_pending_completion(
    tmp_path, initial, replacement, expected,
):
    result = run_body(tmp_path, f'''
        def f(value):
            made = mark_safe(value)
            alias = {initial}
            try:
                return alias
            finally:
                try:
                    try:
                        return {replacement}
                    finally:
                        raise value
                except:
                    alias = {replacement}
    ''', 'let $value = call $safe { name: "mark_safe"; }; return $value;')
    assert_witness(result, expected)


def test_runtime_canceled_inner_return_resumes_the_original_pending_return():
    original = object()
    replacement = object()

    def f():
        alias = original
        try:
            return alias
        finally:
            try:
                try:
                    return replacement
                finally:
                    raise ValueError()
            except ValueError:
                alias = replacement

    assert f() is original


def test_nested_cleanup_continue_discards_the_outer_pending_return(tmp_path):
    result = run_body(tmp_path, '''
        def f(value):
            made = mark_safe(value)
            for item in value:
                try:
                    return made
                finally:
                    try:
                        continue
                    finally:
                        pass
            return None
    ''', 'let $value = call $safe { name: "mark_safe"; }; return $value;')
    assert_witness(result, False)


@pytest.mark.parametrize("source", [
    '''
        def f(value):
            try:
                try:
                    yield None
                finally:
                    pass
            except Exception:
                compile_query()
    ''',
    '''
        def f(value):
            try:
                yield None
            except* Exception:
                compile_query()
    ''',
    '''
        def f(value):
            try:
                try:
                    yield None
                finally:
                    try:
                        raise value
                    except:
                        pass
            except Exception:
                compile_query()
    ''',
])
def test_close_bypasses_exception_headers_through_dispatch_points(tmp_path, source):
    assert_witness(run_body(tmp_path, source,
        'yield null; resume close; call $done { name: "compile_query"; };'), False)


def test_close_selects_the_first_matching_ordinary_handler(tmp_path):
    result = run_body(tmp_path, '''
        def f(value):
            try:
                yield None
            except GeneratorExit:
                pass
            except BaseException:
                compile_query()
    ''', 'yield null; resume close; call $done { name: "compile_query"; };')
    assert_witness(result, False)


@pytest.mark.parametrize("carrier", [
    "if (yield None):\n                    pass",
    "while (yield None):\n                    pass",
    "raise (yield None)",
])
@pytest.mark.parametrize("mode", ["throw", "close"])
def test_unmodeled_suspension_carriers_keep_resumption_unknown(tmp_path, carrier, mode):
    result = run_body(tmp_path, f'''
        def f(value):
            try:
                {carrier}
            except BaseException:
                compile_query()
    ''', f'yield null; resume {mode}; call $done {{ name: "compile_query"; }};')
    assert result["rows"] == []
    assert result["complete"]
    assert result["unknown_candidates"] > 0


@pytest.mark.parametrize("first,second", [
    ("ValueError", "ValueError"),
    ("BaseException", "ValueError"),
    ("Exception", "ValueError"),
])
def test_star_handler_cannot_match_a_subgroup_consumed_by_an_earlier_header(
    tmp_path, first, second,
):
    result = run_body(tmp_path, f'''
        def f(value):
            try:
                raise value
            except* {first}:
                resolve_query()
            except* {second}:
                compile_query()
    ''', 'call $first { name: "resolve_query"; }; '
         'call $second { name: "compile_query"; };')
    assert_witness(result, False)


@pytest.mark.parametrize("first,second", [
    ("ValueError", "ValueError"),
    ("BaseException", "ValueError"),
    ("Exception", "ValueError"),
])
def test_skipped_star_header_still_excludes_its_types_from_later_handlers(
    tmp_path, first, second,
):
    result = run_body(tmp_path, f'''
        def f(value):
            try:
                raise value
            except* {first}:
                pass
            except* {second}:
                compile_query()
    ''', 'call $second { name: "compile_query"; };')
    assert_witness(result, False)


def test_star_catchall_cannot_propagate_an_unmatched_remainder(tmp_path):
    result = run_body(tmp_path, '''
        def f(value):
            made = None
            try:
                try:
                    raise value
                except* BaseException:
                    made = mark_safe(value)
            except:
                return made
            return None
    ''', 'let $value = call $safe { name: "mark_safe"; }; return $value;')
    assert_witness(result, False)


def test_close_singleton_does_not_gain_other_subgroups_after_a_handler(tmp_path):
    result = run_body(tmp_path, '''
        def f(value):
            try:
                yield None
            except* GeneratorExit:
                resolve_query()
            except* ValueError:
                compile_query()
    ''', 'yield null; resume close; '
         'call $first { name: "resolve_query"; }; '
         'call $second { name: "compile_query"; };')
    assert_witness(result, False)


@pytest.mark.parametrize("header,rebound", [
    ("Exception", "BaseException"),
    ("BaseException", "ValueError"),
])
def test_module_shadowed_builtin_headers_keep_close_dispatch_unknown(
    tmp_path, header, rebound,
):
    result = run_body(tmp_path, f'''
        {header} = {rebound}

        def f(value):
            try:
                yield None
            except {header}:
                compile_query()
    ''', 'yield null; resume close; call $done { name: "compile_query"; };')
    assert result["rows"] == []
    assert result["complete"]
    assert result["unknown_candidates"] > 0
