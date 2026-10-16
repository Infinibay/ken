import json

import pytest

from grade_public_v224 import correct_repoqa_piece, load_closed_results
from public_benchmarks_v222 import sha


def test_unclosed_capture_cannot_be_scored(tmp_path):
    (tmp_path / 'r').mkdir()
    (tmp_path / 'r/responses.json').write_text(json.dumps([{'id': 'one', 'results': []}]))
    with pytest.raises(ValueError, match='not closed'):
        load_closed_results(tmp_path, ['one'])


def test_complete_capture_keeps_failed_queries_and_rejects_mutation(tmp_path):
    (tmp_path / 'r').mkdir()
    response = tmp_path / 'r/responses.json'
    response.write_text(json.dumps([{'id': 'one', 'results': [], 'error': 'preparation failed'}]))
    (tmp_path / 'closure.json').write_text(json.dumps({
        'queries': 1, 'response_pins': {'r/responses.json': sha(response)}}))
    assert load_closed_results(tmp_path, ['one'])['one']['error'] == 'preparation failed'
    response.write_text('[]')
    with pytest.raises(ValueError, match='changed'):
        load_closed_results(tmp_path, ['one'])


def test_unknown_missing_and_duplicate_responses_cannot_disappear_from_denominator(tmp_path):
    (tmp_path / 'r').mkdir()
    response = tmp_path / 'r/responses.json'
    response.write_text(json.dumps([{'id': 'one'}, {'id': 'one'}]))
    (tmp_path / 'closure.json').write_text(json.dumps({
        'queries': 2, 'response_pins': {'r/responses.json': sha(response)}}))
    with pytest.raises(ValueError, match='duplicate'):
        load_closed_results(tmp_path, ['one', 'two'])


@pytest.mark.parametrize('result', [
    {'path': 'a.py', 'piece_kind': 'file', 'entity': None, 'entity_span': None},
    {'path': 'a.py', 'piece_kind': 'symbol', 'entity': None},
    {'path': 'a.py', 'piece_kind': 'symbol', 'entity': {'kind': 'function', 'qualname': 'run'}, 'entity_span': None},
])
def test_null_identity_cannot_crash_scoring_or_receive_function_credit(result):
    assert not correct_repoqa_piece(result, {'path': 'a.py', 'name': 'run', 'start_line': 1, 'end_line': 3})
