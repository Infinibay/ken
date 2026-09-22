"""Per-project compilation retention; plans never embed a graph or SQLite IDs."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import RLock

from .cache import ArtifactCache
from .compiler import Program, Scan, compile
from .execution import prepare
from .syntax import parse


@dataclass(frozen=True, slots=True)
class Prepared:
    program: Program
    plans: tuple[tuple[str, tuple[Scan, ...]], ...]


_LOCK = RLock()
_PROJECTS: OrderedDict[str, ArtifactCache[Prepared]] = OrderedDict()
# A bounded number of project coordinators; evicted coordinators cannot admit
# in-flight work after clear. Their active callers still own working references.
_MAX_PROJECTS = 8
COMPILER_REVISION = "structural-compiler/3"


@lru_cache(maxsize=1)
def implementation_fingerprint() -> str:
    digest = sha256(COMPILER_REVISION.encode())
    for file in sorted(Path(__file__).parent.rglob("*.py")):
        digest.update(file.relative_to(Path(__file__).parent).as_posix().encode())
        digest.update(sha256(file.read_bytes()).digest())
    structural = Path(__file__).parent.parent / "structural"
    for file in sorted(
        [
            *structural.glob("relational*.py"),
            structural / "query_view.py",
            structural / "query.py",
        ]
    ):
        digest.update(file.name.encode())
        digest.update(sha256(file.read_bytes()).digest())
    for file in sorted((structural.parent / 'structural_store').glob('graph_*.py')):
        digest.update(file.name.encode())
        digest.update(sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def artifact_key(
    source: str,
    query: str | None,
    reference: bool,
    libraries: Mapping[str, str] | None = None,
) -> str:
    raw = (
        repr(
            (
                implementation_fingerprint(),
                query,
                reference,
                sorted((libraries or {}).items()),
            )
        ).encode()
        + b"\0"
        + source.encode()
    )
    return sha256(raw).hexdigest()


def compile_query(
    root: Path,
    source: str,
    query: str | None,
    *,
    budget_bytes: int,
    reference: bool = False,
    libraries: Mapping[str, str] | None = None,
) -> tuple[Prepared, str, dict[str, int]]:
    from .catalog import with_packaged_libraries

    libraries = (
        with_packaged_libraries(source) if libraries is None else dict(libraries)
    )
    capacity = min(budget_bytes // 5, 100_000_000)
    with _LOCK:
        name = str(root)
        cache = _PROJECTS.get(name)
        if cache is None:
            cache = ArtifactCache(capacity)
            if capacity:
                _PROJECTS[name] = cache
        else:
            _PROJECTS.move_to_end(name)
            cache.configure(capacity)
            if not capacity:
                _PROJECTS.pop(name)
        while len(_PROJECTS) > _MAX_PROJECTS:
            _, old = _PROJECTS.popitem(last=False)
            old.clear()
    key = artifact_key(source, query, reference, libraries)
    disk_hit = False

    def compute() -> Prepared:
        nonlocal disk_hit
        if capacity:
            from ken.structural_store.artifacts import read_existing

            from .codec import CODEC, decode

            payload = read_existing(
                root / ".ken/structural/v2/store.sqlite", key, CODEC, max_bytes=capacity
            )
            if payload is not None:
                try:
                    prepared = decode(payload, max_bytes=capacity)
                    disk_hit = True
                    return prepared
                except ValueError:
                    pass
        program = compile(
            parse(source),
            query,
            libraries={name: parse(text, name) for name, text in libraries.items()},
        )
        programs = program.branches or (program,)
        return Prepared(
            program,
            tuple((p.fingerprint, prepare(p, reference=reference)) for p in programs),
        )

    prepared, state = cache.get_or_compute(key, compute)
    return prepared, "disk_hit" if disk_hit else state, cache.stats()


def clear_compilation_cache() -> None:
    with _LOCK:
        for cache in _PROJECTS.values():
            cache.clear()
        _PROJECTS.clear()
