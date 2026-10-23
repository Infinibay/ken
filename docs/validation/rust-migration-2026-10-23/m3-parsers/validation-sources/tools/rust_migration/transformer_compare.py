"""Replay public adapter observations against authenticated original calls."""
from __future__ import annotations

import json, hashlib
import numpy as np
from .transformer_reference import CATALOG, validate_original, freeze_profile_budget, profile_key


def request_policy(original: dict) -> dict:
    """Only original public inputs and settings, never captured outputs."""
    validate_original(original)
    capture, adapter = original['capture'], original['adapter']
    settings = capture['settings']
    if adapter == 'judge':
        cases = [{k: r[k] for k in ('id', 'query', 'documents', 'purpose', 'sequence_length')}
                 for r in capture['requests']]
    else:
        cases = [{'id': r['id'], 'texts': r['texts'],
                  'side': 'query' if r['side'] == 'query' else 'passage'}
                 for r in capture['requests']]
    result = {'dtype': settings['dtype'], 'batch_size': settings['batch_size'],
              'sequence_length': settings['sequence_length'], 'cases': cases}
    if adapter != 'mlx':
        result['device'] = {'kind': 'mps' if settings['device_request'] == 'mlx' else settings['device_request']}
    return result


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def compare_transformer(original: dict, actual: dict) -> dict:
    report = {'passed': False, 'errors': [], 'scores': 0, 'vectors': 0,
              'feeds': 0, 'maximum_absolute_error': 0.0}
    try:
        validate_original(original)
        capture = original['capture']
        adapter, settings = original['adapter'], capture['settings']
        definition = next(m for m in json.loads(CATALOG.read_text())['models'] if m['name'] == settings['model_id'])
        fingerprint = hashlib.sha256(json.dumps(definition['assets'], sort_keys=True).encode()).hexdigest()
        judge = adapter == 'judge'
        mlx = adapter == 'mlx' or (judge and settings['backend'] == 'mlx')
        expected_format = {'judge': 'ken-relevance-probe/1',
                           'sentence': 'ken-sentence-probe/1', 'mlx': 'ken-mlx-probe/1'}[adapter]
        _require(actual['format'] == expected_format, 'wrong public adapter format')
        _require(actual['initial_preparation'] is None, 'original lazy construction differs')
        if not judge:
            _require(actual['after_empty_preparation'] is None and actual['empty_vectors'] == [],
                     'empty encoder must not load')
            _require(actual['dimension'] == capture.get('dimension', definition['dimension']), 'wrong encoder dimension')
        _require(len(actual['rows']) == len(capture['requests']), 'missing or extra public cases')
        limit = freeze_profile_budget(original)['raw_score_max_absolute_error' if judge
                                                else 'vector_max_absolute_error']
        for request, expected, row in zip(capture['requests'], capture['results'], actual['rows'], strict=True):
            name = request['id']
            _require(row['id'] == expected['id'] == name, 'wrong case order')
            trace = row['preparation']
            _require(trace['model_fingerprint'] == fingerprint, f'{name}: wrong actual model asset fingerprint')
            device = 'mps' if expected['device_after'] == 'mlx' else expected['device_after']
            dtype = expected['attempts'][-1]['dtype'] if judge else settings['dtype']
            _require(trace['device'] == {'kind': device} and trace['dtype'] == dtype,
                     f'{name}: wrong actual device/dtype transition')
            _require(trace['runtime']['backend'] == ('mlx' if mlx else 'torch') and
                     trace['core_version'] == ('0.32.3' if mlx else '2.9.0'),
                     f'{name}: wrong executing core')
            if judge:
                _require(row['passed_original_call'] == expected['passed_original_call'],
                         f'{name}: changed success/error behavior')
                if not expected['passed_original_call']:
                    _require(row['exception'] == expected['exception'] and row['message'] == expected['message'],
                             f'{name}: wrong original error')
                    continue
            feeds = capture['feeds'][slice(*expected['feed_range'])]
            expected_feeds = [f['inputs'] if not mlx else {
                'input_ids': f['input_ids'], 'attention_mask': [
                    [1] * n + [0] * (len(f['input_ids'][0]) - n) for n in f['real_lengths']]
            } for f in feeds]
            _require(row['feeds'] == expected_feeds, f'{name}: wrong token feeds/masks')
            if judge:
                _require(all(row['projection_ids'] == f['projection_ids'] for f in feeds),
                         f'{name}: wrong projection rows')
                _require(row['remaining'] == request['remaining'] and row['query_ids'] == request['query_ids'],
                         f'{name}: wrong query truncation/budget')
                field, payload = 'scores', 'scores_f32le_hex'
            else:
                _require(row['counts'] == capture['counts'][name], f'{name}: wrong raw token counts')
                order = ([i for feed in feeds for i in feed['original_indices']] if mlx else
                         np.argsort([-len(t) for t in request['texts']]).tolist())
                _require(row['order'] == order, f'{name}: wrong original sort order')
                field, payload = 'vectors', 'vectors_f32le_hex'
            gold = np.frombuffer(bytes.fromhex(expected[payload]), dtype='<f4').reshape(expected['shape'])
            values = np.asarray(row[field], dtype=np.float32)
            _require(values.shape == gold.shape and np.isfinite(values).all(), f'{name}: invalid output shape/finiteness')
            difference = float(np.abs(values - gold).max()) if values.size else 0.
            _require(difference <= limit, f'{name}: original numerical tolerance exceeded')
            report[field] += len(values)
            report['feeds'] += len(feeds)
            report['maximum_absolute_error'] = max(report['maximum_absolute_error'], difference)
        _require(actual['preparation'] == actual['rows'][-1]['preparation'], 'final state differs from last call')
        report['passed'] = True
    except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        report['errors'].append(str(error))
    return report


def compare_prepared_transformer(prepared, original: dict, source_root, output) -> dict:
    """Execute one complete public profile after its explicit preparation phase."""
    from pathlib import Path
    import hashlib, shutil, time
    from .preparation import PreparedNativeTransformer
    from .transformer_evidence import source_identity
    from .transformer_sources import source_lease, capacity_plan
    from .transformer_process import run_transformer
    if not isinstance(prepared, PreparedNativeTransformer):
        raise ValueError('typed PreparedNativeTransformer required')
    prepared.environment()
    validate_original(original)
    for path in (prepared.probe, prepared.registry, prepared.module, prepared.runtimes):
        if not path.is_file(): raise ValueError('missing explicit prepared transformer input: '+str(path))
    if not prepared.core.is_dir(): raise ValueError('missing explicit native transformer core')
    def artifact(path):
        with path.open('rb') as stream:
            return {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    expected_registry = source_root/'crates/ken-models/resources/transformer-catalog.json'
    if artifact(prepared.registry) != artifact(expected_registry):
        raise ValueError('stale/unregistered transformer catalogue')
    expected_runtimes = source_root/'tools/rust_migration/data/transformer-cores.json'
    if artifact(prepared.runtimes) != artifact(expected_runtimes):
        raise ValueError('stale/unregistered transformer native cores')
    settings = original['capture']['settings']
    backend = 'mlx' if original['adapter'] == 'mlx' else settings.get('backend', 'torch')
    core = next(r for r in json.loads(prepared.runtimes.read_text())['cores']
                if r['os'] == original['platform'] and r['backend'] == backend and r['arch'] == 'aarch64')
    definition = next(m for m in json.loads(prepared.registry.read_text())['models'] if m['name'] == settings['model_id'])
    module, host = artifact(prepared.module), artifact(prepared.probe)
    source = source_identity(source_root)
    runtime = {'format': 'ken-native-transformer/1', 'backend': backend, 'runtimes': [{
        'os': core['os'], 'arch': core['arch'], 'core_version': core['core_version'],
        'libraries': core['libraries'], 'module': module}]}
    started = time.monotonic()
    with source_lease(prepared, definition, core, module_bytes=module['bytes']) as leased:
        preparation_s = time.monotonic()-started
        request = request_policy(original) | {
            'model': definition, 'runtime': runtime,
            'snapshot': str(leased.sources/definition['assets']['model_id'].replace('/', '--')/definition['assets']['revision']),
            'private_parent': str(output/'unused-private'), 'module': str(prepared.module),
            'core_root': str(prepared.core)}
        observation = run_transformer(prepared.probe, request, output,
                    deadline_s=freeze_profile_budget(original)['execution_deadline_seconds'])
    if source != source_identity(source_root) or host != artifact(prepared.probe) or module != artifact(prepared.module):
        raise ValueError('transformer source or native binary changed during execution')
    comparison = compare_transformer(original, observation['actual'])
    shutil.copyfile(output/'stdout.json', output/'actual.json')
    row = {'key': profile_key(original), 'directory': output.name, 'source_files': source,
           'host_binary': host, 'native_module': module,
           'runtime': {k: core[k] for k in ('backend', 'core_version', 'libraries')},
           'execution': observation['receipt'], 'preparation': {'elapsed_s': preparation_s,
           'outside_execution_budget': True, 'capacity': capacity_plan(definition, core,
             module_bytes=module['bytes'], acquire=prepared.acquire)}, 'comparison': comparison}
    (output/'profile.json').write_text(json.dumps(row, indent=2, allow_nan=False)+'\n')
    return row
