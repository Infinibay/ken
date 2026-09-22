"""A fixed manifest is inspected once when resolving crate-relative imports."""

from ken.structural import semantic
from ken.structural.frontend import lower_source


def test_grouped_crate_imports_share_the_manifest_root(monkeypatch):
    units = [lower_source("pub struct A; pub struct B;", "rust", "src/model.rs")]
    units += [
        lower_source("use crate::model::{A, B}; fn work() {}", "rust", f"src/use{i}.rs")
        for i in range(20)
    ]
    expected = semantic.link_project(units).to_dict()
    original = semantic.posixpath.commonpath
    calls = []

    def commonpath(paths):
        calls.append(len(paths))
        return original(paths)

    monkeypatch.setattr(semantic.posixpath, "commonpath", commonpath)
    assert semantic.link_project(units).to_dict() == expected
    assert calls == [len(units)]
