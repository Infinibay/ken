"""Expand Spanish queries locally with a pinned, lazy CPU int8 translator."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Callable, Mapping
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

REQUIRED_ARTIFACTS = ('model.bin', 'config.json', 'shared_vocabulary.json', 'source.spm', 'target.spm')
_SPANISH = frozenset(('dónde donde cuál cual qué que cómo como quién quien función funcion método '
    'metodo clase prueba pruebas archivo encuentra busca devuelve convierte obtiene implementa '
    'contiene permite devuelve crea genera elimina cuando una uno los las para del con por').split())
_PROTECTED = re.compile(r'`[^`]+`|\b[A-Za-z_$][\w$]*(?:[.:]+[\w$]+)+\b|\b[A-Za-z_$]+_[A-Za-z_$\d]+\b')


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return 'unavailable'


def _load_cpu_runtime(root: Path) -> tuple[Any, Any, Any]:
    ct2 = import_module('ctranslate2')
    sentencepiece = import_module('sentencepiece')
    model = ct2.Translator(str(root), device='cpu', compute_type='int8', inter_threads=1, intra_threads=2)
    return (model, sentencepiece.SentencePieceProcessor(model_file=str(root/'source.spm')),
            sentencepiece.SentencePieceProcessor(model_file=str(root/'target.spm')))


class LocalQueryExpansion:
    """Query text chooses the language path; no labels or remote service enter it."""
    def __init__(self, root: Path, registration: Mapping[str, Any], *,
                 load_runtime: Callable[[Path], tuple[Any, Any, Any]] = _load_cpu_runtime,
                 prepare_artifacts: Callable[[], None] | None = None):
        self.root = root.resolve()
        artifacts = {name: dict(registration['artifacts'][name]) for name in REQUIRED_ARTIFACTS}
        self.identity = {'model_id': registration['model_id'], 'revision': registration['revision'],
            'artifacts': artifacts, 'runtime': {p: _version(p) for p in ('ctranslate2', 'sentencepiece')},
            'device': 'cpu', 'compute_type': 'int8', 'intra_threads': 2, 'inter_threads': 1,
            'beam_size': 1, 'max_decoding_length': 256,
            'preprocessing': 'spanish-lexicon-two-or-question-protect-qualified-identifiers-v1'}
        self.revision = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()
        self._artifacts = artifacts
        self._load_runtime = load_runtime
        self._prepare_artifacts = prepare_artifacts
        self._runtime: tuple[Any, Any, Any] | None = None
        self._lock = threading.Lock()

    def _load(self) -> tuple[Any, Any, Any]:
        if self._runtime is None:
            with self._lock:
                if self._runtime is None:
                    if self._prepare_artifacts is not None:
                        self._prepare_artifacts()
                    for name, expected in self._artifacts.items():
                        path = self.root/name
                        if not path.is_file() or path.stat().st_size != expected['bytes']:
                            raise ValueError(f'local query expansion artifact missing or changed: {name}')
                        with path.open('rb') as stream:
                            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                        if actual != expected['sha256']:
                            raise ValueError(f'local query expansion artifact changed: {name}')
                    self._runtime = self._load_runtime(self.root)
        return self._runtime

    def __call__(self, query: str) -> str:
        words = set(re.findall(r'\w+', query.casefold()))
        if '¿' not in query and len(_SPANISH & words) < 2:
            return query
        protected: dict[str, str] = {}

        def protect(match: re.Match[str]) -> str:
            key = 'ZXQ'+str(len(protected))+'QXZ'
            protected[key] = match[0]
            return key

        prepared = _PROTECTED.sub(protect, query)
        model, source, target = self._load()
        tokens = source.encode(prepared, out_type=str) + ['</s>']
        results = model.translate_batch([tokens], beam_size=1, max_decoding_length=256)
        expanded = target.decode(results[0].hypotheses[0])
        for key, value in protected.items():
            expanded = re.sub(r'\s*'.join(map(re.escape, key)), lambda _: value, expanded, flags=re.I)
        if not isinstance(expanded, str) or not expanded.strip():
            raise ValueError('local query expansion produced empty text')
        return expanded
