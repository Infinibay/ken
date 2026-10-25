"""Explicit native SDK/build preparation, outside neural execution deadlines."""
from __future__ import annotations

import argparse, hashlib, json, os, platform, shutil, subprocess, sys, tempfile
from pathlib import Path
from .transformer_evidence import source_identity
from .native_platform import native_target
from .transformer_cores import transformer_core,transformer_cores
from .transformer_sources import allocated_footprint, capacity_plan, RESERVE_BYTES


def artifact(path: Path) -> dict:
    with path.open('rb') as stream:
        return {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}


def copy_torch_sdk(package: Path, target: Path, registration: dict) -> None:
    if target.exists() or not package.is_absolute() or not target.is_absolute():
        raise ValueError('new absolute SDK destination and explicit package required')
    header = package/'include/torch/csrc/api/include/torch/version.h'
    if f'"{registration["core_version"]}"' not in header.read_text():
        raise ValueError('unregistered Torch SDK version header')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.torch-sdk-', dir=target.parent) as temporary:
        stage = Path(temporary); shutil.copytree(package/'include', stage/'include')
        (stage/'lib').mkdir()
        for name, expected in registration['libraries'].items():
            relative = Path(name)
            if len(relative.parts) != 2 or relative.parts[0] != 'lib' or 'python' in name.lower():
                raise ValueError('registered native library closure required')
            candidates = [p for p in (package/relative, package.parent/'torch.libs'/relative.name) if p.is_file()]
            matching = [p for p in candidates if artifact(p) == expected]
            if not matching: raise ValueError('missing/unregistered native library: '+name)
            shutil.copyfile(matching[0], stage/relative)
            if artifact(stage/relative) != expected: raise ValueError('changed native library: '+name)
        (stage/'PREPARATION.json').write_text(json.dumps({'source': 'explicit verified Torch package',
            'version_header': registration['core_version'], 'python_library_copied': False,
            'libraries': [{'name': Path(name).name, **record} for name, record in registration['libraries'].items()]}, indent=2)+'\n')
        stage.rename(target)



def prepare_tokenizer_sources(catalogue: Path, target: Path, *, borrowed_sources: Path | None = None) -> Path:
    """Publish authenticated tokenizer/config data without any model weights."""
    from ken.model_assets import ModelAssets
    from .fastembed_sources import _download
    if target.exists() or not target.is_absolute(): raise ValueError('fresh absolute metadata destination required')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tokenizer-sources-', dir=target.parent) as temporary:
        stage = Path(temporary)
        for definition in json.loads(catalogue.read_bytes())['models']:
            assets = definition['assets']
            metadata = {name: record for name, record in assets['artifacts'].items()
                        if name.endswith('.json')}
            if not metadata: raise ValueError('registered tokenizer/config artifacts required')
            relative = Path(assets['model_id'].replace('/', '--'))/assets['revision']
            snapshot = stage/relative; snapshot.mkdir(parents=True)
            if borrowed_sources is None:
                _download(ModelAssets.from_dict(assets | {'artifacts': metadata}), snapshot)
            else:
                for name, expected in metadata.items():
                    source = borrowed_sources/relative/name
                    if artifact(source) != expected: raise ValueError('unregistered metadata artifact: '+name)
                    destination = snapshot/name; destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    if artifact(destination) != expected: raise ValueError('changed metadata artifact: '+name)
        stage.rename(target)
    return target


def prepare_transformers(repo: Path, torch_package: Path, mlx_package: Path | None,
                         out: Path, target: Path, cmake: Path | None) -> dict:
    if out.exists() or any(not p.is_absolute() for p in (repo, torch_package, out, target)):
        raise ValueError('fresh explicit absolute transformer preparation paths required')
    system,architecture = native_target(platform.system(),platform.machine())
    registry = json.loads((repo/'tools/rust_migration/data/transformer-cores.json').read_text())
    torch = transformer_core(registry,platform.system(),platform.machine(),'torch')
    before = source_identity(repo)
    out.mkdir(parents=True)
    env = os.environ.copy()
    for name in ('LIBTORCH_USE_PYTORCH', 'LIBTORCH_BYPASS_VERSION_CHECK', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        env.pop(name, None)
    env.update(CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2', CMAKE_BUILD_PARALLEL_LEVEL='2',
               CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    if cmake is not None:
        if not cmake.is_absolute() or not cmake.is_file(): raise ValueError('explicit prepared CMake required')
        env['CMAKE'] = str(cmake)
    def run(name, command):
        with (out/(name+'.log')).open('w') as output:
            subprocess.run(command, cwd=repo, env=env, stdout=output, stderr=subprocess.STDOUT,
                           timeout=3600, check=True)
    # Reserve before SDK copying/building; per-model leases check again later.
    if shutil.disk_usage(out).free < RESERVE_BYTES+2*sum(r['bytes'] for r in torch['libraries'].values()):
        raise OSError('insufficient native preparation free space plus3GiB reserve')
    copy_torch_sdk(torch_package, out/'torch-sdk', torch)
    env.update(LIBTORCH=str(out/'torch-sdk'), LIBTORCH_CXX11_ABI='1', CARGO_TARGET_DIR=str(out/'torch-target'))
    run('torch-build', ['cargo', 'build', '--release', '--locked', '--manifest-path', str(repo/'native/ken-torch-backend/Cargo.toml')])
    suffix = 'dylib' if system == 'macos' else 'so'
    module = out/f'torch-target/release/libken_torch_backend.{suffix}'
    prepared = {'torch_core': str(out/'torch-sdk'), 'torch_module': str(module),
                'torch_module_identity': artifact(module), 'workspace_target': str(target)}
    if system == 'macos':
        if mlx_package is None or not mlx_package.is_absolute(): raise ValueError('explicit pinned MLX SDK required on macOS')
        mlx = transformer_core(registry,platform.system(),platform.machine(),'mlx')
        for name, expected in mlx['libraries'].items():
            if artifact(mlx_package/name) != expected: raise ValueError('unregistered MLX SDK library: '+name)
        env.update(KEN_MLX_CORE=str(mlx_package), CARGO_TARGET_DIR=str(out/'mlx-target'))
        run('mlx-build', ['cargo', 'build', '--release', '--locked', '--manifest-path', str(repo/'native/ken-mlx-backend/Cargo.toml')])
        module = out/'mlx-target/release/libken_mlx_backend.dylib'
        prepared.update(mlx_core=str(mlx_package), mlx_module=str(module), mlx_module_identity=artifact(module))
    env['CARGO_TARGET_DIR'] = str(target)
    run('public-probes-build', ['cargo', 'build', '--release', '--locked', '-p', 'ken-models',
                              '--example', 'sentence_probe', '--example', 'mlx_probe', '--example', 'relevance_probe'])
    for adapter, name in [('sentence', 'sentence_probe'), ('mlx', 'mlx_probe'), ('judge', 'relevance_probe')]:
        path = target/'release/examples'/name
        prepared[adapter+'_probe'] = str(path); prepared[adapter+'_probe_identity'] = artifact(path)
    if before != source_identity(repo): raise ValueError('native source changed while building transformers')
    catalogue = json.loads((repo/'crates/ken-models/resources/transformer-catalog.json').read_text())
    plans = [capacity_plan(model, core, module_bytes=prepared[core['backend']+'_module_identity']['bytes'], acquire=True)
             for model in catalogue['models'] for core in transformer_cores(registry,platform.system(),platform.machine())
             if core['backend'] == 'torch' or model['architecture'] == 'qwen3']
    metadata = prepare_tokenizer_sources(repo/'crates/ken-models/resources/transformer-catalog.json', out/'metadata')
    prepared['metadata_sources'] = str(metadata)
    allocated = allocated_footprint([repo, target, out, Path(sys.prefix)])
    usage = shutil.disk_usage(out); required = max(p['required_free_bytes'] for p in plans)
    if usage.free < required: raise OSError('insufficient transformer model/private-copy free space plus3GiB reserve')
    report = {'format': 'ken-transformer-preparation/1', 'platform': system, 'architecture': architecture, 'source_files': before,
              'prepared': prepared, 'capacity': {'measured_allocated_bytes': allocated,
              'observed_free_bytes': usage.free, 'declared_total_bytes': usage.total,
              'next_phase_required_free_bytes': required, 'model_plans': plans,
              'measured_allocated_plus_next_phase_bytes': allocated+required}}
    if allocated+required > usage.total: raise OSError('measured transformer peak exceeds declared runner capacity')
    (out/'preparation.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path.cwd())
    parser.add_argument('--torch-package', type=Path, required=True)
    parser.add_argument('--mlx-package', type=Path)
    parser.add_argument('--cmake', type=Path)
    parser.add_argument('--target-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = prepare_transformers(args.source_root, args.torch_package, args.mlx_package,
                                  args.out, args.target_root, args.cmake)
    print(json.dumps({'prepared': True, 'capacity': result['capacity']}))


if __name__ == '__main__': main()
