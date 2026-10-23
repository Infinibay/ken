"""Accept both registered platforms only after raw semantic evidence replay."""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from .policy_evidence import _read, authenticate_manifest
from .transformer_evidence import profile_errors, source_identity, gate_errors
from .transformer_reference import read_original, profile_key

FORMAT = 'ken-transformer-acceptance/1'
EXECUTION_FORMAT = 'ken-transformer-execution/1'
REFERENCE = Path('docs/validation/rust-migration-2026-10-20/m2-transformer-reference')
TOOLING = ('transformer_process.py', 'transformer_compare.py', 'transformer_evidence.py',
           'transformer_validate.py', 'transformer_reference.py', 'preparation.py', 'model_validate.py',
           'transformer_sources.py', 'transformer_prepare.py', 'transformer_execution.py',
           'data/transformer-cores.json')
REQUIRED_GATES = ('transformer_unit', 'transformer_parity', 'transformer_ownership',
                  'native_torch', 'native_mlx', 'capacity')


def tooling_identity(source_root: Path) -> dict:
    paths = [source_root/'tools/rust_migration'/name for name in TOOLING]
    paths += [source_root/'transformer_migration_tests'/name for name in ('test_parity.py', 'test_ownership.py')]
    paths += [source_root/'.github/workflows/rust-models.yml', source_root/'.github/workflows/rust-transformers.yml',
              source_root/'.github/actions/prepare-native-transformers/action.yml',
              source_root/'.github/actions/prepare-native-validation/action.yml']
    return {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _replay_profiles(platform_receipt: Path, source_root: Path):
    row, files = {}, {}
    result = {'scope': 'transformer-profiles', 'passed': False, 'errors': [], 'M2_accepted': False}
    try:
        def require(condition, message):
            if not condition: raise ValueError(message)
        row = json.loads(_read(platform_receipt, 'summary.json'))
        require(row['format'] == FORMAT and row['scope'] == 'transformer-local' and
                row['passed'] is True and row['synthetic_fixture'] is False and
                row['M2_accepted'] is False, 'real complete platform evidence required')
        platform = row['platform']
        require(platform in ('macos', 'linux') and row['architecture'] == 'aarch64',
                'unregistered transformer platform')
        require(row['source_files'] == source_identity(source_root) and
                row['tooling'] == tooling_identity(source_root), 'stale current source/tooling')
        reference = source_root/REFERENCE
        index = json.loads((reference/'INDEX.json').read_bytes())
        originals = {entry['key']: read_original(reference, entry['receipt']) for entry in index['chunks']
                     if entry['key'].split('|')[0] == platform}
        require(len(originals) == (24 if platform == 'macos' else 9), 'incomplete trusted reference inventory')
        require(sorted(p['key'] for p in row['profiles']) == sorted(originals),
                'missing/duplicated/reordered profile coverage')
        files = authenticate_manifest(row['execution_artifacts'], lambda name: _read(platform_receipt, name),
                                      format=EXECUTION_FORMAT)
        registry = json.loads((source_root/'tools/rust_migration/data/transformer-cores.json').read_text())
        require(registry['format'] == 'ken-native-transformer-cores/1', 'registered native core closure required')
        for profile in row['profiles']:
            original = originals[profile['key']]
            require(profile_key(original) == profile['key'], 'reference key mismatch')
            backend = 'mlx' if original['adapter'] == 'mlx' else original['capture']['settings'].get('backend', 'torch')
            cores = [r for r in registry['cores'] if (r['os'], r['arch'], r['backend']) == (platform, 'aarch64', backend)]
            require(len(cores) == 1, 'one executing core registration required')
            core = {k: cores[0][k] for k in ('backend', 'core_version', 'libraries')}
            result['errors'].extend(profile_errors(files, profile, original, source_root, core))
        result.update(platform=platform, profiles=len(row['profiles']), source_files=row['source_files'],
                      tooling=row['tooling'], passed=not result['errors'])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        result['errors'].append('transformer profile evidence: '+str(error))
    return result, row, files


def replay_transformer_profiles(platform_receipt: Path, source_root: Path) -> dict:
    return _replay_profiles(platform_receipt, source_root)[0]


def validate_transformer(platform_receipt: Path, source_root: Path) -> dict:
    result, row, files = _replay_profiles(platform_receipt, source_root)
    result['scope'] = 'transformer-replay'
    if not result['passed']: return result
    result['passed'] = False
    try:
        def require(condition, message):
            if not condition: raise ValueError(message)
        platform = row['platform']
        require(set(row['gates']) == set(REQUIRED_GATES), 'all transformer gates required')
        for name, gate in row['gates'].items():
            if name == 'native_mlx' and platform == 'linux':
                require(gate == {'applicable': False, 'reason': 'Apple GPU only'},
                        'Linux MLX applicability must be explicit')
            else:
                require(gate['ran'] is True and gate['passed'] is True and gate['exit_code'] == 0,
                        'failed/missing transformer gate: '+name)
        result['errors'].extend(gate_errors(files, row, source_root))
        # The preceding34-gate chain is authenticated and re-evaluated against
        # current files. A summary whose booleans merely say "passed" is insufficient.
        from .fastembed_validate import fastembed_fingerprints, fastembed_receipt_errors
        from .fastembed_evidence import _proof_errors
        base = json.loads(files['base/summary.json'])
        expected = fastembed_fingerprints(source_root, None,
                    source_root/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz', None, None, None)
        result['errors'].extend(fastembed_receipt_errors(base, expected))
        result['errors'].extend(_proof_errors({k.removeprefix('base/'): v for k, v in files.items()
                                              if k.startswith('base/')}, base))
        require(base['platform'] == ('Darwin' if platform == 'macos' else 'Linux'), 'legacy platform differs')
        result.update(platform=platform, profiles=len(row['profiles']), source_files=row['source_files'],
                      tooling=row['tooling'], passed=not result['errors'])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        result['errors'].append('transformer platform evidence: '+str(error))
    return result


def aggregate_transformers(directory: Path, source_root: Path) -> dict:
    results = []
    for path in sorted(directory.rglob('summary.json')):
        try:
            if json.loads(path.read_bytes()).get('scope') == 'transformer-local':
                results.append(validate_transformer(path.parent, source_root))
        except (OSError, ValueError, AttributeError):
            results.append({'passed': False, 'errors': ['unreadable transformer summary']})
    errors = [error for r in results for error in r['errors']]
    if sorted(r.get('platform', '') for r in results) != ['linux', 'macos']:
        errors.append('exactly one accepted Linux and macOS platform required')
    passed = len(results) == 2 and all(r['passed'] for r in results) and not errors
    return {'scope': 'transformer-matrix', 'passed': passed, 'errors': errors,
            'platforms': results, 'Transformer_accepted': passed, 'M2_accepted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('platform', 'matrix'), default='matrix')
    parser.add_argument('--platform-receipts', type=Path)
    parser.add_argument('--execute', action='store_true', help='execute explicitly prepared public profiles')
    parser.add_argument('--preparation', type=Path)
    parser.add_argument('--legacy-platform', type=Path)
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--acquire-sources', action='store_true')
    parser.add_argument('--recorded-profiles', type=Path)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.execute:
        if args.scope != 'platform' or any(p is None for p in (args.preparation,args.legacy_platform,args.sources)):
            parser.error('execution requires platform scope, preparation, legacy-platform and sources')
        from .transformer_execution import execute_platform
        result = execute_platform(args.source_root,args.preparation,args.legacy_platform,args.sources,args.out,
                 acquire=args.acquire_sources,recorded_profiles=args.recorded_profiles)
        result.setdefault('errors',result.get('replay_errors',[]))
    else:
        if args.platform_receipts is None: parser.error('platform-receipts required for replay')
        result = (aggregate_transformers(args.platform_receipts, args.source_root) if args.scope == 'matrix'
                  else validate_transformer(args.platform_receipts, args.source_root))
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': result['passed'], 'errors': result['errors'], 'M2_accepted': False}))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__': main()
