"""Bounded per-model preparation; borrowed sources and unrelated caches survive."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib, os, shutil, tempfile
from pathlib import Path
from .preparation import PreparedNativeTransformer
from .fastembed_sources import _download

RESERVE_BYTES = 3 * 1024**3


def capacity_plan(definition: dict, runtime: dict, *, module_bytes: int, acquire: bool) -> dict:
    if type(module_bytes) is not int or module_bytes <= 0 or type(acquire) is not bool:
        raise ValueError('explicit native size and acquisition policy required')
    source = sum(r['bytes'] for r in definition['assets']['artifacts'].values())
    core = sum(r['bytes'] for r in runtime['libraries'].values())
    private = source + core + module_bytes
    return {'model_source_bytes': source, 'private_bytes': private,
            'reserve_bytes': RESERVE_BYTES,
            'required_free_bytes': (source if acquire else 0) + private + RESERVE_BYTES}


def allocated_footprint(paths: list[Path]) -> int:
    """Count each actual inode once, including sparse/clone allocation as reported."""
    seen, total = set(), 0
    for root in paths:
        for path in ([root] if root.is_file() else root.rglob('*')):
            if path.is_symlink() or not path.is_file(): continue
            stat = path.stat(); key = (stat.st_dev, stat.st_ino)
            if key not in seen:
                seen.add(key); total += getattr(stat, 'st_blocks', (stat.st_size+511)//512)*512
    return total


def verify_source(prepared: PreparedNativeTransformer, definition: dict) -> None:
    assets = definition['assets']
    snapshot = prepared.sources/assets['model_id'].replace('/', '--')/assets['revision']
    for name, expected in assets['artifacts'].items():
        relative = Path(name)
        if relative.is_absolute() or any(p in ('.', '..') for p in relative.parts):
            raise ValueError('unsafe registered transformer artifact')
        path = snapshot/relative
        if not path.is_file() or path.stat().st_size != expected['bytes']:
            raise ValueError('missing/wrong-size transformer artifact: '+name)
        digest = hashlib.sha256(); size = 0
        with path.open('rb') as stream:
            while chunk := stream.read(min(65536, expected['bytes']-size+1)):
                size += len(chunk)
                if size > expected['bytes']: raise ValueError('oversized transformer artifact: '+name)
                digest.update(chunk)
        if size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
            raise ValueError('transformer artifact hash mismatch: '+name)


@contextmanager
def source_lease(prepared: PreparedNativeTransformer, definition: dict, runtime: dict, *, module_bytes: int):
    prepared.environment()
    prepared.sources.mkdir(parents=True, exist_ok=True)
    plan = capacity_plan(definition, runtime, module_bytes=module_bytes, acquire=prepared.acquire)
    free = shutil.disk_usage(prepared.sources).free
    if free < plan['required_free_bytes']:
        raise OSError(f'transformer capacity: need {plan["required_free_bytes"]} free bytes, have {free}')
    if not prepared.acquire:
        verify_source(prepared, definition)
        yield prepared
        return
    from ken.model_assets import ModelAssets
    assets = ModelAssets.from_dict(definition['assets'])
    with tempfile.TemporaryDirectory(prefix='transformer-lease-', dir=prepared.sources) as temporary:
        root = Path(temporary)
        snapshot = root/assets.model_id.replace('/', '--')/assets.revision
        snapshot.mkdir(parents=True)
        _download(assets, snapshot)
        leased = replace(prepared, sources=root, acquire=False)
        verify_source(leased, definition)
        yield leased
