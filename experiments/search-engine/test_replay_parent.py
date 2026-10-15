import hashlib
import json

import numpy as np
import pytest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path):
    base, parent = tmp_path/'base', tmp_path/'parent'
    (base/'requests').mkdir(parents=True)
    parent.mkdir()
    requests = [{'id': 'q', 'repo_id': 'repo', 'request': {'query': 'a behavior'}}]
    (base/'requests/repo.jsonl').write_text(json.dumps(requests[0])+'\n')
    # Distinct canonical owners can share the same file/source hash.
    candidates = [{'path': 'same.py', 'entity': {'qualname': name}, 'source_hash': 'same'}
                  for name in ('first', 'second')]
    (base/'candidates.jsonl').write_text(json.dumps({'id': 'q', 'candidates': candidates})+'\n')
    np.savez(base/'repo.npz', x=np.array([[1., 2.], [3., 4.]]), qid=['q', 'q'], index=[0, 1])
    np.savez(parent/'repo.npz', x=np.array([[1., 2., 5.], [3., 4., 6.]]), qid=['q', 'q'], index=[0, 1])
    (base/'registration.json').write_text(json.dumps({'repos': {'repo': {
        'requests_sha256': sha(base/'requests/repo.jsonl'), 'features_sha256': sha(base/'repo.npz')}}}))
    (parent/'registration.json').write_text(json.dumps({'features': ['a', 'b', 'extra'],
        'query_repos': {'repo': {'output_sha256': sha(parent/'repo.npz')}},
        'public_inputs': {str(base/'candidates.jsonl'): sha(base/'candidates.jsonl'),
                          str(base/'registration.json'): sha(base/'registration.json')}}))
    return base, parent


def test_complete_parent_has_an_explicit_file_and_row_binding(tmp_path):
    from replay_parent import validate_replay_parent

    base, parent = fixture(tmp_path)
    receipts = validate_replay_parent(parent, base)
    assert receipts[str(base/'candidates.jsonl')] == sha(base/'candidates.jsonl')
    assert receipts[str(parent/'repo.npz')] == sha(parent/'repo.npz')


def test_reordered_same_file_owners_are_rejected_even_with_equal_counts_and_hashes(tmp_path):
    from replay_parent import validate_replay_parent

    base, parent = fixture(tmp_path)
    row = json.loads((base/'candidates.jsonl').read_text())
    row['candidates'].reverse()
    (base/'candidates.jsonl').write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError):
        validate_replay_parent(parent, base)


@pytest.mark.parametrize('corruption', ['index', 'prefix', 'qid'])
def test_redeclaring_a_new_npz_hash_does_not_hide_wrong_row_identity(tmp_path, corruption):
    from replay_parent import validate_replay_parent

    base, parent = fixture(tmp_path)
    data = np.load(parent/'repo.npz')
    values = {key: data[key] for key in data.files}
    if corruption == 'index':
        values['index'] = values['index'][::-1]
    elif corruption == 'prefix':
        values['x'] = values['x'][::-1]
    else:
        values['qid'] = np.array(['wrong', 'q'])
    np.savez(parent/'repo.npz', **values)
    record = json.loads((parent/'registration.json').read_text())
    record['query_repos']['repo']['output_sha256'] = sha(parent/'repo.npz')
    (parent/'registration.json').write_text(json.dumps(record))
    with pytest.raises(ValueError):
        validate_replay_parent(parent, base)


@pytest.mark.parametrize('corruption', [None, 'index', 'prefix', 'qid'])
def test_an_appended_feature_extension_keeps_the_complete_bound_parent(tmp_path, corruption):
    from replay_parent import validate_replay_parent

    base, parent = fixture(tmp_path)
    extension = tmp_path/'extension'
    extension.mkdir()
    values = {'x': np.array([[1., 2., 5., 7.], [3., 4., 6., 8.]]),
              'qid': np.array(['q', 'q']), 'index': np.array([0, 1])}
    if corruption == 'index':
        values['index'] = values['index'][::-1]
    elif corruption == 'prefix':
        values['x'] = values['x'][::-1]
    elif corruption == 'qid':
        values['qid'] = np.array(['wrong', 'q'])
    np.savez(extension/'repo.npz', **values)
    (extension/'registration.json').write_text(json.dumps({
        'features': ['a', 'b', 'extra', 'extension'],
        'parent_features_registration_sha256': sha(parent/'registration.json'),
        'query_repos': {'repo': {'output_sha256': sha(extension/'repo.npz'),
                               'parent_features_sha256': sha(parent/'repo.npz')}}}))
    if corruption:
        with pytest.raises(ValueError):
            validate_replay_parent(parent, base, extension=extension)
    else:
        receipts = validate_replay_parent(parent, base, extension=extension)
        assert receipts[str(extension/'repo.npz')] == sha(extension/'repo.npz')
