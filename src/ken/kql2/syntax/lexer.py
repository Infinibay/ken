"""Contextual lexer: slash becomes regex only when the parser requests one."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .ast import Span


class ParseError(ValueError):
    def __init__(self, message: str, span: Span, code: str = "syntax_error"):
        self.message, self.span, self.code = message, span, code
        super().__init__(f"{span.source}:{span.start}: {message}")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    span: Span


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_OPERATORS = ("...", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "++", "--", "**", "->")


class Lexer:
    def __init__(self, text: str, source: str, *, max_bytes: int = 2_000_000):
        self.text, self.source, self.pos = text, source, 0
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ParseError("input is not valid UTF-8", Span(source, 0, 0)) from exc
        if size > max_bytes:
            raise ParseError("input byte limit exceeded", Span(source, 0, size), "resource_limit")
        # One linear pass; token spans must not encode the entire prefix each time.
        self.offsets = [0]
        for char in text:
            self.offsets.append(self.offsets[-1] + len(char.encode("utf-8")))
        self.cached: Token | None = None

    def span(self, start: int, end: int) -> Span:
        return Span(self.source, self.offsets[start], self.offsets[end])

    def fail(self, message: str, start: int | None = None) -> None:
        at = self.pos if start is None else start
        raise ParseError(message, self.span(at, min(at + 1, len(self.text))))

    def skip(self) -> None:
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith("//", self.pos):
                end = self.text.find("\n", self.pos + 2)
                self.pos = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end < 0:
                    self.fail("unterminated comment")
                self.pos = end + 2
            else:
                break

    def peek(self) -> Token:
        if self.cached is None:
            self.cached = self.read()
        return self.cached

    def take(self) -> Token:
        token = self.peek()
        self.cached = None
        return token

    def read(self) -> Token:
        self.skip()
        start = self.pos
        if start == len(self.text):
            return Token("EOF", "", self.span(start, start))
        char = self.text[start]
        if char == '"':
            self.pos += 1
            while self.pos < len(self.text):
                current = self.text[self.pos]
                self.pos += 1
                if current == "\\":
                    self.pos += 1
                elif current == '"':
                    break
            else:
                self.fail("unterminated string", start)
            raw = self.text[start:self.pos]
            try:
                decoded = json.loads(raw)
                decoded.encode("utf-8")
            except (ValueError, UnicodeEncodeError) as exc:
                raise ParseError("invalid JSON string", self.span(start, min(self.pos, len(self.text)))) from exc
            kind = "STRING"
        elif char == "$":
            match = _IDENT.match(self.text, start + 1)
            if not match:
                self.fail("expected role name", start)
            assert match is not None
            self.pos, kind = match.end(), "ROLE"
        elif char.isascii() and char.isdigit():
            match = _NUMBER.match(self.text, start)
            assert match is not None
            self.pos = match.end()
            kind = "FLOAT" if any(c in match.group() for c in ".eE") else "INTEGER"
        elif _IDENT.match(self.text, start):
            match = _IDENT.match(self.text, start)
            assert match is not None
            self.pos, kind = match.end(), "IDENT"
        else:
            operator = next((op for op in _OPERATORS if self.text.startswith(op, start)), char)
            if operator not in _OPERATORS and char not in "{}()[];,:.|&^~+-*/%<>=_":
                self.fail(f"unexpected character {char!r}")
            self.pos += len(operator)
            kind = "SYMBOL"
        return Token(kind, self.text[start:self.pos], self.span(start, self.pos))

    def regex(self) -> Token:
        opening = self.take()
        if opening.text != "/":
            raise ParseError("expected regular expression", opening.span)
        start = self.pos - 1
        in_class = False
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == "\\":
                if self.pos == len(self.text):
                    self.fail("unterminated regex", start)
                escaped = self.text[self.pos]
                if escaped.isdigit() or escaped in "gk":
                    self.fail("regex backreferences are not supported", start)
                self.pos += 1
            elif char == "[":
                in_class = True
            elif char == "]":
                in_class = False
            elif char == "/" and not in_class:
                break
            elif char in "\r\n":
                self.fail("newline in regex", start)
            elif char == "(" and self.text.startswith("?", self.pos):
                if not self.text.startswith("?:", self.pos):
                    self.fail("regex extensions other than (?:...) are not supported", start)
        else:
            self.fail("unterminated regex", start)
        pattern = self.text[start + 1:self.pos - 1]
        if len(pattern.encode()) > 4096:
            self.fail("regex byte limit exceeded", start)
        flag_start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isalpha():
            self.pos += 1
        flags = self.text[flag_start:self.pos]
        if len(set(flags)) != len(flags) or set(flags) - set("ims"):
            self.fail("invalid or repeated regex flags", flag_start)
        try:
            re.compile(pattern)
        except (re.error, OverflowError) as exc:
            raise ParseError(f"invalid regex: {exc}", opening.span) from exc
        return Token("REGEX", self.text[start:self.pos], self.span(start, self.pos))
