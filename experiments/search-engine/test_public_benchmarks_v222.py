import math
from pathlib import Path

import pytest

from public_benchmarks_v222 import (
    checked_path, core_documents, retrieval_metrics, repoqa_correct_piece,
    repoqa_request,
)


def test_query_projection_does_not_leak_reference_or_rewrite_text():
    needle = {'description': '\nMerge adjacent strings.\n', 'name': 'secret',
              'path': 'secret.py', 'start_line': 10}
    value = repoqa_request('python', 'owner/repo', 0, needle, Path('/tmp/repo'))
    assert value['query'] == needle['description']
    assert set(value) == {'id', 'repo_id', 'root', 'query', 'scope', 'piece_kind'}
    assert 'secret' not in str(value)


@pytest.mark.parametrize('name', ['../escape.py', '/absolute.py', 'a/../../x.py'])
def test_snapshot_cannot_escape_destination(tmp_path, name):
    with pytest.raises(ValueError):
        checked_path(tmp_path, name)


def test_core_eligibility_uses_public_snapshot_filter_without_positive_labels():
    documents = [{'_id': 'a', 'text': 'x\ny'}, {'_id': 'b', 'text': 'z'}]
    selected = core_documents(documents, ['a'])
    assert selected == {'documents/a.txt': {'id': 'a', 'text': 'x\ny'}}
    with pytest.raises(ValueError, match='missing'):
        core_documents(documents, ['c'])


def test_correct_piece_requires_file_name_function_kind_and_definition():
    gold = {'path': 'a.py', 'name': 'run', 'start_line': 10, 'end_line': 20}
    good = {'path': 'a.py', 'piece_kind': 'symbol',
            'entity': {'kind': 'method', 'qualname': 'Runner.run'},
            'entity_span': {'start_line': 11, 'end_line': 20}}
    assert repoqa_correct_piece(good, gold)
    assert not repoqa_correct_piece(good | {'path': 'other.py'}, gold)
    assert not repoqa_correct_piece(good | {'entity_span': {'start_line': 21, 'end_line': 30}}, gold)
    assert not repoqa_correct_piece(good | {'entity': {'kind': 'class', 'qualname': 'run'}}, gold)
    assert not repoqa_correct_piece(good | {'entity': {'kind': 'method', 'qualname': 'Runner.other'}}, gold)
    assert not repoqa_correct_piece(good | {'piece_kind': 'file'}, gold)


def test_multilabel_metrics_distinguish_any_hit_from_recall_and_dcg():
    metric = retrieval_metrics(['wrong', 'b', 'a'], {'a': 1, 'b': 1, 'c': 1}, k=10)
    assert metric['hit1'] == 0 and metric['hit10'] == 1
    assert metric['recall10'] == 2 / 3
    assert metric['ndcg10'] == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(4)) /
        (1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)))
    assert retrieval_metrics([], {'a': 1}, k=10)['ndcg10'] == 0


def test_duplicate_predictions_do_not_multiply_relevance():
    with pytest.raises(ValueError, match='duplicate'):
        retrieval_metrics(['a', 'a'], {'a': 1}, k=10)
