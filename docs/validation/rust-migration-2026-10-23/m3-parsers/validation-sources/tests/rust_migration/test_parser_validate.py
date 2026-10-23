"""Full parser results and ordered grammar observations cannot disappear."""
from copy import deepcopy
from pathlib import Path
import pytest
from tools.rust_migration.parser_validate import parser_cases, compare_parser_observations, source_identity

REPO = Path(__file__).resolve().parents[2]

@pytest.fixture
def original():
    return parser_cases(REPO)

def native(cases):
    return {'format': 'ken-parser-observation/1', 'cases': [
        {'id': row['id'], **({'error': 'invalid utf-8'} if 'error' in row else
         {'parsed': deepcopy(row['parsed']), 'syntax': deepcopy(row.get('syntax', []))})}
        for row in cases]}

def test_all_languages_and_original_encoding_failures_are_in_the_inventory(original):
    assert len(original) == 239
    assert len({c['input']['language'] for c in original}) == 19
    assert len([c for c in original if 'syntax' in c]) == 215
    assert len([c for c in original if 'error' in c]) == 2
    assert compare_parser_observations(original, native(original)) == []

@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'reorder', 'range', 'kind', 'docs', 'scope', 'annotations', 'syntax', 'error', 'format'])
def test_complete_fields_and_order_are_required(original, mutation):
    actual = native(original); rows = actual['cases']
    if mutation == 'missing': rows.pop()
    elif mutation == 'duplicate': rows[-1] = deepcopy(rows[0])
    elif mutation == 'reorder': rows[0], rows[1] = rows[1], rows[0]
    elif mutation in ('range', 'kind', 'docs'):
        symbol = next(r['parsed']['symbols'][0] for r in rows if r.get('parsed', {}).get('symbols'))
        symbol[{'range': 'line_start', 'kind': 'kind', 'docs': 'docstring'}[mutation]] = -7 if mutation == 'range' else 'changed'
    elif mutation in ('scope', 'annotations'):
        scope = next(r['parsed']['scopes'][0] for r in rows if r.get('parsed', {}).get('scopes'))
        scope['documentation' if mutation == 'scope' else 'annotations'] = 'lost' if mutation == 'scope' else []
        if mutation == 'annotations': scope['annotations'] = ['injected']
    elif mutation == 'syntax': next(r['syntax'] for r in rows if r.get('syntax')).pop()
    elif mutation == 'error': next(r for r in rows if 'error' in r)['error'] = 'other failure'
    else: actual['format'] = 'other'
    assert compare_parser_observations(original, actual)

def test_character_tables_and_grammar_locks_are_source_inputs():
    identities = source_identity(REPO)
    assert 'crates/ken-syntax/src/python_unicode15.json' in identities
    assert 'crates/ken-syntax/grammars.lock.json' in identities

@pytest.mark.parametrize('status', ['ok', 'FAILED'])
def test_rustdoc_compile_fail_inventory_preserves_actual_execution_status(status):
    from tools.rust_migration.parser_evidence import parser_rust_gate_errors
    discovery = 'path.rs - scope::kind (line 84): test\n'
    output = f'test path.rs - scope::kind (line 84) - compile fail ... {status}\n'
    output += f'test result: {"ok" if status == "ok" else "FAILED"}. {1 if status == "ok" else 0} passed; {0 if status == "ok" else 1} failed; 0 ignored;\n'
    assert bool(parser_rust_gate_errors(discovery, output)) == (status != 'ok')
