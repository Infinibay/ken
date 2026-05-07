"""Per-language symbol extractors.

Each parser exposes the same shape (`parse_file`) so the indexer can
pick one by language and not care about tree-sitter specifics. Adding
a language = drop a module, register it in `LANGUAGE_BY_EXT`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ken.parsers.python import parse_python_file
from ken.parsers.types import ParsedFile


# Extension → (language label, parser fn). One of these or nothing.
LANGUAGE_BY_EXT: dict[str, tuple[str, Callable[[bytes, str], ParsedFile]]] = {
    ".py": ("python", parse_python_file),
    ".pyi": ("python", parse_python_file),
}


def detect_language(path: Path) -> tuple[str, Callable[[bytes, str], ParsedFile]] | None:
    return LANGUAGE_BY_EXT.get(path.suffix.lower())


__all__ = ["LANGUAGE_BY_EXT", "ParsedFile", "detect_language"]
