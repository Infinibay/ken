"""Capture original profile identities only; this never loads a model runtime."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys


def capture_profile_identities(reference_root: Path) -> dict:
    source = reference_root / 'src/ken/retrieval/profile.py'
    original_bytes = source.read_bytes()
    name = '_ken_frozen_profile_reference'
    specification = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(specification)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
        runtime = {'format': 'ken-legacy-runtime/1',
                   'backends': {backend: module._backend_runtime(backend) for backend in
                                ('static', 'model2vec', 'sentence-transformers', 'mlx', 'provided')},
                   'evidence': [(p, module._package_version(p)) for p in ('numpy', 'snowballstemmer')],
                   'contextual': [(p, module._package_version(p)) for p in ('numpy', 'tokenizers', 'onnxruntime')]}
        inputs = [
            ('static', {'model_id': 'ken/static-qwen3-r512-v2', 'revision': '1' * 64}),
            ('potion', {'model_id': 'minishlab/potion-code-16M-v2', 'revision': '2' * 64,
                        'backend': 'model2vec', 'dtype': 'float16', 'batch_size': 1024}),
            ('torch', {'model_id': 'Qwen/Qwen3-Embedding-0.6B', 'revision': '3' * 40,
                       'backend': 'sentence-transformers', 'dtype': 'bfloat16', 'sequence_length': 384}),
            ('mlx', {'model_id': 'Qwen/Qwen3-Embedding-0.6B', 'revision': '3' * 40,
                     'backend': 'mlx', 'dtype': 'float16', 'batch_size': 8}),
            ('provided', {'model_id': 'injected/encoder', 'revision': '4' * 40, 'backend': 'provided'}),
            ('unicode', {'model_id': 'modelos/niño 🚀\t"\\', 'revision': 'a' * 40, 'backend': 'provided'}),
        ]
        encoders = []
        for label, value in inputs:
            encoder = module.EncoderSpec(**value)
            encoders.append({'label': label, 'input': value, 'config': asdict(encoder),
                             'key': encoder.key, 'tokenizer_revision': encoder.tokenizer_revision})
        by_label = {row['label']: row['input'] for row in encoders}
        profiles = [(label, {'identity': value, 'behavior': value}) for label, value in inputs]
        base = {'identity': by_label['static'], 'behavior': by_label['potion']}
        joint = {'model': by_label['torch'], 'candidate_limit': 80, 'rank_unit': 'entity',
                 'evidence_results': 0, 'max_windows': 4, 'max_fragments': 4}
        profiles.append(('joint', base | {'joint': joint, 'passage_tokenizer': 'behavior-model'}))
        for version in (1, 2, 3):
            evidence = {'model_revision': 'c' * 64, 'word_model': by_label['potion'],
                        'feature_version': version, 'evidence_version': version}
            if version >= 2:
                evidence['expansion_revision'] = 'd' * 64
            options = base | {'evidence': evidence}
            if version >= 2:
                options['contextual'] = {'model': by_label['torch'], 'channel_limit': 100,
                                         'broad_limit': 400}
                if version == 3:
                    options['contextual']['view_model'] = by_label['mlx']
            profiles.append((f'evidence-v{version}', options))

        def observe_profile(label, options, *, upgrade=False):
            profile = module.RetrievalProfile.from_dict(options, upgrade_representation=upgrade)
            return {'label': label, 'input': options, 'config': profile.to_dict(),
                    'serialized_python': json.dumps(profile.to_dict(), sort_keys=True),
                    'fingerprint': profile.fingerprint,
                    'vector_revisions': {view: profile.vector_revision(view) for view in ('identity', 'behavior')}}

        def observe_error(options, create):
            try:
                create(options)
            except (ValueError, TypeError) as error:
                return {'input': options, 'error': {'type': type(error).__name__, 'message': str(error)}}
            raise AssertionError('original unexpectedly accepted negative fixture')

        invalid_encoders = [observe_error(by_label['static'] | change, lambda value: module.EncoderSpec(**value))
            for change in ({'revision': 'main'}, {'revision': 'A' * 40}, {'backend': 'unknown'},
                           {'dtype': 'int8'}, {'sequence_length': 0}, {'batch_size': 0})]
        invalid_inputs = [base | change for change in (
            {'max_tokens': 0}, {'candidate_limit': 0}, {'rrf_k': 0}, {'passage_tokenizer': 'unknown'},
            {'representation_version': 2}, {'joint': joint, 'evidence': profiles[-3][1]['evidence']},
            {'contextual': {'model': by_label['torch']}},
            {'evidence': profiles[-2][1]['evidence']},
            {'evidence': profiles[-1][1]['evidence'], 'contextual': {'model': by_label['torch']}},
            {'joint': joint | {'max_fragments': 5}}, {'joint': joint | {'rank_unit': 'file'}},
            {'evidence': profiles[-3][1]['evidence'] | {'stemming': 'other'}},
            {'evidence': profiles[-3][1]['evidence'] | {'model_revision': 'main'}},
            {'evidence': profiles[-3][1]['evidence'] | {'evidence_version': 4}},
        )]
        captured = {'format': 'ken-profile-original/1',
                    'platform': 'macos' if platform.system() == 'Darwin' else 'linux',
                    'original_source': {'path': 'src/ken/retrieval/profile.py', 'bytes': len(original_bytes),
                                        'sha256': hashlib.sha256(original_bytes).hexdigest()},
                    'capture_tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'legacy_runtime': runtime, 'encoders': encoders,
                    'profiles': [observe_profile(label, value) for label, value in profiles],
                    'invalid_encoders': invalid_encoders,
                    'invalid_profiles': [observe_error(value, module.RetrievalProfile.from_dict) for value in invalid_inputs],
                    'representation_upgrade': observe_profile('representation2-upgraded',
                        base | {'representation_version': 2}, upgrade=True),
                    'native_inference_accepted': False}
        if source.read_bytes() != original_bytes:
            raise ValueError('original profile source changed during capture')
        return captured
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    record = capture_profile_identities(args.reference.resolve())
    with args.out.open('x') as stream:
        json.dump(record, stream, indent=2, ensure_ascii=True)
        stream.write('\n')
    print(json.dumps({'captured': True, 'encoders': len(record['encoders']), 'profiles': len(record['profiles']),
                      'native_inference_accepted': False}))


if __name__ == '__main__':
    main()
