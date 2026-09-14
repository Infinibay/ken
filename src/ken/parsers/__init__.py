"""Per-language symbol extractors.

Each parser exposes the same shape (``parse_<lang>_file(bytes, hint) ->
ParsedFile``) so the indexer can pick one by extension and not care
about tree-sitter specifics. Adding a language = drop a module, append
to ``LANGUAGE_BY_EXT``.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

from ken.parsers.types import ParsedFile

ParserFn = Callable[[bytes, str], ParsedFile]


def _load(module: str, attribute: str) -> ParserFn:
    """Import one language's parser, without letting it take the package down.

    Every grammar is loaded at its module's import time, and some of them come
    from ``tree-sitter-language-pack``, which downloads and extracts a shared
    library on first use. A machine where that extraction fails (no network, a
    cache directory the process may not create) used to fail *every* language,
    because this package imported all nineteen parsers eagerly: a scan of a
    C# repository died on the Bash grammar. The failure is now confined to the
    language that needs it and names itself when called.
    """
    try:
        return getattr(importlib.import_module(f"ken.parsers.{module}"), attribute)
    except Exception as exc:  # pragma: no cover - depends on the host's grammar cache
        def unavailable(content: bytes, hint: str, *, _module: str = module, _cause: Exception = exc) -> ParsedFile:
            raise RuntimeError(f"the {_module} parser is unavailable: {_cause}") from _cause
        unavailable.__name__ = attribute
        return unavailable


parse_bash_file = _load("bash", "parse_bash_file")
parse_c_file = _load("c", "parse_c_file")
parse_cpp_file = _load("cpp", "parse_cpp_file")
parse_csharp_file = _load("csharp", "parse_csharp_file")
parse_css_file = _load("css", "parse_css_file")
parse_dart_file = _load("dart", "parse_dart_file")
parse_go_file = _load("go", "parse_go_file")
parse_graphql_file = _load("graphql", "parse_graphql_file")
parse_html_file = _load("html", "parse_html_file")
parse_java_file = _load("java", "parse_java_file")
parse_js_file = _load("javascript", "parse_js_file")
parse_kotlin_file = _load("kotlin", "parse_kotlin_file")
parse_php_file = _load("php", "parse_php_file")
parse_powershell_file = _load("powershell", "parse_powershell_file")
parse_python_file = _load("python", "parse_python_file")
parse_ruby_file = _load("ruby", "parse_ruby_file")
parse_rust_file = _load("rust", "parse_rust_file")
parse_sql_file = _load("sql", "parse_sql_file")
parse_ts_file = _load("typescript", "parse_ts_file")

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
