"""Run the frozen original judge, recording actual feeds and raw scores.

This module is migration tooling only. Each invocation uses one isolated oracle
process and one model/dtype/device; it is never called by the native product.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import resource
import time
import weakref


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--backend', choices=['torch', 'mlx'], required=True)
    parser.add_argument('--device', choices=['cpu', 'mps', 'mlx'], required=True)
    parser.add_argument('--dtype', choices=['float32', 'float16', 'bfloat16'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    import huggingface_hub
    from ken.retrieval.joint_model import LocalRelevanceJudge
    from ken.retrieval.profile import EncoderSpec
    import ken.retrieval.joint_model as original

    source = args.reference.resolve() / 'src/ken/retrieval/joint_model.py'
    assert Path(original.__file__).resolve() == source
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    snapshot = args.snapshot.resolve()
    registration = json.loads((snapshot / 'VERIFIED-DATA.json').read_text())
    assert registration['model_id'] == 'Qwen/Qwen3-Reranker-0.6B'
    assert registration['revision'] == 'e61197ed45024b0ed8a2d74b80b4d909f1255473'

    def local_snapshot(model, **options):
        assert model == registration['model_id']
        assert options == {'revision': registration['revision'], 'local_files_only': True, 'token': False}
        return str(snapshot)

    huggingface_hub.snapshot_download = local_snapshot
    if args.backend == 'torch':
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        os.environ['KEN_EMBED_DEVICE'] = args.device
    else:
        assert args.device == 'mlx' and platform.system() == 'Darwin'

    settings = {'model_id': registration['model_id'], 'revision': registration['revision'],
                'backend': args.backend, 'dtype': args.dtype, 'device_request': args.device,
                'sequence_length': 512, 'batch_size': 16}
    spec = EncoderSpec(registration['model_id'], registration['revision'],
                       backend='mlx' if args.backend == 'mlx' else 'sentence-transformers',
                       dtype=args.dtype, sequence_length=512, batch_size=16)
    judge = LocalRelevanceJudge(spec)
    assert judge._model is None
    preparation_start = time.monotonic()
    # An empty public call must perform original loading, even though it feeds
    # no model batches. Capture this before accessing the private tokenizer.
    try:
        judge.score('', [], purpose='implementation')
    except IndexError as failure:
        assert str(failure) == 'list index out of range'
        initial_empty_error = {'exception': type(failure).__name__, 'message': str(failure)}
    else:
        raise AssertionError('pinned original unexpectedly accepted empty documents')
    preparation_s = time.monotonic() - preparation_start
    assert judge._model is not None
    assert judge.device == args.device
    tokenizer = judge._tokenizer
    projection_ids = [tokenizer.convert_tokens_to_ids(token) for token in ('yes', 'no')]
    prefix = tokenizer.encode(original.PREFIX, add_special_tokens=False)
    suffix = tokenizer.encode(original.SUFFIX, add_special_tokens=False)
    requests = [{'id': 'empty', 'query': '', 'documents': [], 'purpose': 'implementation'}]
    requests += [{'id': 'purpose_' + purpose, 'query': 'where is configuration saved?',
                  'documents': ['def save_config(value): persist(value)'], 'purpose': purpose}
                 for purpose in [*original.INSTRUCTIONS, 'unknown']]
    for count in (128, 129):
        query = 'a ' * (count - 1) + 'a'
        assert len(tokenizer.encode(query, add_special_tokens=False)) == count
        requests.append({'id': f'query{count}', 'query': query, 'documents': ['source'], 'purpose': 'tests'})
    requests += [{'id': f'budget{count}', 'query': 'query', 'documents': ['a ' * 20],
                  'purpose': 'tests', 'remaining_override': count} for count in (15, 16)]
    requests += [{'id': f'batch{count}', 'query': 'query', 'documents': [''] * count,
                  'purpose': 'implementation'} for count in (16, 17)]
    requests += [{'id': 'long_source', 'query': 'query', 'documents': ['source ' * 600], 'purpose': 'usage'},
                 {'id': 'empty_budget15', 'query': 'query', 'documents': [], 'purpose': 'tests', 'remaining_override': 15}]
    # Budget ValueError triggers the original permanent CPU/F32 retry on MPS.
    # Put those cases last so every valid numerical case still observes the
    # requested accelerator. Retain and capture the ensuing state transition.
    requests.sort(key=lambda request: request.get('remaining_override') == 15)
    feeds, results = [], []
    current = {}
    model = judge._model
    if args.backend == 'torch':
        actual = model.model
        forward = weakref.WeakMethod(actual.forward)
        signature = inspect.signature(actual.forward)

        def observed_forward(*positional, **kwargs):
            call = forward()
            assert call is not None
            feeds.append({'case': current['id'], 'actual_device': str(call.__self__.device),
                          'weight_dtype': str(call.__self__.dtype), 'shape': list(kwargs['input_ids'].shape),
                          'inputs': {key: value.detach().cpu().tolist() for key, value in kwargs.items()
                                     if key in {'input_ids', 'attention_mask'}}, 'projection_ids': projection_ids})
            return call(*positional, **kwargs)

        observed_forward.__signature__ = signature
        actual.forward = observed_forward
    else:
        import mlx.core as mx

        def observed_model(ids):
            # The original suffix ends in a nonpadding newline. The tokenizer's
            # real source lengths, retained below, determine every true length;
            # do not infer them from EOS/pad IDs that may occur in real text.
            first = current['rows_seen']
            lengths = current['real_lengths'][first:first + ids.shape[0]]
            feeds.append({'case': current['id'], 'actual_device': 'mlx-gpu', 'weight_dtype': args.dtype,
                          'shape': list(ids.shape), 'input_ids': np.asarray(ids).tolist(),
                          'real_lengths': lengths, 'original_indices': list(range(first, first + len(lengths))),
                          'projection_ids': projection_ids})
            current['rows_seen'] += len(lengths)
            return model(ids)

        judge._model = observed_model
    original_run = weakref.WeakMethod(judge._run)

    def observed_run(query, documents, purpose):
        call = original_run()
        assert call is not None
        attempt = {'device': judge.device,
                   'dtype': args.dtype if args.backend == 'mlx' else str(judge._model.dtype).removeprefix('torch.'),
                   'feed_range': [len(feeds), len(feeds)]}
        try:
            values = call(query, documents, purpose)
        except (ValueError, IndexError, RuntimeError) as failure:
            attempt.update(outcome='exception', exception=type(failure).__name__, message=str(failure))
            raise
        else:
            attempt.update(outcome='returned', finite=bool(np.isfinite(values).all()))
            return values
        finally:
            attempt['feed_range'][1] = len(feeds)
            current['attempts'].append(attempt)

    judge._run = observed_run
    for request in requests:
        raw_query = tokenizer.encode(request['query'], add_special_tokens=False)
        query_ids = raw_query[:128]
        instruction = original.INSTRUCTIONS.get(request['purpose'], original.INSTRUCTIONS['implementation'])
        header = tokenizer.encode('<Instruct>: ' + instruction + '\n<Query>: ', add_special_tokens=False)
        header += query_ids + tokenizer.encode('\n<Document>: ', add_special_tokens=False)
        overhead = len(prefix) + len(header) + len(suffix)
        limit = overhead + request['remaining_override'] if 'remaining_override' in request else 512
        request.update(sequence_length=limit, remaining=limit - overhead,
                       query_token_count=len(raw_query), query_ids=query_ids,
                       budget_parts={'prefix': len(prefix), 'header': len(header), 'suffix': len(suffix)})
        if request['remaining'] < 16:
            request['expected_error'] = 'ValueError'
        elif not request['documents']:
            request['expected_error'] = 'IndexError'
        judge.spec = replace(spec, sequence_length=limit)
        current.clear()
        current.update(id=request['id'], rows_seen=0, attempts=[])
        if args.backend == 'mlx' and request['remaining'] >= 16 and request['documents']:
            encoded = tokenizer(request['documents'], add_special_tokens=False, truncation=True,
                                max_length=request['remaining'])['input_ids']
            current['real_lengths'] = [overhead + len(row) for row in encoded]
        first = len(feeds)
        start = time.monotonic()
        try:
            values = judge.score(request['query'], request['documents'], purpose=request['purpose'])
            result = {'id': request['id'], 'passed_original_call': True, 'shape': list(values.shape),
                      'finite': bool(np.isfinite(values).all()),
                      'scores_f32le_hex': values.astype('<f4', copy=False).tobytes().hex()}
            assert 'expected_error' not in request and result['finite']
        except (ValueError, IndexError) as failure:
            if request.get('expected_error') != type(failure).__name__:
                raise
            result = {'id': request['id'], 'passed_original_call': False,
                      'exception': type(failure).__name__, 'message': str(failure)}
        result.update(feed_range=[first, len(feeds)], device_after=judge.device,
                      attempts=current['attempts'], elapsed_s=time.monotonic() - start)
        results.append(result)
        print(json.dumps({'case': request['id'], 'original_success': result['passed_original_call'],
                          'elapsed_s': result['elapsed_s']}), flush=True)
    packages = (['mlx', 'mlx-lm'] if args.backend == 'mlx' else ['torch', 'sentence-transformers'])
    packages += ['transformers', 'numpy', 'tokenizers']
    capture = {'settings': settings, 'model_registration': registration, 'original_source_sha256': source_sha,
               'dimension': 1, 'loaded_before_cases': True, 'initial_empty_call_loaded': True,
               'initial_empty_error': initial_empty_error,
               'requests': requests, 'results': results, 'feeds': feeds, 'preparation_s': preparation_s,
               'package_versions': {name: importlib.metadata.version(name) for name in packages},
               'peak_rss_process_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if platform.system() == 'Linux' else 1),
               'fixed_before_native': {'score_f32_abs_tolerance': 1e-5}, 'model_inference_accepted': False}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    record = {'format': 'ken-transformer-original/1', 'platform': 'macos' if platform.system() == 'Darwin' else 'linux',
              'adapter': 'judge', 'capture': capture}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, ensure_ascii=True, allow_nan=False) + '\n')
    print(json.dumps({'captured': True, 'cases': len(results), 'feeds': len(feeds), 'model_inference_accepted': False}), flush=True)


if __name__ == '__main__':
    main()
