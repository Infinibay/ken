"""Per-language symbol extractors.

Each parser exposes the same shape (``parse_<lang>_file(bytes, hint) ->
ParsedFile``) so the indexer can pick one by extension and not care
about tree-sitter specifics. Adding a language = drop a module, append
to ``LANGUAGE_BY_EXT``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ken.parsers.go import parse_go_file
from ken.parsers.java import parse_java_file
from ken.parsers.javascript import parse_js_file
from ken.parsers.python import parse_python_file
from ken.parsers.rust import parse_rust_file
from ken.parsers.typescript import parse_ts_file
from ken.parsers.types import ParsedFile

ParserFn = Callable[[bytes, str], ParsedFile]

# Extension → (language label, parser fn).
LANGUAGE_BY_EXT: dict[str, tuple[str, ParserFn]] = {
    ".py": ("python", parse_python_file),
    ".pyi": ("python", parse_python_file),
    ".rs": ("rust", parse_rust_file),
    ".js": ("javascript", parse_js_file),
    ".jsx": ("javascript", parse_js_file),
    ".mjs": ("javascript", parse_js_file),
    ".cjs": ("javascript", parse_js_file),
    ".ts": ("typescript", parse_ts_file),
    ".tsx": ("typescript", parse_ts_file),
    ".go": ("go", parse_go_file),
    ".java": ("java", parse_java_file),
}


def detect_language(path: Path) -> tuple[str, ParserFn] | None:
    return LANGUAGE_BY_EXT.get(path.suffix.lower())


__all__ = ["LANGUAGE_BY_EXT", "ParsedFile", "detect_language"]
