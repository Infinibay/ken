"""Resolve indexed candidates to current source, without executing project code."""

from __future__ import annotations

import ast
import io
import tokenize
from typing import Any
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


    def preview(self, candidate: dict) -> dict:
        """Quote bounded code from the same snapshot used to assess this owner."""
        data, symbols = self.cache[candidate["path"]]
        symbol = symbols[(candidate["kind"], candidate["symbol"])]
        if candidate["source"]["sha256"] != symbol.sha256:
            raise ValueError("preview does not match assessed source")
        encoding = (tokenize.detect_encoding(io.BytesIO(data).readline)[0]
                    if Path(symbol.path).suffix in {".py", ".pyi"} else "utf-8")
        lines = data.decode(encoding).splitlines()
        return _preview(symbol, list(symbols.values()), lines, candidate["matched_formulation"])


def _body_start(body: list[ast.stmt]) -> int:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return body[0].lineno if body else 0


def _preview(symbol: Symbol, symbols: list[Symbol], lines: list[str], question: str) -> dict:
    """Keep declaration plus question-relevant implementation, never a doc wall."""
    from .reasoners import terms
    start = symbol.line
    end = len(lines) if symbol.kind == "module" else symbol.end_line
    if not 1 <= start <= end <= len(lines):
        raise ValueError("assessed owner is outside source")
    if end - start + 1 <= 16 and len("\n".join(lines[start-1:end])) <= 4000:
        spans = [(start, end)]
    else:
        query = terms(question)
        if symbol.kind == "class":
            prefix = symbol.qualname + "."
            members = [s for s in symbols if s.qualname.startswith(prefix)
                       and "." not in s.qualname[len(prefix):]]
        elif symbol.kind == "module":
            members = [s for s in symbols if s.kind != "module" and "." not in s.qualname]
        else:
            members = []
        best: tuple[int, int, Symbol, int, int] | None = None
        for owner in members or [symbol]:
            a = owner.implementation_line or owner.line
            b = end if owner.kind == "module" else owner.end_line
            width = min(12, b-a+1)
            if width < 1:
                continue
            for first in range(a, b-width+2):
                text = "\n".join(lines[first-1:first+width-1])
                option = (len(query & terms(text)), -first, owner, first, first+width-1)
                if best is None or option[:2] > best[:2]:
                    best = option
        spans = [(start, min(start+1, end))]
        if best is not None:
            _, _, owner, a, b = best
            if owner != symbol:
                spans.append((owner.line, min(owner.line+1, owner.end_line)))
            spans.append((a, b))
    selected: list[int] = []
    chars = 0
    for number in sorted({n for a, b in spans for n in range(a, b+1)}):
        cost = len(lines[number-1]) + 1
        if len(selected) < 16 and chars + cost <= 4000:
            selected.append(number)
            chars += cost
    snippets: list[dict[str, Any]] = []
    for number in selected:
        if snippets and snippets[-1]["end_line"] == number-1:
            snippets[-1]["end_line"] = number
            snippets[-1]["content"] += "\n" + lines[number-1]
        else:
            snippets.append({"start_line": number, "end_line": number, "content": lines[number-1]})
    result: dict[str, Any] = {"end_line": end, "snippets": snippets, "truncated": len(selected) < end-start+1}
    if not snippets:
        result["preview_unavailable"] = "Source exceeds preview budget; use ken_read for this symbol."
    return result


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
            implementation_line=_body_start(tree.body),
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
                    implementation_line=_body_start(node.body),
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
    detected = detect_language(Path(path), source=data)
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
