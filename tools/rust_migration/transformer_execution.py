"""Coordinate prepared profiles and gates, with one model lease at a time."""
from __future__ import annotations

import hashlib, json, os, platform, shutil, signal, subprocess, sys
from dataclasses import replace
from pathlib import Path
from .policy_evidence import seal_execution
from .preparation import PreparedNativeTransformer
from .transformer_compare import compare_prepared_transformer
from .transformer_evidence import source_identity
from .transformer_reference import read_original
from .transformer_sources import source_lease


def _gate(repo, environment, out, name, command, *, timeout=600):
    output = out/(name+'.log')
    with output.open('w') as stream:
        process = subprocess.Popen(command, cwd=repo, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try: code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.wait(); code = 124
        finally:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    return {'ran': True, 'passed': code == 0, 'exit_code': code, 'command': command,
            'artifact': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def execute_platform(repo: Path, preparation: Path, legacy_platform: Path, sources: Path,
                     out: Path, *, acquire: bool = False, recorded_profiles: Path | None = None) -> dict:
    from .transformer_validate import FORMAT, EXECUTION_FORMAT, REFERENCE, tooling_identity, validate_transformer
    from .fastembed_evidence import execution_errors
    from .fastembed_validate import fastembed_receipt_errors, fastembed_fingerprints
    if any(not p.is_absolute() for p in (repo, preparation, legacy_platform, sources, out)) or out.exists():
        raise ValueError('fresh explicit absolute platform execution inputs required')
    prepared = json.loads(preparation.read_bytes())
    if prepared['format'] != 'ken-transformer-preparation/1' or prepared['source_files'] != source_identity(repo):
        raise ValueError('stale native transformer build preparation')
    base = json.loads((legacy_platform/'summary.json').read_bytes())
    fingerprints = fastembed_fingerprints(repo, None,
        repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz', None, None, None)
    errors = fastembed_receipt_errors(base, fingerprints) + execution_errors(legacy_platform, base)
    if errors: raise ValueError('current complete34-gate base required: '+str(errors))
    system = 'macos' if platform.system() == 'Darwin' else 'linux'
    if prepared['platform'] != system: raise ValueError('prepared native platform differs')
    slots = prepared['prepared']; catalogue = repo/'crates/ken-models/resources/transformer-catalog.json'
    runtimes = repo/'tools/rust_migration/data/transformer-cores.json'
    registry = json.loads(runtimes.read_bytes())
    originals_index = json.loads((repo/REFERENCE/'INDEX.json').read_bytes())
    originals = [read_original(repo/REFERENCE, row['receipt']) for row in originals_index['chunks']
                 if row['key'].split('|')[0] == system]
    if len(originals) != (24 if system == 'macos' else 9): raise ValueError('complete registered profile inventory required')
    before = source_identity(repo); tooling = tooling_identity(repo)
    out.mkdir(parents=True)
    shutil.copytree(legacy_platform, out/'base', ignore=shutil.ignore_patterns('environment'))
    row = {'format': FORMAT, 'scope': 'transformer-local', 'synthetic_fixture': False,
           'passed': False, 'M2_accepted': False, 'platform': system, 'architecture': 'aarch64',
           'source_files': before, 'tooling': tooling, 'profiles': [], 'gates': {}}
    def save(): (out/'summary.json').write_text(json.dumps(row, indent=2, allow_nan=False)+'\n')
    save()
    env = os.environ.copy()
    env.update(KEN_TORCH_CORE=slots['torch_core'], KEN_TORCH_MODULE=slots['torch_module'],
               KEN_TORCH_PREPARATION=str(Path(slots['torch_core'])/'PREPARATION.json'),
               KEN_TRANSFORMER_SOURCE_ROOT=str(sources), CARGO_INCREMENTAL='0',
               CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    if system == 'macos': env.update(KEN_MLX_CORE=slots['mlx_core'], KEN_MLX_MODULE=slots['mlx_module'])
    tests = [f'tests/rust_migration/test_transformer_{name}.py' for name in
             ('reference', 'process', 'compare', 'evidence', 'validate', 'sources', 'prepare')]
    row['gates']['transformer_unit'] = _gate(repo, env, out, 'transformer-unit',
            [sys.executable, '-m', 'pytest', *tests, '-o', 'addopts=', '-q', f'--junitxml={out/"unit.xml"}'])
    # Native tests may use an explicit loader path; run_transformer removes it
    # from production child environments before any profile execution.
    native_env = env | {'LIBTORCH': slots['torch_core'], 'LIBTORCH_CXX11_ABI': '1',
                       'CARGO_TARGET_DIR': str(Path(slots['torch_module']).parents[1])}
    native_env.pop('LIBTORCH_USE_PYTORCH', None); native_env.pop('LIBTORCH_BYPASS_VERSION_CHECK', None)
    native_env['DYLD_LIBRARY_PATH' if system == 'macos' else 'LD_LIBRARY_PATH'] = str(Path(slots['torch_core'])/'lib')
    row['gates']['native_torch'] = _gate(repo, native_env, out, 'native-torch',
            ['cargo', 'test', '--locked', '--manifest-path', str(repo/'native/ken-torch-backend/Cargo.toml'), '--', '--test-threads=1'])
    if system == 'macos':
        mlx_env = env | {'CARGO_TARGET_DIR': str(Path(slots['mlx_module']).parents[1]),
                         'DYLD_LIBRARY_PATH': str(Path(slots['mlx_core'])/'lib')}
        row['gates']['native_mlx'] = _gate(repo, mlx_env, out, 'native-mlx',
            ['cargo', 'test', '--locked', '--manifest-path', str(repo/'native/ken-mlx-backend/Cargo.toml'), '--', '--test-threads=1'])
    else: row['gates']['native_mlx'] = {'applicable': False, 'reason': 'Apple GPU only'}
    capacity = prepared['capacity']
    valid_capacity = (capacity['observed_free_bytes'] >= capacity['next_phase_required_free_bytes'] and
                      capacity['measured_allocated_plus_next_phase_bytes'] <= capacity['declared_total_bytes'])
    (out/'capacity.json').write_text(json.dumps(capacity, indent=2)+'\n')
    row['gates']['capacity'] = {'ran': True, 'passed': valid_capacity, 'exit_code': 0 if valid_capacity else 1,
                               'artifact': 'capacity.json', 'sha256': hashlib.sha256((out/'capacity.json').read_bytes()).hexdigest()}
    if any(g.get('passed') is False for g in row['gates'].values()):
        save(); return row
    if recorded_profiles is not None:
        from .transformer_validate import replay_transformer_profiles
        replay = replay_transformer_profiles(recorded_profiles, repo)
        if not replay['passed']: raise ValueError('current recorded profiles failed: '+str(replay['errors']))
        recorded = json.loads((recorded_profiles/'summary.json').read_bytes())
        row['profiles'] = recorded['profiles']
        shutil.copytree(recorded_profiles/'profiles', out/'profiles')
    else:
        definitions = json.loads(catalogue.read_bytes())['models']
        for definition in definitions:
            records = [r for r in originals if r['capture']['settings']['model_id'] == definition['name']]
            if not records: continue
            # One shared borrowed/acquired source, released before the next model.
            torch = next(r for r in registry['cores'] if r['os'] == system and r['backend'] == 'torch')
            initial = PreparedNativeTransformer(Path(slots['sentence_probe']), sources, catalogue,
                Path(slots['torch_module']), Path(slots['torch_core']), runtimes, acquire=acquire)
            with source_lease(initial, definition, torch, module_bytes=slots['torch_module_identity']['bytes']) as leased:
                for original in records:
                    adapter = original['adapter']; backend = 'mlx' if adapter == 'mlx' else original['capture']['settings'].get('backend', 'torch')
                    active = replace(leased, probe=Path(slots[adapter+'_probe']),
                        module=Path(slots[backend+'_module']), core=Path(slots[backend+'_core']))
                    destination = out/'profiles'/f'{len(row["profiles"]):02}'
                    observation = compare_prepared_transformer(active, original, repo, destination)
                    observation['directory'] = str(destination.relative_to(out))
                    (destination/'profile.json').write_text(json.dumps(observation, indent=2)+'\n')
                    row['profiles'].append(observation)
                    if not observation['comparison']['passed']:
                        save(); return row
    row['passed'] = True
    row['execution_artifacts'] = seal_execution(out, format=EXECUTION_FORMAT); save()
    env['KEN_TRANSFORMER_PLATFORM_EXECUTION'] = str(out)
    row['gates']['transformer_parity'] = _gate(repo, env, out, 'transformer-parity',
        [sys.executable, '-m', 'pytest', 'transformer_migration_tests/test_parity.py', '-o', 'addopts=', '-q'])
    env['KEN_TRANSFORMER_OWNERSHIP_LOG'] = str(out/'native-owners.log')
    row['gates']['transformer_ownership'] = _gate(repo, env, out, 'transformer-ownership',
        [sys.executable, '-m', 'pytest', 'transformer_migration_tests/test_ownership.py', '-o', 'addopts=', '-q'])
    row['passed'] = (before == source_identity(repo) and tooling == tooling_identity(repo) and
                    all(g.get('passed', not g.get('applicable', True)) for g in row['gates'].values()))
    row['execution_artifacts'] = seal_execution(out, format=EXECUTION_FORMAT); save()
    replay = validate_transformer(out, repo)
    if not replay['passed']:
        row['passed'] = False; row['replay_errors'] = replay['errors']; save()
    return row
