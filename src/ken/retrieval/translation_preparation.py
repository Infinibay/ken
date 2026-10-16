"""Prepare the measured CT2 files from pinned public data, without Torch."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from ken.model_assets import ModelAssets
from ken.retrieval.query_expansion import LocalQueryExpansion, REQUIRED_ARTIFACTS


def prepare_translation(definition: Mapping[str, Any], destination: Path, *,
                        source_snapshot: Path | None = None, cache_dir: Path | None = None,
                        local_files_only: bool = False) -> None:
    """Normalize JSON formatting only, then authenticate every byte before publish."""
    source = ModelAssets.from_dict(definition['source'])
    target = ModelAssets.from_dict(definition['derived'])
    required = set(REQUIRED_ARTIFACTS)
    if ({a.path for a in source.artifacts} != required
            or {a.path for a in target.artifacts} != required):
        raise ValueError('translation preparation requires the complete measured file set')
    if destination.name != target.revision:
        raise ValueError('derived translation directory must match its origin revision')
    if destination.is_dir():
        target.verify(destination)
        return
    snapshot = (source.verify(source_snapshot) if source_snapshot is not None else
                source.resolve(cache_dir=cache_dir, local_files_only=local_files_only))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prepare-translation-', dir=destination.parent) as stage:
        prepared = Path(stage) / target.revision
        prepared.mkdir()
        for artifact in target.artifacts:
            origin, output = snapshot / artifact.path, prepared / artifact.path
            if artifact.path in {'config.json', 'shared_vocabulary.json'}:
                text = json.dumps(json.loads(origin.read_bytes()), indent=2, ensure_ascii=True)
                if artifact.path == 'config.json':
                    text += '\n'
                output.write_bytes(text.encode('utf-8'))
            else:
                shutil.copyfile(origin, output)
        target.verify(prepared)
        try:
            os.rename(prepared, destination)
        except OSError:
            # Another process may have published the same immutable recipe.
            if not destination.is_dir():
                raise
        target.verify(destination)


def default_query_expansion(*, cache_root: Path | None = None, cache_dir: Path | None = None,
                            local_files_only: bool = False) -> LocalQueryExpansion:
    artifact = resources.files('ken.embedder').joinpath('data/es-en-ct2-int8.json')
    definition = json.loads(artifact.read_text())
    recipe = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    if cache_root is None:
        cache_root = Path(os.environ.get('KEN_CACHE_DIR', str(Path.home() / '.cache' / 'ken'))).expanduser()
    root = cache_root / 'models' / 'translation' / recipe / definition['derived']['revision']
    return LocalQueryExpansion(root, definition['derived'], prepare_artifacts=lambda:
        prepare_translation(definition, root, cache_dir=cache_dir, local_files_only=local_files_only))
