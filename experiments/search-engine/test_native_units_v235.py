import pytest

from native_units_v235 import correct_file, correct_piece


@pytest.fixture
def target():
    return {'path': 'package/engine.py', 'kind': 'method', 'qualname': 'Runner.execute',
        'start_line': 12, 'declaration_start_line': 10, 'end_line': 24,
        'source_sha256': 'source', 'anchor_ranges': [{'start_line': 18, 'end_line': 20}]}


@pytest.fixture
def result():
    return {'path': 'package/engine.py', 'piece_kind': 'symbol',
        'entity': {'kind': 'method', 'qualname': 'Runner.execute'},
        'entity_span': {'start_line': 12, 'end_line': 24},
        'evidence': [], 'source_hash': 'source', 'stale': False}


def test_exact_responsible_unit_counts_without_requiring_its_visible_body(result, target):
    assert correct_piece(result, target)
    assert correct_file(result, target)


def test_correct_file_cannot_credit_a_different_symbol(result, target):
    result['entity']['qualname'] = 'Runner.unrelated'
    assert correct_file(result, target)
    assert not correct_piece(result, target)


def test_whole_file_or_containing_class_requires_the_specific_fragment(result, target):
    result.update(piece_kind='file', entity={'kind': 'file', 'qualname': None},
                  entity_span={'start_line': 1, 'end_line': 100})
    assert not correct_piece(result, target)
    result['evidence'] = [{'start_line': 18, 'end_line': 19, 'content': 'only a partial anchor'}]
    assert not correct_piece(result, target)
    result['evidence'] = [{'start_line': 17, 'end_line': 21, 'content': 'specific source'}]
    assert correct_piece(result, target)


def test_mislabelled_same_extent_does_not_become_the_correct_function(result, target):
    result['entity']['kind'] = 'class'
    assert not correct_piece(result, target)


def test_only_source_bound_decorator_variation_is_allowed(result, target):
    for start in (10, 11, 12):
        result['entity_span']['start_line'] = start
        assert correct_piece(result, target)
    result['entity_span']['start_line'] = 9
    assert not correct_piece(result, target)


def test_wrong_definition_end_cannot_credit_repeated_qualname(result, target):
    result['entity_span']['end_line'] = 25
    assert not correct_piece(result, target)


@pytest.mark.parametrize('entity', [None, {}, {'kind': 'file', 'qualname': None}])
def test_null_or_generic_identity_needs_verified_fragment(result, target, entity):
    result['entity'] = entity
    assert not correct_piece(result, target)


def test_wrong_source_version_or_path_or_stale_never_counts(result, target):
    result['source_hash'] = 'changed'
    assert not correct_piece(result, target)
    assert not correct_file(result, target)
    result['source_hash'] = 'source'
    result['path'] = 'other.py'
    assert not correct_piece(result, target)
    result['path'] = target['path']
    result['stale'] = True
    assert not correct_piece(result, target)


def test_fragment_reference_does_not_credit_a_whole_module_by_identity(result, target):
    target.update(kind='fragment', qualname=None, start_line=1, end_line=100)
    result.update(entity={'kind': 'module', 'qualname': None},
                  entity_span={'start_line': 1, 'end_line': 100})
    assert not correct_piece(result, target)
    result['evidence'] = [{'start_line': 18, 'end_line': 20, 'content': 'verified fragment'}]
    assert correct_piece(result, target)
