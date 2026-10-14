"""Classify code purpose from source conventions and structural annotations."""
from __future__ import annotations

import re
from pathlib import PurePosixPath


def classify_role(path: str, name: str | None = None, annotations: tuple[str, ...] = ()) -> str:
    file = PurePosixPath(path)
    parts = {p.lower() for p in file.parts}
    stem = file.stem.lower()
    rust_test = any(re.fullmatch(r"#\[\s*(?:test|cfg\(\s*test\s*\))\s*\]", a.strip())
                    for a in annotations)
    if (parts & {"tests", "test", "__tests__", "spec", "specs"}
            or stem.startswith("test_") or (name or "").rsplit(".", 1)[-1].startswith("test_")
            or file.name.endswith("_test.go")
            or re.search(r"\.(?:test|spec)\.(?:[cm]?[jt]sx?)$", file.name, re.IGNORECASE)
            or rust_test):
        return "test"
    if parts & {"examples", "example", "demo", "demos"}:
        return "example"
    if parts & {"docs", "doc", "documentation"} or file.suffix.lower() in {".md", ".rst", ".txt"}:
        return "documentation"
    return "definition"
