"""Indexer pipeline: hash, unchanged-skip, parse, persist, delete."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.indexer import _hash, _is_unchanged, delete_file, delete_path, index_files


class _FakeEmbedder:
    """Deterministic stand-in for the real embedder. Same shape, no model load."""

    @property
    def dim(self) -> int:
        return 384

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def _vec(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text)) & 0xFFFF_FFFF)
        v = rng.normal(size=384).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)


@pytest.fixture
def project(tmp_path):
    """Project root with a real on-disk SQLite DB and the schema applied."""
    root = tmp_path
    (root / ".ken").mkdir()
    db = root / ".ken" / "ken.db"
    conn = connect(db)
    init_schema(conn)
    yield root, conn
    conn.close()


def test_hash_is_deterministic():
    h1 = _hash(b"hello world")
    h2 = _hash(b"hello world")
    h3 = _hash(b"hello mars")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 32  # blake2b-256


def test_index_files_skips_too_large(project):
    root, conn = project
    big = root / "big.py"
    big.write_bytes(b"x = 1\n" * 200_000)  # > 1 MB
    stats = index_files(conn, root, [Path("big.py")], max_file_bytes=1024)
    assert stats.skipped_too_large == 1
    assert stats.parsed == 0


def test_index_files_persists_symbols_and_imports(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text(
        '''import os
def foo():
    """Doc."""
    return 1
'''
    )
    stats = index_files(conn, root, [Path("mod.py")])
    assert stats.parsed == 1
    assert stats.symbols == 1
    assert stats.imports == 1
    rows = conn.execute("SELECT name FROM ci_symbols").fetchall()
    assert rows[0]["name"] == "foo"


def test_index_files_resolves_internal_python_import(project):
    root, conn = project
    (root / "pkg").mkdir()
    (root / "pkg" / "util.py").write_text("def helper(): return 1\n")
    (root / "main.py").write_text("import pkg.util\n")

    index_files(conn, root, [Path("pkg/util.py"), Path("main.py")])

    row = conn.execute(
        """
        SELECT f.path AS target
        FROM ci_imports i
        JOIN ci_files f ON f.id = i.to_file_id
        WHERE i.to_module = 'pkg.util'
        """
    ).fetchone()
    assert row["target"] == "pkg/util.py"


def test_index_files_resolves_ts_relative_import(project):
    root, conn = project
    (root / "src").mkdir()
    (root / "src" / "lib.ts").write_text("export function f() { return 1 }\n")
    (root / "src" / "app.ts").write_text("import { f } from './lib'\nf()\n")

    index_files(conn, root, [Path("src/lib.ts"), Path("src/app.ts")])

    row = conn.execute(
        """
        SELECT f.path AS target FROM ci_imports i
        JOIN ci_files f ON f.id = i.to_file_id
        WHERE i.to_module LIKE '%./lib%'
        """
    ).fetchone()
    assert row["target"] == "src/lib.ts"


def test_index_files_resolves_ts_esm_js_extension(project):
    # TS ESM imports source `cache.ts` as `cache.js` (nodenext convention).
    root, conn = project
    (root / "src").mkdir()
    (root / "src" / "cache.ts").write_text("export const c = 1\n")
    (root / "src" / "use.ts").write_text("import { c } from './cache.js'\n")

    index_files(conn, root, [Path("src/cache.ts"), Path("src/use.ts")])

    row = conn.execute(
        "SELECT to_file_id FROM ci_imports WHERE to_module LIKE '%cache.js%'"
    ).fetchone()
    assert row["to_file_id"] is not None


def test_index_files_resolves_relative_index_file(project):
    root, conn = project
    (root / "src" / "comp").mkdir(parents=True)
    (root / "src" / "comp" / "index.ts").write_text("export const x = 1\n")
    (root / "src" / "app.ts").write_text("import { x } from './comp'\n")

    index_files(conn, root, [Path("src/comp/index.ts"), Path("src/app.ts")])

    row = conn.execute(
        "SELECT f.path AS t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module LIKE '%./comp%'"
    ).fetchone()
    assert row["t"] == "src/comp/index.ts"


def test_index_files_resolves_tsconfig_path_alias(project):
    root, conn = project
    (root / "app" / "src" / "utils").mkdir(parents=True)
    (root / "app" / "src" / "utils" / "debug.ts").write_text("export const d = 1\n")
    (root / "app" / "src" / "main.ts").write_text("import { d } from '@/utils/debug'\n")
    (root / "app" / "tsconfig.json").write_text(
        '{\n  // jsonc comment\n  "compilerOptions": {\n'
        '    "baseUrl": ".",\n    "paths": { "@/*": ["src/*"] },\n  }\n}\n'
    )
    index_files(conn, root, [
        Path("app/src/utils/debug.ts"), Path("app/src/main.ts"), Path("app/tsconfig.json"),
    ])
    row = conn.execute(
        "SELECT f.path t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module LIKE '@/utils%'"
    ).fetchone()
    assert row["t"] == "app/src/utils/debug.ts"


def test_index_files_resolves_workspace_package(project):
    root, conn = project
    (root / "packages" / "shared" / "src").mkdir(parents=True)
    (root / "packages" / "shared" / "src" / "index.ts").write_text("export const x = 1\n")
    (root / "packages" / "shared" / "package.json").write_text('{"name": "@acme/shared"}\n')
    (root / "app" / "src").mkdir(parents=True)
    (root / "app" / "src" / "use.ts").write_text("import { x } from '@acme/shared/src/index'\n")
    index_files(conn, root, [
        Path("packages/shared/src/index.ts"), Path("packages/shared/package.json"),
        Path("app/src/use.ts"),
    ])
    row = conn.execute(
        "SELECT f.path t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module LIKE '@acme/shared%'"
    ).fetchone()
    assert row["t"] == "packages/shared/src/index.ts"


def test_index_files_resolves_java_package_import(project):
    root, conn = project
    base = root / "src" / "main" / "java" / "com" / "acme"
    base.mkdir(parents=True)
    (base / "Helper.java").write_text("package com.acme;\nclass Helper {}\n")
    (base / "App.java").write_text("package com.acme;\nimport com.acme.Helper;\nclass App {}\n")
    index_files(conn, root, [
        Path("src/main/java/com/acme/Helper.java"),
        Path("src/main/java/com/acme/App.java"),
    ])
    row = conn.execute(
        "SELECT f.path t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module = 'com.acme.Helper'"
    ).fetchone()
    assert row["t"] == "src/main/java/com/acme/Helper.java"


def test_index_files_resolves_rust_crate_path(project):
    root, conn = project
    (root / "src").mkdir()
    (root / "Cargo.toml").write_text("[package]\nname = \"demo\"\n")
    (root / "src" / "machine.rs").write_text("pub struct Machine;\n")
    (root / "src" / "lib.rs").write_text("mod machine;\nuse crate::machine::Machine;\n")
    index_files(conn, root, [
        Path("Cargo.toml"), Path("src/machine.rs"), Path("src/lib.rs"),
    ])
    row = conn.execute(
        "SELECT f.path t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module = 'crate::machine::Machine'"
    ).fetchone()
    assert row["t"] == "src/machine.rs"


def test_index_files_resolves_rust_mod_dir(project):
    root, conn = project
    (root / "src" / "commands").mkdir(parents=True)
    (root / "Cargo.toml").write_text("[package]\nname = \"d\"\n")
    (root / "src" / "commands" / "mod.rs").write_text("pub fn run() {}\n")
    (root / "src" / "lib.rs").write_text("mod commands;\nuse crate::commands;\n")
    index_files(conn, root, [
        Path("Cargo.toml"), Path("src/commands/mod.rs"), Path("src/lib.rs"),
    ])
    row = conn.execute(
        "SELECT f.path t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module = 'crate::commands'"
    ).fetchone()
    assert row["t"] == "src/commands/mod.rs"


def test_index_files_resolves_go_module_path(project):
    root, conn = project
    (root / "internal" / "store").mkdir(parents=True)
    (root / "go.mod").write_text("module github.com/acme/proj\n\ngo 1.21\n")
    (root / "internal" / "store" / "store.go").write_text("package store\nfunc New() {}\n")
    (root / "main.go").write_text(
        'package main\nimport "github.com/acme/proj/internal/store"\nfunc main(){ store.New() }\n'
    )
    index_files(conn, root, [
        Path("go.mod"), Path("internal/store/store.go"), Path("main.go"),
    ])
    row = conn.execute(
        "SELECT f.path t FROM ci_imports i JOIN ci_files f ON f.id = i.to_file_id "
        "WHERE i.to_module LIKE '%internal/store%'"
    ).fetchone()
    assert row["t"] == "internal/store/store.go"


def test_index_files_skips_unchanged_on_rerun(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")])
    stats2 = index_files(conn, root, [Path("mod.py")])
    assert stats2.unchanged == 1
    assert stats2.parsed == 0


def test_is_unchanged_requires_embedding_when_asked(project):
    """Indexed without embedder, then queried with need_embedding=True
    should return False so the daemon's warm pass picks it up."""
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")])  # no embedder → no embedding
    content_hash = _hash(src.read_bytes())
    assert _is_unchanged(conn, "mod.py", content_hash, need_embedding=False) is True
    assert _is_unchanged(conn, "mod.py", content_hash, need_embedding=True) is False


def test_index_files_with_embedder_populates_embedding(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")], embedder=_FakeEmbedder())
    row = conn.execute(
        "SELECT embedding IS NOT NULL AS has_emb FROM ci_files WHERE path = 'mod.py'"
    ).fetchone()
    assert row["has_emb"] == 1


def test_index_files_with_embedder_populates_plain_text_intent(project):
    root, conn = project
    readme = root / "README.md"
    readme.write_text(
        """# Ken

Install from a local checkout with uv tool install --editable.
""",
        encoding="utf-8",
    )

    index_files(conn, root, [Path("README.md")], embedder=_FakeEmbedder())

    row = conn.execute(
        "SELECT embedding IS NOT NULL AS has_emb FROM ci_files WHERE path = 'README.md'"
    ).fetchone()
    assert row["has_emb"] == 1
    intent = conn.execute(
        """
        SELECT source_kind, text, weight, embedding IS NOT NULL AS has_embedding
        FROM ci_intent_sources
        """
    ).fetchone()
    assert intent["source_kind"] == "plain_text"
    assert "local checkout" in intent["text"]
    assert intent["weight"] == pytest.approx(0.55)
    assert intent["has_embedding"] == 1


def test_index_files_persists_docstring_intent_sources(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text(
        '''"""Module role for auth sessions."""

def login():
    """Authenticate a user session."""
    return 1
'''
    )
    index_files(conn, root, [Path("mod.py")], embedder=_FakeEmbedder())

    rows = conn.execute(
        """
        SELECT source_kind, text, embedding IS NOT NULL AS has_embedding,
               symbol_id IS NOT NULL AS is_symbol
        FROM ci_intent_sources
        ORDER BY source_kind
        """
    ).fetchall()

    assert [
        (row["source_kind"], row["text"], row["has_embedding"], row["is_symbol"])
        for row in rows
    ] == [
        ("module_docstring", "Module role for auth sessions.", 1, 0),
        ("symbol_docstring", "Authenticate a user session.", 1, 1),
    ]


def test_delete_file_cascades_to_symbols(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")])
    assert delete_file(conn, "mod.py") is True
    sym_count = conn.execute("SELECT COUNT(*) FROM ci_symbols").fetchone()[0]
    assert sym_count == 0


def test_delete_file_returns_false_when_missing(project):
    _, conn = project
    assert delete_file(conn, "nope.py") is False


def test_delete_path_removes_indexed_subtree(project):
    root, conn = project
    kept = root / "pkg_extra.py"
    wildcard_neighbor = root / "pkgA" / "nested.py"
    nested = root / "pkg" / "nested.py"
    nested.parent.mkdir()
    wildcard_neighbor.parent.mkdir()
    kept.write_text("def kept(): return 1\n")
    wildcard_neighbor.write_text("def neighbor(): return 3\n")
    nested.write_text("def nested(): return 2\n")
    index_files(
        conn,
        root,
        [Path("pkg_extra.py"), Path("pkgA/nested.py"), Path("pkg/nested.py")],
    )

    assert delete_path(conn, "pkg") == 1

    rows = conn.execute("SELECT path FROM ci_files ORDER BY path").fetchall()
    assert [row["path"] for row in rows] == ["pkgA/nested.py", "pkg_extra.py"]


# ---------------------------------------------------------------------------
# Import resolution for languages added via tree-sitter-language-pack:
# Ruby require_relative, C++ quoted #include, Kotlin package, PHP PSR-4.
# ---------------------------------------------------------------------------


def _target_of(conn, module_like: str) -> str | None:
    row = conn.execute(
        """
        SELECT f.path AS target FROM ci_imports i
        JOIN ci_files f ON f.id = i.to_file_id
        WHERE i.to_module LIKE ?
        """,
        (module_like,),
    ).fetchone()
    return row["target"] if row else None


def test_resolves_ruby_require_relative(project):
    root, conn = project
    (root / "lib").mkdir()
    (root / "lib" / "util.rb").write_text("def helper; end\n")
    (root / "app.rb").write_text('require_relative "lib/util"\n')

    index_files(conn, root, [Path("lib/util.rb"), Path("app.rb")])

    assert _target_of(conn, "%lib/util%") == "lib/util.rb"


def test_resolves_cpp_quoted_include(project):
    root, conn = project
    (root / "inc").mkdir()
    (root / "inc" / "helper.hpp").write_text("int helper();\n")
    (root / "main.cpp").write_text('#include "inc/helper.hpp"\n#include <vector>\n')

    index_files(conn, root, [Path("inc/helper.hpp"), Path("main.cpp")])

    assert _target_of(conn, '%helper.hpp%') == "inc/helper.hpp"
    # the angle-bracket system header stays external (unresolved to a file)
    row = conn.execute(
        "SELECT resolution FROM ci_imports WHERE to_module = 'vector'"
    ).fetchone()
    assert row["resolution"] == "external"


def test_resolves_kotlin_package_import(project):
    root, conn = project
    (root / "com" / "foo").mkdir(parents=True)
    (root / "com" / "foo" / "models.kt").write_text(
        "package com.foo\nclass Baz\n"
    )
    (root / "com" / "app.kt").write_text(
        "package com\nimport com.foo.Baz\nfun use() {}\n"
    )

    index_files(conn, root, [Path("com/foo/models.kt"), Path("com/app.kt")])

    assert _target_of(conn, "com.foo.Baz") == "com/foo/models.kt"


def test_resolves_php_psr4_import(project):
    root, conn = project
    (root / "composer.json").write_text(
        '{"autoload": {"psr-4": {"App\\\\": "src/"}}}'
    )
    (root / "src" / "Models").mkdir(parents=True)
    (root / "src" / "Models" / "User.php").write_text(
        "<?php\nnamespace App\\Models;\nclass User {}\n"
    )
    (root / "src" / "Service.php").write_text(
        "<?php\nnamespace App;\nuse App\\Models\\User;\nclass Service {}\n"
    )

    index_files(
        conn, root, [Path("src/Models/User.php"), Path("src/Service.php")]
    )

    assert _target_of(conn, "App\\Models\\User") == "src/Models/User.php"


def test_resolves_rust_super_glob_to_own_file(project):
    root, conn = project
    (root / "src").mkdir()
    # An inline test module's `use super::*;` refers to the file's own module.
    (root / "src" / "calc.rs").write_text(
        "pub fn add() {}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n}\n"
    )
    (root / "src" / "lib.rs").write_text("pub mod calc;\n")
    (root / "Cargo.toml").write_text("[package]\nname = \"demo\"\n")

    index_files(conn, root, [Path("src/calc.rs"), Path("src/lib.rs")])

    row = conn.execute(
        """
        SELECT f.path AS target, i.resolution FROM ci_imports i
        JOIN ci_files f ON f.id = i.to_file_id
        WHERE i.to_module LIKE 'super::%'
        """
    ).fetchone()
    assert row["target"] == "src/calc.rs"
    assert row["resolution"] == "internal"
