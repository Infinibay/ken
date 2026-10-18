"""Imported exception names are not evidence of a builtin hierarchy."""
import pytest

from test_completion_paths import run_body


@pytest.mark.parametrize('import_source', [
    'from custom import BaseException',
    'from custom import ValueError as BaseException',
    'import custom as BaseException',
    'from custom import *',
    'class BaseException(ValueError): pass',
    'def BaseException(): pass',
])
def test_imported_close_handler_type_keeps_uncertainty(tmp_path, import_source):
    result = run_body(tmp_path, import_source + '''
def f():
    try:
        yield None
    except BaseException:
        compile_query()
''', 'yield null; resume close; call $done {name:"compile_query";};')
    assert result['rows'] == []
    assert result['complete'] and result['unknown_candidates'] > 0
