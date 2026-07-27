"""Per-language symbol extractors.

Each parser exposes the same shape (``parse_<lang>_file(bytes, hint) ->
ParsedFile``) so the indexer can pick one by extension and not care
about tree-sitter specifics. Adding a language = drop a module, append
to ``LANGUAGE_BY_EXT``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ken.parsers.bash import parse_bash_file
from ken.parsers.c import parse_c_file
from ken.parsers.cpp import parse_cpp_file
from ken.parsers.csharp import parse_csharp_file
from ken.parsers.css import parse_css_file
from ken.parsers.dart import parse_dart_file
from ken.parsers.go import parse_go_file
from ken.parsers.graphql import parse_graphql_file
from ken.parsers.html import parse_html_file
from ken.parsers.java import parse_java_file
from ken.parsers.javascript import parse_js_file
from ken.parsers.kotlin import parse_kotlin_file
from ken.parsers.php import parse_php_file
from ken.parsers.powershell import parse_powershell_file
from ken.parsers.python import parse_python_file
from ken.parsers.ruby import parse_ruby_file
from ken.parsers.rust import parse_rust_file
from ken.parsers.sql import parse_sql_file
from ken.parsers.typescript import parse_ts_file
from ken.parsers.types import ParsedFile

ParserFn = Callable[[bytes, str], ParsedFile]

# Extension → (language label, parser fn).
LANGUAGE_BY_EXT: dict[str, tuple[str, ParserFn]] = {
    ".c": ("c", parse_c_file),
    ".h": ("c", parse_c_file),
    ".cpp": ("cpp", parse_cpp_file),
    ".cc": ("cpp", parse_cpp_file),
    ".cxx": ("cpp", parse_cpp_file),
    ".hpp": ("cpp", parse_cpp_file),
    ".hh": ("cpp", parse_cpp_file),
    ".hxx": ("cpp", parse_cpp_file),
    ".ipp": ("cpp", parse_cpp_file),
    ".cs": ("csharp", parse_csharp_file),
    ".csx": ("csharp", parse_csharp_file),
    ".css": ("css", parse_css_file),
    ".html": ("html", parse_html_file),
    ".htm": ("html", parse_html_file),
    # Server-side template dialects are HTML with an extra brace syntax the
    # grammar treats as text, so the tags, ids and script sources still come
    # out — which is the part ken indexes.
    ".vue": ("html", parse_html_file),
    ".svelte": ("html", parse_html_file),
    ".py": ("python", parse_python_file),
    ".pyi": ("python", parse_python_file),
    ".rs": ("rust", parse_rust_file),
    ".rb": ("ruby", parse_ruby_file),
    ".rake": ("ruby", parse_ruby_file),
    ".gemspec": ("ruby", parse_ruby_file),
    ".js": ("javascript", parse_js_file),
    ".jsx": ("javascript", parse_js_file),
    ".mjs": ("javascript", parse_js_file),
    ".cjs": ("javascript", parse_js_file),
    ".ts": ("typescript", parse_ts_file),
    ".tsx": ("typescript", parse_ts_file),
    ".go": ("go", parse_go_file),
    ".java": ("java", parse_java_file),
    ".kt": ("kotlin", parse_kotlin_file),
    ".kts": ("kotlin", parse_kotlin_file),
    ".dart": ("dart", parse_dart_file),
    ".php": ("php", parse_php_file),
    ".phtml": ("php", parse_php_file),
    ".sql": ("sql", parse_sql_file),
    ".graphql": ("graphql", parse_graphql_file),
    ".gql": ("graphql", parse_graphql_file),
    ".sh": ("bash", parse_bash_file),
    ".bash": ("bash", parse_bash_file),
    ".ksh": ("bash", parse_bash_file),
    ".ps1": ("powershell", parse_powershell_file),
    ".psm1": ("powershell", parse_powershell_file),
    ".psd1": ("powershell", parse_powershell_file),
}


def detect_language(path: Path) -> tuple[str, ParserFn] | None:
    return LANGUAGE_BY_EXT.get(path.suffix.lower())


__all__ = ["LANGUAGE_BY_EXT", "ParsedFile", "detect_language"]
