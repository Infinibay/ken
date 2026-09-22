"""Resolve indexed candidates to current source, without executing project code."""

from __future__ import annotations

import ast
from hashlib import blake2b, sha256
from pathlib import Path

from ken.parsers import detect_language

from .model import Symbol


class SourceReader:
    """Bound file reads and reuse a single snapshot for symbols in the same file."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.cache: dict[str, tuple[bytes, dict[tuple[str, str], Symbol]]] = {}

    def resolve(self, row: dict) -> Symbol:
        path = row["path"]
        if path not in self.cache:
            target = (self.root / path).resolve()
            if not target.is_relative_to(self.root):
                raise ValueError("source escapes project")
            if len(self.cache) >= 24:
                raise ValueError("source file budget exhausted")
            with target.open("rb") as stream:
                data = stream.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("source exceeds 2 MiB")
            digest = sha256(data).hexdigest()
            symbols = (
                _python(data, path, digest)
                if target.suffix in {".py", ".pyi"}
                else _other(data, path, digest)
            )
            self.cache[path] = data, symbols
        data, symbols = self.cache[path]
        symbol = symbols.get((row["kind"], row["qualname"]))
        if symbol is None:
            raise ValueError("indexed symbol no longer present or parser unavailable")
        from dataclasses import replace

        return replace(
            symbol,
            refreshed=blake2b(data, digest_size=32).digest() != row["content_hash"],
        )


def _python(data: bytes, path: str, digest: str) -> dict[tuple[str, str], Symbol]:
    tree = ast.parse(data)
    result = {}
    documentation = ast.get_docstring(tree)
    if documentation:
        doc = tree.body[0]
        result[("module", path)] = Symbol(
            path,
            path,
            "module",
            doc.lineno,
            doc.end_lineno or doc.lineno,
            documentation,
            digest,
        )

    def walk(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = prefix + node.name
                cls = isinstance(node, ast.ClassDef)
                calls = () if cls else tuple(_calls(node.body))
                kind = "class" if cls else "method" if prefix else "function"
                result[(kind, qualname)] = Symbol(
                    path,
                    qualname,
                    kind,
                    node.lineno,
                    node.end_lineno or node.lineno,
                    ast.get_docstring(node) or "",
                    digest,
                    calls,
                )
                if cls:
                    walk(node.body, qualname + ".")
            elif hasattr(node, "body"):
                walk(node.body, prefix)

    walk(tree.body)
    return result


def _calls(body):
    pending = list(body)
    while pending:
        node = pending.pop()
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                yield node.func.id, node.lineno
            elif isinstance(node.func, ast.Attribute):
                yield node.func.attr, node.lineno
        pending.extend(ast.iter_child_nodes(node))


def _other(data: bytes, path: str, digest: str) -> dict[tuple[str, str], Symbol]:
    detected = detect_language(Path(path))
    if detected is None:
        raise ValueError("unsupported source language")
    parsed = detected[1](data, path)
    result = {
        (s.kind, s.qualname): Symbol(
            path,
            s.qualname,
            s.kind,
            s.line_start,
            s.line_end,
            s.docstring or "",
            digest,
            doc_scope="parser_excerpt",
        )
        for s in parsed.symbols
    }
    if parsed.docstring:
        result[("module", path)] = Symbol(
            path,
            path,
            "module",
            1,
            min(len(data.splitlines()), 150),
            parsed.docstring,
            digest,
            doc_scope="parser_excerpt",
        )
    return result
