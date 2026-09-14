"""A parser the host cannot load must not take the whole scan with it.

Grammar shared libraries are loaded when their module is imported, and some come
from ``tree-sitter-language-pack``, which downloads and extracts them on first
use. On a host where that fails, the old code surfaced a ``DownloadError``
traceback out of ``ken structural patterns`` -- for *every* language, because the
parser package imported all nineteen eagerly and because a failing file aborted
the project build instead of being reported as skipped.
"""
from __future__ import annotations


import pytest

from ken import parsers
from ken.structural import service


def test_one_unloadable_grammar_does_not_break_the_others(monkeypatch):
    import importlib

    real_import_module = importlib.import_module

    def guarded(name, *args, **kwargs):
        if name == "ken.parsers.bash":
            raise RuntimeError("Download error: cannot create cache directory")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", guarded)
    registry = parsers._load("bash", "parse_bash_file")
    with pytest.raises(RuntimeError, match="bash parser is unavailable"):
        registry(b"echo hi", "script.sh")
    # The other languages still resolve.
    assert parsers._load("python", "parse_python_file")(b"def f(): pass", "a.py")


def test_a_file_the_frontend_cannot_lower_is_reported_not_fatal(tmp_path):
    import ken.structural.service as module
    from ken.structural.frontend import lower_source

    (tmp_path / "good.py").write_text("class A:\n    def run(self):\n        return 1\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("class B:\n    pass\n", encoding="utf-8")

    def explode(content, language, path):
        if path.endswith("bad.py"):
            raise RuntimeError("grammar unavailable")
        return lower_source(content, language, path)

    original = module.lower_source
    module.lower_source = explode
    try:
        graph, analysis = service.build_project(tmp_path, path=".", cache_mb=0)
    finally:
        module.lower_source = original
    assert [s["path"] for s in analysis["skipped"]] == ["bad.py"]
    assert "grammar unavailable" in analysis["skipped"][0]["reason"]
    assert analysis["files"] == ["good.py"]
    assert analysis["coverage_complete"] is False
    # The scanned file is still in the graph: a failure is not a reason to lose
    # everything that parsed.
    assert any(entity.path == "good.py" for entity in graph.entities.values())
