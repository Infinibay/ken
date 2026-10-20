"""Original-only evidence validates structure; it never certifies native inference."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

CATALOG = Path(__file__).resolve().parents[2] / 'crates/ken-models/resources/transformer-catalog.json'


def test_profile_execution_budget_uses_only_finite_original_measurements():
    from tools.rust_migration.transformer_reference import freeze_profile_budget
    record = original()
    record['capture']['preparation_s'] = 2.0
    record['capture']['results'][0]['elapsed_s'] = 20.0
    budget = freeze_profile_budget(record)
    assert budget['original_total_seconds'] == 22.0
    assert budget['execution_deadline_seconds'] == 66
    assert budget['acquisition_outside_deadline'] is True
    assert budget['vector_max_absolute_error'] == 1e-6
    assert budget['raw_score_max_absolute_error'] == 1e-5
    record['capture']['results'][0]['elapsed_s'] = 0.1
    assert freeze_profile_budget(record)['execution_deadline_seconds'] == 60
    for bad in (-1, float('inf'), float('nan'), True, None, '2'):
        record['capture']['preparation_s'] = bad
        with pytest.raises(ValueError, match='timing'):
            freeze_profile_budget(record)
    record['capture']['preparation_s'] = 2.0
    record['capture']['results'][0].pop('elapsed_s')
    with pytest.raises(ValueError, match='timing'):
        freeze_profile_budget(record)


def test_original_repeat_compares_values_and_feeds_ignoring_only_measurements():
    from tools.rust_migration.transformer_reference import validate_repeat
    first=original();second=deepcopy(first)
    second['capture']['preparation_s']=10.0
    second['capture']['peak_rss_process_bytes']=99999
    second['capture']['results'][0]['elapsed_s']=20.0
    validate_repeat(first,second)
    second['capture']['results'][0]['vectors_f32le_hex']=(struct.pack('<1024f',2.,*([0.]*1023))*2).hex()
    with pytest.raises(ValueError,match='repeat'):
        validate_repeat(first,second)
    second=deepcopy(first);second['capture']['feeds'][0]['inputs']['input_ids'][0][0]=63
    with pytest.raises(ValueError,match='repeat'):
        validate_repeat(first,second)


def original():
    catalog = json.loads(CATALOG.read_text())
    model = next(row for row in catalog['models'] if row['name'] == 'Qwen/Qwen3-Embedding-0.6B')
    vector = struct.pack('<1024f', 1., *([0.] * 1023))
    files = [dict(path=name, **row) for name, row in model['assets']['artifacts'].items()]
    return {'format': 'ken-transformer-original/1', 'adapter': 'sentence', 'platform': 'macos',
            'capture': {'settings': {'model_id': model['name'], 'revision': model['assets']['revision'],
                        'dtype': 'float32', 'device_request': 'cpu', 'sequence_length': 512, 'batch_size': 16},
                'original_source_sha256': catalog['original_sources']['sentence']['sha256'],
                'model_registration': dict(model_id=model['name'], revision=model['assets']['revision'], files=files),
                'package_versions': {'torch': '2.9.0', 'numpy': '2.4.4', 'sentence-transformers': '5.6.1',
                                     'transformers': '4.57.6', 'tokenizers': '0.22.2'},
                'dimension': 1024, 'empty_batch_did_not_load': True, 'count_did_not_load_model': True,
                'counts': {'lexical': [1, 1]}, 'long_count': 701,
                'requests': [{'id': 'lexical', 'side': 'passages', 'texts': ['a', 'b']}],
                'results': [{'id': 'lexical', 'passed_original_call': True, 'shape': [2, 1024],
                             'finite': True, 'vectors_f32le_hex': (vector * 2).hex(), 'device_after': 'cpu',
                             'feed_range': [0, 1], 'elapsed_s': 0.1}],
                'feeds': [{'case': 'lexical', 'actual_device': 'cpu', 'weight_dtype': 'torch.float32',
                           'shape': [2, 1], 'inputs': {'input_ids': [[64], [65]], 'attention_mask': [[1], [1]]}}],
                'preparation_s': 0.2, 'peak_rss_process_bytes': 10000, 'model_inference_accepted': False}}


def test_successful_original_requires_actual_feeds():
    from tools.rust_migration.transformer_reference import validate_original
    record = original()
    validate_original(record)
    record['capture']['feeds'] = []
    with pytest.raises(ValueError, match='feed'):
        validate_original(record)


@pytest.mark.parametrize('mutation', [
    lambda r: r['capture']['settings'].update(revision='main'),
    lambda r: r['capture']['settings'].update(dtype='int8'),
    lambda r: r['capture']['settings'].update(sequence_length=0),
    lambda r: r['capture']['package_versions'].update(torch='2.14.0'),
    lambda r: r['capture'].update(original_source_sha256='0' * 64),
    lambda r: r['capture']['model_registration']['files'].pop(),
    lambda r: r['capture']['results'][0].update(shape=[1, 1024]),
    lambda r: r['capture']['results'][0].update(vectors_f32le_hex='0000'),
    lambda r: r['capture']['feeds'][0]['inputs'].update(input_ids=[[True], [65]]),
    lambda r: r['capture']['feeds'][0]['inputs'].update(attention_mask=[[2], [1]]),
    lambda r: r['capture']['feeds'][0].update(actual_device='mps'),
    lambda r: r['capture']['results'][0].update(id='unrelated'),
    lambda r: r['capture'].update(model_inference_accepted=True),
])
def test_original_rows_bind_tokens_vectors_versions_and_data(mutation):
    from tools.rust_migration.transformer_reference import validate_original
    record = original()
    mutation(record)
    with pytest.raises(ValueError):
        validate_original(record)


def test_original_cannot_hide_nonfinite_vectors_with_finite_flag():
    from tools.rust_migration.transformer_reference import validate_original
    record = original()
    record['capture']['results'][0]['vectors_f32le_hex'] = struct.pack('<2048f', float('nan'), *([0.] * 2047)).hex()
    with pytest.raises(ValueError, match='finite'):
        validate_original(record)


def test_inventory_cannot_omit_profile_or_case():
    from tools.rust_migration.transformer_reference import required_inventory, validate_inventory
    record = original()
    inventory = required_inventory()
    for records in ([], [record, record]):
        with pytest.raises(ValueError, match='profile'):
            validate_inventory(records, inventory)
    bad = deepcopy(inventory)
    bad['profiles'][0]['cases'].append('batch17')
    with pytest.raises(ValueError, match='case'):
        validate_inventory([record], bad)


def test_complete_inventory_is_fixed_by_source_not_a_resealed_receipt():
    from tools.rust_migration.transformer_reference import required_inventory, validate_inventory
    inventory = required_inventory()
    assert len(inventory['profiles']) == 33
    assert sum(len(row['cases']) for row in inventory['profiles']) == 432
    with pytest.raises(ValueError, match='profile'):
        validate_inventory([], {'profiles': []})
    bad = deepcopy(inventory)
    bad['profiles'].pop()
    with pytest.raises(ValueError, match='profile'):
        validate_inventory([], bad)


def test_raw_chunks_authenticate_and_bound(tmp_path):
    from tools.rust_migration.transformer_reference import read_original, write_original
    record = original()
    receipt = write_original(tmp_path, 'original', record)
    assert read_original(tmp_path, receipt) == record
    path = tmp_path / receipt['path']
    payload = path.read_bytes()
    path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    with pytest.raises(ValueError):
        read_original(tmp_path, receipt)
    payload = gzip.compress(b' ' * (16 * 1024 * 1024 + 1), mtime=0)
    path.write_bytes(payload)
    receipt.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    with pytest.raises(ValueError, match='bound'):
        read_original(tmp_path, receipt)


def test_original_errors_cannot_masquerade_as_outputs(tmp_path):
    from tools.rust_migration.transformer_reference import read_original
    from tools.rust_migration.fastembed_reference import write_chunk
    record = original()
    record['capture']['results'][0].update(passed_original_call=False, error='RuntimeError: unavailable')
    receipt = write_chunk(tmp_path, 'resealed', record)
    with pytest.raises(ValueError, match='error'):
        read_original(tmp_path, receipt)


def judge_original():
    record = original()
    catalog = json.loads(CATALOG.read_text())
    model = next(row for row in catalog['models'] if row['role'] == 'judge')
    record['adapter'] = 'judge'
    capture = record['capture']
    capture['settings'].update(model_id=model['name'], revision=model['assets']['revision'], backend='torch')
    capture['original_source_sha256'] = catalog['original_sources']['judge']['sha256']
    capture['model_registration'] = dict(model_id=model['name'], revision=model['assets']['revision'],
        files=[dict(path=name, **row) for name, row in model['assets']['artifacts'].items()])
    capture['dimension'] = 1
    capture['loaded_before_cases'] = True
    capture['requests'] = [{'id': 'purpose_tests', 'query': 'query', 'documents': ['a', 'b'],
                            'purpose': 'tests', 'sequence_length': 512, 'remaining': 16,
                            'query_token_count': 1, 'query_ids': [64]}]
    capture['results'][0].update(id='purpose_tests', shape=[2], scores_f32le_hex=struct.pack('<2f', -2., 10.).hex())
    del capture['results'][0]['vectors_f32le_hex']
    capture['feeds'][0].update(case='purpose_tests', projection_ids=[9693, 2152])
    return record


def test_judge_reference_preserves_raw_scores_and_query_bound():
    from tools.rust_migration.transformer_reference import validate_original
    record = judge_original()
    validate_original(record)
    record['capture']['requests'][0].update(query_token_count=129, query_ids=[64] * 129)
    with pytest.raises(ValueError, match='query'):
        validate_original(record)


def test_judge_budget_error_is_exact_and_has_no_fabricated_output():
    from tools.rust_migration.transformer_reference import validate_original
    record = judge_original()
    capture = record['capture']
    capture['requests'][0].update(documents=[], remaining=15, expected_error='ValueError')
    capture['results'][0] = {'id': 'purpose_tests', 'passed_original_call': False,
        'exception': 'ValueError', 'message': 'joint model sequence budget cannot contain query and source',
        'feed_range': [0, 0], 'device_after': 'cpu'}
    capture['feeds'] = []
    validate_original(record)
    capture['results'][0]['scores_f32le_hex'] = '00000000'
    with pytest.raises(ValueError, match='error'):
        validate_original(record)


def test_judge_empty_documents_still_require_original_load_and_budget_check():
    from tools.rust_migration.transformer_reference import validate_original
    record = judge_original()
    capture = record['capture']
    capture['requests'][0].update(documents=[], expected_error='IndexError')
    capture['results'][0] = {'id': 'purpose_tests', 'passed_original_call': False,
        'exception': 'IndexError', 'message': 'list index out of range',
        'feed_range': [0, 0], 'device_after': 'cpu'}
    capture['feeds'] = []
    validate_original(record)
    capture['loaded_before_cases'] = False
    with pytest.raises(ValueError, match='load'):
        validate_original(record)


def test_judge_empty_tokenizer_error_cannot_hide_nonempty_failure():
    from tools.rust_migration.transformer_reference import validate_original
    record = judge_original()
    record['capture']['requests'][0].update(expected_error='IndexError')
    record['capture']['results'][0] = {'id': 'purpose_tests', 'passed_original_call': False,
        'exception': 'IndexError', 'message': 'list index out of range',
        'feed_range': [0, 0], 'device_after': 'cpu'}
    record['capture']['feeds'] = []
    with pytest.raises(ValueError):
        validate_original(record)


def judge_demotion_original():
    record = judge_original()
    capture = record['capture']
    capture['settings'].update(dtype='float16', device_request='mps')
    request = deepcopy(capture['requests'][0])
    request.update(id='budget15', remaining=15, expected_error='ValueError')
    capture['requests'].insert(0, request)
    message = 'joint model sequence budget cannot contain query and source'
    attempts = [{'device': device, 'dtype': dtype, 'outcome': 'exception', 'exception': 'ValueError',
                 'message': message, 'feed_range': [0, 0]} for device, dtype in [('mps', 'float16'), ('cpu', 'float32')]]
    capture['results'].insert(0, {'id': 'budget15', 'passed_original_call': False, 'exception': 'ValueError',
        'message': message, 'feed_range': [0, 0], 'device_after': 'cpu', 'attempts': attempts})
    capture['results'][1]['attempts'] = [{'device': 'cpu', 'dtype': 'float32', 'outcome': 'returned',
                                        'finite': True, 'feed_range': [0, 1]}]
    return record


def test_judge_budget_failure_demotes_once_and_subsequent_cases_use_cpu_float32():
    from tools.rust_migration.transformer_reference import validate_original
    record = judge_demotion_original()
    validate_original(record)
    record['capture']['feeds'][0]['weight_dtype'] = 'torch.float16'
    with pytest.raises(ValueError, match='dtype'):
        validate_original(record)


@pytest.mark.parametrize('mutation', [
    lambda r: r['capture']['results'][0]['attempts'].pop(),
    lambda r: r['capture']['results'][0]['attempts'][0].update(exception='IndexError'),
    lambda r: r['capture']['results'][0]['attempts'][1].update(dtype='float16'),
    lambda r: r['capture']['results'][1]['attempts'][0].update(device='mps'),
])
def test_judge_retry_cannot_be_fabricated_or_return_to_accelerator(mutation):
    from tools.rust_migration.transformer_reference import validate_original
    record = judge_demotion_original()
    mutation(record)
    with pytest.raises(ValueError):
        validate_original(record)


def test_published_original_corpus_matches_fixed_inventory():
    from tools.rust_migration.transformer_reference import freeze_profile_budget, profile_key, read_original, validate_inventory, validate_repeat
    from tools.rust_migration.fastembed_reference import read_chunk
    directory = CATALOG.parents[3] / 'docs/validation/rust-migration-2026-10-20/m2-transformer-reference'
    index = json.loads((directory / 'INDEX.json').read_text())
    assert index['format'] == 'ken-transformer-original-reference/1'
    assert index['model_inference_accepted'] is False
    assert index['original_guard']['passed'] is True and index['original_guard']['files'] == 1066
    records = []
    for chunk in index['chunks']:
        record = read_original(directory, chunk['receipt'])
        assert profile_key(record) == chunk['key']
        records.append(record)
    validate_inventory(records, index['inventory'])
    assert index['execution_budgets']['legacy_execution_deadline_seconds'] == 600
    assert index['execution_budgets']['profiles'] == {profile_key(record): freeze_profile_budget(record) for record in records}
    by_key={profile_key(record):record for record in records}
    keys=[]
    assert len(index['repeat_chunks'])==21 and len(index['repeat_diagnostics'])==12
    for chunk in index['repeat_chunks']:
        validate_repeat(by_key[chunk['key']],read_original(directory,chunk['receipt']))
        keys.append(chunk['key'])
    for chunk in index['repeat_diagnostics']:
        diagnostic=read_chunk(directory,chunk['receipt'])
        assert diagnostic['format']=='ken-transformer-uninstrumented-repeat/1'
        assert diagnostic['scope']=='vector-repeat-only' and diagnostic['model_inference_accepted'] is False
        assert diagnostic['profile_key']==chunk['key'] and diagnostic['capture']['feeds']==[]
        def values(rows):
            return [{k:v for k,v in row.items() if k not in {'elapsed_s','feed_range'}} for row in rows]
        assert values(diagnostic['capture']['results'])==values(by_key[chunk['key']]['capture']['results'])
        keys.append(chunk['key'])
    assert len(set(keys))==len(keys)==len(by_key) and set(keys)==set(by_key)
