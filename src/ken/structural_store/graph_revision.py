"""Graph-data versioning is independent of query/compiler implementation."""

from functools import lru_cache
from hashlib import sha256
from pathlib import Path


@lru_cache(maxsize=1)
def graph_revision() -> str:
    root = Path(__file__).parent.parent
    execution_only = {
        "cache.py",
        "catalog.py",
        "catalog_evaluation.py",
        "index_service.py",
        "kenql.py",
        "query.py",
        "rules.py",
        "selectors.py",
        "serialization.py",
        "service.py",
    }
    files = [
        path
        for path in (root / "structural").glob("*.py")
        if path.name not in execution_only and not path.name.startswith("relational")
    ]
    files.extend((root / "common_ast").glob("*.py"))
    # Storage layout changes belong to schema migrations, not source analysis.
    # Bump this contract only when projection semantics cannot be migrated from
    # existing indexed columns. Writer/cache refactors must not reparse a repo.
    digest = sha256(b"native-query-graph/1")
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()
