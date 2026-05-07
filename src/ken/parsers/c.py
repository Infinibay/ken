"""Lightweight C symbol extractor.

This is intentionally regex/brace based rather than a full C parser.
For large C codebases such as the Linux kernel, the highest-value cold
start signal is mapping function-like names in prompts to files. A
conservative top-level definition extractor is enough for that without
adding another tree-sitter runtime dependency.
"""

from __future__ import annotations

import re

from ken.parsers.types import ParsedFile, ParsedSymbol

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_CONTROL = {"if", "for", "while", "switch", "return", "sizeof"}
_FUNC_HEADER_RE = re.compile(
    rf"(?P<header>(?:^|[;\n}}\]])[^\n;{{}}#]*?\b(?P<name>{_IDENT})\s*\([^;{{}}]*\)\s*)\{{",
    re.MULTILINE,
)
_MACRO_DEF_RE = re.compile(
    rf"^\s*(?P<macro>SYSCALL_DEFINE\d+|COMPAT_SYSCALL_DEFINE\d+|BPF_CALL_\d+)\s*"
    rf"\(\s*(?P<name>{_IDENT})\b",
    re.MULTILINE,
)


def parse_c_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    text = source.decode("utf-8", errors="replace")
    out = ParsedFile()
    seen: set[str] = set()
    for name, line in _macro_symbols(text):
        seen.add(name)
        out.symbols.append(
            ParsedSymbol(
                kind="function",
                name=name,
                qualname=name,
                line_start=line,
                line_end=line,
            )
        )
    for match in _FUNC_HEADER_RE.finditer(_strip_comments(text)):
        name = match.group("name")
        if name in _CONTROL or name in seen or _is_macro_name(name):
            continue
        header = match.group("header")
        if _looks_like_call_site(header):
            continue
        start_line = text.count("\n", 0, match.start("name")) + 1
        out.symbols.append(
            ParsedSymbol(
                kind="function",
                name=name,
                qualname=name,
                line_start=start_line,
                line_end=_matching_brace_line(text, match.end() - 1),
            )
        )
        seen.add(name)
    out.symbols.sort(key=lambda s: (s.line_start, s.name))
    return out


def _macro_symbols(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for match in _MACRO_DEF_RE.finditer(text):
        macro = match.group("macro")
        raw = match.group("name")
        name = f"__{raw}" if macro.startswith(("SYSCALL_DEFINE", "COMPAT_")) else raw
        out.append((name, text.count("\n", 0, match.start("name")) + 1))
    return out


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", _blank_match, text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _blank_match(match: re.Match[str]) -> str:
    return "\n" * match.group(0).count("\n")


def _looks_like_call_site(header: str) -> bool:
    stripped = " ".join(header.split())
    if "=" in stripped:
        return True
    if stripped.startswith(("else ", "do ")):
        return True
    return False


def _is_macro_name(name: str) -> bool:
    return bool(re.match(r"^(SYSCALL_DEFINE\d+|COMPAT_SYSCALL_DEFINE\d+|BPF_CALL_\d+)$", name))


def _matching_brace_line(text: str, open_brace: int) -> int:
    depth = 0
    for idx in range(open_brace, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text.count("\n", 0, idx) + 1
    return text.count("\n", 0, open_brace) + 1
