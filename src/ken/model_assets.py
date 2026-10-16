"""Portable, content-verified public model assets, independent of inference."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class ModelPreparationError(RuntimeError):
    """A declared public model needs preparation before local inference."""


@dataclass(frozen=True)
class ModelArtifact:
    path: str
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if (not re.fullmatch(r'[A-Za-z0-9_./-]+', self.path)
                or PurePosixPath(self.path).is_absolute()
                or any(p in ('', '.', '..') for p in self.path.split('/'))):
            raise ValueError('model artifact path must be local and relative')
        if type(self.bytes) is not int or self.bytes < 0:
            raise ValueError('model artifact byte count must be nonnegative')
        if not re.fullmatch(r'[a-f0-9]{64}', self.sha256):
            raise ValueError('model artifact requires a SHA256 digest')


@dataclass(frozen=True)
class ModelAssets:
    model_id: str
    revision: str
    artifacts: tuple[ModelArtifact, ...]
    license: str = ''

    def __post_init__(self) -> None:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.model_id):
            raise ValueError('a public Hugging Face model identifier is required')
        if not re.fullmatch(r'[a-f0-9]{40}', self.revision):
            raise ValueError('an immutable Hugging Face revision is required')
        if not self.artifacts or len({a.path for a in self.artifacts}) != len(self.artifacts):
            raise ValueError('distinct model artifacts are required')

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModelAssets:
        return cls(value['model_id'], value['revision'], tuple(sorted(
            (ModelArtifact(path, record['bytes'], record['sha256'])
             for path, record in value['artifacts'].items()), key=lambda a: a.path)), value.get('license', ''))

    def to_dict(self) -> dict[str, Any]:
        return {'model_id': self.model_id, 'revision': self.revision, 'license': self.license,
                'artifacts': {a.path: {'bytes': a.bytes, 'sha256': a.sha256} for a in self.artifacts}}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()

    def verify(self, snapshot: Path) -> Path:
        """Accept cache symlinks, but require exact declared bytes before use."""
        if snapshot.name != self.revision or not snapshot.is_dir():
            raise ValueError('registered model revision required')
        for artifact in self.artifacts:
            path = snapshot / artifact.path
            if not path.is_file() or path.stat().st_size != artifact.bytes:
                raise ValueError(f'registered model artifact missing or changed: {artifact.path}')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != artifact.sha256:
                raise ValueError(f'registered model artifact changed: {artifact.path}')
        return snapshot

    def resolve(self, *, cache_dir: Path | None = None, local_files_only: bool = False) -> Path:
        """Download only pinned data files; never model code or floating refs."""
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError
        snapshot = None
        try:
            for artifact in self.artifacts:
                path = Path(hf_hub_download(self.model_id, filename=artifact.path,
                    revision=self.revision, cache_dir=cache_dir, local_files_only=local_files_only, token=False))
                root = path.parents[len(PurePosixPath(artifact.path).parts) - 1]
                if snapshot is not None and snapshot != root:
                    raise ValueError('model artifacts resolved to different snapshots')
                snapshot = root
        except (HfHubHTTPError, LocalEntryNotFoundError, OSError) as exc:
            raise ModelPreparationError(f'Cannot prepare {self.model_id}@{self.revision}; '
                'allow its pinned public files to download once, then retry offline.') from exc
        if snapshot is None:
            raise ValueError('model assets have no files')
        return self.verify(snapshot)
