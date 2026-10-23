"""Authenticate original transformer observations, without native acceptance.

These checks establish complete, consistent reference inputs. They do not prove
that a claimed observation was produced by executing the original; platform
receipts additionally retain the capture command, tool/source hashes and logs.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct

from .fastembed_reference import read_chunk, write_chunk

CATALOG = Path(__file__).resolve().parents[2] / 'crates/ken-models/resources/transformer-catalog.json'
DTYPES = {'float32', 'float16', 'bfloat16'}
ENCODER_CASES = ('lexical', 'specials', 'repeated', 'batch16', 'batch17', 'ties17', 'ties33',
                 'content_tokens_511', 'content_tokens_512', 'content_tokens_513',
                 'unicode_truncation', 'query_prompt')
JUDGE_CASES = ('empty', 'purpose_implementation', 'purpose_tests', 'purpose_usage',
               'purpose_documentation', 'purpose_identity', 'purpose_unknown', 'query128', 'query129',
               'budget16', 'batch16', 'batch17', 'long_source', 'budget15', 'empty_budget15')


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def profile_key(record: dict) -> str:
    settings = record['capture']['settings']
    device = 'mlx' if record['adapter'] == 'mlx' else settings['device_request']
    return '|'.join((record['platform'], record['adapter'], settings['model_id'], device, settings['dtype']))


def freeze_profile_budget(record: dict) -> dict:
    """Freeze a production profile's deadline using original observations only.

    Three times original initialization plus public calls, with a 60s floor,
    reserves deterministic protocol/verification overhead without consulting a
    candidate's speed. Acquisition is a separate phase; the legacy 600s gate
    and already fixed numerical tolerances are unaffected.
    """
    validate_original(record)
    capture = record['capture']
    times = [capture.get('preparation_s'), *(row.get('elapsed_s') for row in capture['results'])]
    _require(all(type(value) in (int, float) and math.isfinite(value) and value >= 0
                 for value in times), 'missing or invalid original timing')
    total = sum(times)
    _require(math.isfinite(total * 3), 'original timing overflow')
    return {'original_total_seconds': total,
            'execution_deadline_seconds': max(60, math.ceil(3 * total)),
            'acquisition_outside_deadline': True,
            'vector_max_absolute_error': 1e-6, 'raw_score_max_absolute_error': 1e-5}


def _validate_identity(record: dict, catalog: dict) -> tuple[dict, dict]:
    _require(record['format'] == 'ken-transformer-original/1', 'invalid original format')
    adapter, platform = record['adapter'], record['platform']
    _require(adapter in {'sentence', 'mlx', 'judge'} and platform in {'macos', 'linux'}, 'unsupported original profile')
    capture = record['capture']
    settings = capture['settings']
    mlx = adapter == 'mlx' or (adapter == 'judge' and settings['backend'] == 'mlx')
    _require(not mlx or platform == 'macos', 'MLX original requires macOS')
    if adapter == 'judge':
        _require(settings['backend'] in {'torch', 'mlx'}, 'invalid original judge backend')
    _require(settings['dtype'] in DTYPES, 'invalid original dtype')
    _require(_positive(settings['sequence_length']) and _positive(settings['batch_size']), 'invalid original limits')
    model = next((m for m in catalog['models'] if m['name'] == settings['model_id']), None)
    _require(model is not None and model['role'] == ('judge' if adapter == 'judge' else 'encoder'), 'unknown original model')
    assert model is not None
    _require(not mlx or model['architecture'] == 'qwen3', 'MLX original requires Qwen3')
    _require(settings['revision'] == model['assets']['revision'], 'wrong original revision')
    _require(capture['original_source_sha256'] == catalog['original_sources'][adapter]['sha256'], 'wrong original source')
    registration = capture['model_registration']
    _require(registration['model_id'] == settings['model_id'] and registration['revision'] == settings['revision'],
             'wrong original asset identity')
    artifacts = {}
    for row in registration['files']:
        _require(row['path'] not in artifacts, 'duplicate original artifact')
        artifacts[row['path']] = {'bytes': row['bytes'], 'sha256': row['sha256']}
    _require(artifacts == model['assets']['artifacts'], 'wrong original artifact declarations')
    expected = {'numpy': '2.4.4', 'transformers': '4.57.6', 'tokenizers': '0.22.2'}
    if not mlx:
        expected.update(torch='2.9.0+cpu' if platform == 'linux' else '2.9.0', **{'sentence-transformers': '5.6.1'})
    else:
        expected.update(mlx='0.32.3', **{'mlx-lm': '0.28.4'})
    _require(capture['package_versions'] == expected, 'wrong original package versions')
    _require(capture['model_inference_accepted'] is False, 'original record cannot accept native inference')
    if adapter == 'judge':
        _require(capture['loaded_before_cases'] is True, 'judge original load observation missing')
    else:
        _require(capture['empty_batch_did_not_load'] is True and capture['count_did_not_load_model'] is True,
                 'original lazy-state observation missing')
        _require(type(capture['long_count']) is int and capture['long_count'] > 512, 'original count was truncated')
    device = 'mlx-gpu' if mlx else settings['device_request']
    _require(device in {'cpu', 'mps', 'mlx-gpu'} and (platform != 'linux' or device == 'cpu'), 'wrong original device')
    return model, settings


def _validate_feed(feed: dict, case: str, adapter: str, settings: dict) -> int:
    _require(feed['case'] == case, 'original feed bound to wrong case')
    device = 'mlx-gpu' if adapter == 'mlx' else settings['device_request']
    dtype = settings['dtype'] if adapter == 'mlx' else 'torch.' + settings['dtype']
    _require(feed['actual_device'].split(':')[0] == device and feed['weight_dtype'] == dtype, 'wrong original feed device/dtype')
    shape = feed['shape']
    _require(isinstance(shape, list) and len(shape) == 2 and all(_positive(v) for v in shape), 'invalid original feed shape')
    rows, columns = shape
    _require(rows <= settings['batch_size'] and columns <= settings['sequence_length'], 'original feed exceeds limits')
    inputs = feed if adapter == 'mlx' else feed['inputs']
    ids = inputs['input_ids']
    _require(len(ids) == rows and all(len(row) == columns for row in ids), 'original token shape mismatch')
    _require(all(type(value) is int and value >= 0 for row in ids for value in row), 'invalid original token')
    if adapter == 'sentence':
        mask = inputs['attention_mask']
        _require(len(mask) == rows and all(len(row) == columns for row in mask), 'original mask shape mismatch')
        _require(all(type(value) is int and value in {0, 1} for row in mask for value in row), 'invalid original mask')
        _require(all(sum(row) > 0 for row in mask), 'empty original attention row')
    else:
        lengths = feed['real_lengths']
        _require(len(lengths) == rows and all(_positive(n) and n <= columns for n in lengths), 'invalid original real lengths')
        indices = feed['original_indices']
        _require(len(indices) == rows and all(type(n) is int and n >= 0 for n in indices), 'invalid original restoration indices')
    return rows


def _validate_original(record: dict) -> None:
    model, settings = _validate_identity(record, json.loads(CATALOG.read_text()))
    capture, adapter = record['capture'], record['adapter']
    if adapter == 'judge':
        _validate_judge(capture, settings)
        return
    dimension = capture.get('dimension', model['dimension'])
    _require(dimension == model['dimension'], 'wrong original dimension')
    requests, results, feeds = capture['requests'], capture['results'], capture['feeds']
    _require(len(requests) == len(results) > 0, 'missing original cases')
    _require(len({r['id'] for r in requests}) == len(requests), 'duplicate original case')
    cursor = 0
    for request, result in zip(requests, results, strict=True):
        _require(request['id'] == result['id'], 'wrong original result case')
        _require(result['passed_original_call'] is True and 'error' not in result, 'original error is not an output')
        _require(result['finite'] is True, 'original vectors not finite')
        texts = request['texts']
        _require(isinstance(texts, list) and all(isinstance(t, str) for t in texts), 'invalid original texts')
        _require(request['side'] in {'passages', 'query'} and (request['side'] != 'query' or len(texts) == 1), 'invalid original side')
        shape = result['shape']
        _require(shape == [len(texts), dimension], 'original output shape mismatch')
        payload = bytes.fromhex(result['vectors_f32le_hex'])
        _require(len(payload) == len(texts) * dimension * 4, 'original vector byte count mismatch')
        _require(all(math.isfinite(value[0]) for value in struct.iter_unpack('<f', payload)), 'original vectors not finite')
        first, last = result['feed_range']
        _require(type(first) is int and type(last) is int and first == cursor and first <= last <= len(feeds), 'invalid original feed range')
        _require(not texts or first < last, 'successful original without actual feed')
        count = sum(_validate_feed(feed, request['id'], adapter, settings) for feed in feeds[first:last])
        _require(count == len(texts), 'original feed row count mismatch')
        cursor = last
        _require(result['device_after'] == ('mlx' if adapter == 'mlx' else settings['device_request']), 'wrong original result device')
        counts = capture['counts'][request['id']]
        _require(len(counts) == len(texts) and all(type(n) is int and n >= 0 for n in counts), 'invalid original token counts')
    _require(cursor == len(feeds), 'unclaimed original feeds')


def _validate_judge(capture: dict, settings: dict) -> None:
    _require(capture['dimension'] == 1, 'wrong judge output dimension')
    requests, results, feeds = capture['requests'], capture['results'], capture['feeds']
    _require(len(requests) == len(results) > 0, 'missing original judge cases')
    _require(len({r['id'] for r in requests}) == len(requests), 'duplicate original judge case')
    cursor = 0
    mlx = settings['backend'] == 'mlx'
    device = 'mlx' if mlx else settings['device_request']
    dtype = settings['dtype']
    for request, result in zip(requests, results, strict=True):
        _require(request['id'] == result['id'], 'wrong original judge result case')
        query_count, query_ids = request['query_token_count'], request['query_ids']
        _require(type(query_count) is int and query_count >= 0 and len(query_ids) == min(query_count, 128)
                 and all(type(n) is int and n >= 0 for n in query_ids), 'wrong original query bound')
        _require(_positive(request['sequence_length']) and type(request['remaining']) is int, 'invalid original judge budget')
        first, last = result['feed_range']
        _require(type(first) is int and type(last) is int and first == cursor and first <= last <= len(feeds), 'invalid original judge feed range')
        attempts = result.get('attempts')
        if attempts is None:
            _require(result['device_after'] == device, 'untraced original judge device transition')
            attempts = [{'device': device, 'dtype': dtype, 'feed_range': result['feed_range'],
                         'outcome': 'returned' if result['passed_original_call'] else 'exception',
                         'finite': result.get('finite'), 'exception': result.get('exception'),
                         'message': result.get('message')}]
        _require(isinstance(attempts, list) and 1 <= len(attempts) <= 2, 'invalid original judge retry count')
        attempt_cursor = first
        final_rows = 0
        for index, attempt in enumerate(attempts):
            if index:
                prior = attempts[index - 1]
                retryable = ((prior['outcome'] == 'exception' and prior['exception'] in {'RuntimeError', 'ValueError'})
                             or (prior['outcome'] == 'returned' and prior['finite'] is False))
                _require(device not in {'cpu', 'mlx'} and retryable, 'invalid original judge retry cause')
                device, dtype = 'cpu', 'float32'
            _require(attempt['device'] == device and attempt['dtype'] == dtype, 'wrong original attempt device/dtype')
            begin, end = attempt['feed_range']
            _require(type(begin) is int and type(end) is int and begin == attempt_cursor
                     and begin <= end <= last, 'invalid original attempt feed range')
            feed_settings = dict(settings, sequence_length=request['sequence_length'], device_request=device, dtype=dtype)
            final_rows = sum(_validate_feed(feed, request['id'], 'mlx' if mlx else 'sentence', feed_settings)
                             for feed in feeds[begin:end])
            attempt_cursor = end
        _require(attempt_cursor == last and result['device_after'] == device, 'wrong original judge final device/feeds')
        final_attempt = attempts[-1]
        if request['remaining'] < 16:
            _require(request.get('expected_error') == 'ValueError' and result['passed_original_call'] is False
                     and result['exception'] == 'ValueError'
                     and result['message'] == 'joint model sequence budget cannot contain query and source'
                     and first == last and 'scores_f32le_hex' not in result and 'shape' not in result,
                     'original budget error cannot contain fabricated output')
            _require(final_attempt['outcome'] == 'exception' and final_attempt['exception'] == 'ValueError'
                     and final_attempt['message'] == result['message'], 'original budget attempt error mismatch')
            continue
        if request['documents'] == []:
            _require(request.get('expected_error') == 'IndexError' and result['passed_original_call'] is False
                     and result['exception'] == 'IndexError' and result['message'] == 'list index out of range'
                     and first == last and 'scores_f32le_hex' not in result and 'shape' not in result,
                     'original empty tokenizer error cannot contain fabricated output')
            _require(final_attempt['outcome'] == 'exception' and final_attempt['exception'] == 'IndexError'
                     and final_attempt['message'] == result['message'], 'original empty attempt error mismatch')
            continue
        _require('expected_error' not in request and result['passed_original_call'] is True
                 and 'exception' not in result and 'error' not in result, 'original judge error is not an output')
        documents = request['documents']
        _require(isinstance(documents, list) and all(isinstance(t, str) for t in documents), 'invalid original judge documents')
        _require(result['shape'] == [len(documents)], 'wrong original judge score shape')
        raw = bytes.fromhex(result['scores_f32le_hex'])
        _require(len(raw) == 4 * len(documents), 'wrong original judge score byte count')
        _require(result['finite'] is True and all(math.isfinite(n[0]) for n in struct.iter_unpack('<f', raw)), 'original scores not finite')
        _require(final_attempt['outcome'] == 'returned' and final_attempt['finite'] is True, 'original returned attempt mismatch')
        _require(not documents or first < last, 'successful original judge without actual feed')
        _require(final_rows == len(documents), 'wrong original judge feed rows')
        for feed in feeds[first:last]:
            ids = feed['projection_ids']
            _require(len(ids) == 2 and len(set(ids)) == 2 and all(type(n) is int and n >= 0 for n in ids), 'invalid original yes/no projection')
        cursor = last
    _require(cursor == len(feeds), 'unclaimed original judge feeds')


def validate_original(record: dict) -> None:
    try:
        _validate_original(record)
    except (KeyError, TypeError, IndexError, OverflowError, struct.error) as error:
        raise ValueError('malformed original record') from error


def write_original(directory: Path, name: str, record: dict) -> dict:
    validate_original(record)
    _require(Path(name).name == name and name not in {'', '.', '..'}, 'invalid original chunk name')
    return write_chunk(directory, name, record)


def read_original(directory: Path, receipt: dict) -> dict:
    record = read_chunk(directory, receipt)
    validate_original(record)
    return record


def validate_repeat(first: dict, second: dict) -> None:
    """Require the same actual inputs, outputs, states and identities twice."""
    validate_original(first)
    validate_original(second)
    _require(profile_key(first) == profile_key(second), 'original repeat profile differs')

    def stable(capture: dict) -> dict:
        value = {key: item for key, item in capture.items()
                 if key not in {'preparation_s', 'peak_rss_process_bytes'}}
        value['results'] = [{key: item for key, item in row.items() if key != 'elapsed_s'}
                            for row in capture['results']]
        return value

    _require(stable(first['capture']) == stable(second['capture']),
             'original repeat inputs, values or state differ')


def required_inventory() -> dict:
    profiles = []
    for model in json.loads(CATALOG.read_text())['models']:
        variants = [('macos', 'sentence', 'cpu'), ('macos', 'sentence', 'mps'), ('linux', 'sentence', 'cpu')]
        cases = ENCODER_CASES
        if model['role'] == 'judge':
            variants = [('macos', 'judge', 'cpu'), ('macos', 'judge', 'mps'),
                        ('macos', 'judge', 'mlx'), ('linux', 'judge', 'cpu')]
            cases = JUDGE_CASES
        elif model['architecture'] == 'qwen3':
            variants.append(('macos', 'mlx', 'mlx'))
        for system, adapter, device in variants:
            for dtype in sorted(DTYPES):
                profiles.append({'key': '|'.join((system, adapter, model['name'], device, dtype)),
                                 'cases': list(cases)})
    return {'format': 'ken-transformer-original-inventory/1',
            'profiles': sorted(profiles, key=lambda row: row['key'])}


def validate_inventory(records: list[dict], inventory: dict) -> None:
    fixed = required_inventory()
    _require(inventory.get('format') == fixed['format'], 'invalid original profile inventory format')
    expected = {row['key']: row['cases'] for row in fixed['profiles']}
    declared = {}
    for row in inventory['profiles']:
        _require(row['key'] not in declared, 'duplicate inventory profile')
        declared[row['key']] = row['cases']
    _require(declared.keys() == expected.keys(), 'incomplete original profile inventory')
    _require(declared == expected, 'incomplete original case inventory')
    observed = {}
    for record in records:
        validate_original(record)
        key = profile_key(record)
        _require(key not in observed, 'duplicate original profile')
        observed[key] = [r['id'] for r in record['capture']['requests']]
    _require(observed.keys() == expected.keys(), 'missing or unexpected original profile')
    _require(observed == expected, 'missing or unexpected original case')
