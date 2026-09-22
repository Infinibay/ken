"""The storage experiment preserves syntax, candidate scope and replacements."""

import sqlite3

import numpy as np
import pytest

pytest.importorskip("flatbuffers")

from examples.bench.ast_storage.codec import (
    Dictionary,
    decode_flat,
    decode_packed,
    encode_flat,
    encode_packed,
    flatten,
)
from examples.bench.ast_storage.experiment import create, run_query, write_unit
from examples.bench.ast_storage.matching import QUERIES, Matcher, oracle
from ken.structural.frontend import parser_for

SOURCES = [
    ("python", "x.py", b'if x == 3:\n pass\nif x != "a":\n pass\n'),
    ("python", "x.py", b"if (x == 3):\n pass\nif x == y:\n pass\nif 3 == x:\n pass\n"),
    ("python", "x.py", b"if x == 3 < 4:\n pass\nif x := 3:\n pass\n"),
    ("python", "x.py", b"def outer():\n if x: pass\n def inner():\n  return f()\n"),
    ("python", "x.py", b"def f():\n if x:\n  pass\n return g()\n"),
    ("python", "x.py", b"if x == :\n pass\n"),
    ("python", "x.py", b'# unicode \xc3\xb1\nif x != "\xc3\xb1":\n pass\n'),
    ("python", "x.py", b""),
    ("rust", "x.rs", b"fn f(x:i32) { if x == 3 { return g(); } if x != 4 {} }"),
    ("rust", "x.rs", b"fn f() { if x { } fn inner() { return g(); } }"),
    ("typescript", "x.ts", b"function f(x:number) { if (x /*c*/ == 3) return g(); }"),
    ("typescript", "x.ts", b'if (x === 3) {} if (x != "a") {} if (x = 3) {}'),
]


@pytest.mark.parametrize("language,path,source", SOURCES)
def test_layouts_and_indexed_detectors_equal_tree_sitter(
    tmp_path, language, path, source
):
    tree = parser_for(language, path).parse(source)
    dictionary = Dictionary()
    columns = flatten(tree, dictionary)
    for encode, decode in ((encode_flat, decode_flat), (encode_packed, decode_packed)):
        buffer = encode(columns)
        restored = decode(buffer)
        for before, after in zip(columns, restored):
            np.testing.assert_array_equal(before, after)
            assert not after.flags.writeable
    matcher = Matcher(dictionary.words)
    expected = oracle(tree)
    for backend in (
        "sqlite",
        "packed",
        "flatbuffers",
        "packed_grouped",
        "flatbuffers_grouped",
    ):
        file = tmp_path / f"{backend}.sqlite"
        with sqlite3.connect(file) as db:
            create(db, backend)
            write_unit(db, backend, 0, path, language, source, columns)
        for query in QUERIES:
            matches, _ = run_query(file, backend, query, matcher)
            assert sorted((start, end) for _, start, end in matches) == sorted(
                expected[query]
            )
            if backend == "flatbuffers":
                scalar, _ = run_query(file, "flatbuffers_scalar", query, matcher)
                assert scalar == matches


def test_scope_closure_does_not_combine_different_methods(tmp_path):
    source = b"def a():\n if x: pass\ndef b():\n return f()\n"
    tree = parser_for("python", "a.py").parse(source)
    assert oracle(tree)["function_branch_return"] == []
    # A nested method's return is not the enclosing method's return.
    nested = parser_for("python", "a.py").parse(SOURCES[3][2])
    assert oracle(nested)["function_branch_return"] == []


@pytest.mark.parametrize(
    "backend",
    ("sqlite", "packed", "flatbuffers", "packed_grouped", "flatbuffers_grouped"),
)
def test_growing_file_replaces_candidates_atomically(tmp_path, backend):
    dictionary = Dictionary()
    path = tmp_path / "cache.sqlite"
    original = b"if x == 1:\n pass\n"
    changed = b"if x == y:\n pass\nif x != 99:\n pass\nif y == 7:\n pass\n"

    def columns(source):
        return flatten(parser_for("python", "a.py").parse(source), dictionary)

    with sqlite3.connect(path) as db:
        create(db, backend)
        for unit in (0, 1):
            write_unit(db, backend, unit, "a.py", "python", original, columns(original))
    with sqlite3.connect(path) as db:
        write_unit(
            db, backend, 0, "a.py", "python", changed, columns(changed), replace=True
        )
        db.rollback()
    matcher = Matcher(dictionary.words)
    before, _ = run_query(path, backend, "if_literal", matcher)
    assert len(before) == 2
    with sqlite3.connect(path) as db:
        write_unit(
            db, backend, 0, "a.py", "python", changed, columns(changed), replace=True
        )
    after, _ = run_query(path, backend, "if_literal", matcher)
    assert [(u, a, b) for u, a, b in before if u == 1] == [
        (u, a, b) for u, a, b in after if u == 1
    ]
    assert [(a, b) for u, a, b in after if u == 0] == oracle(
        parser_for("python", "a.py").parse(changed)
    )["if_literal"]
    assert len(after) == 3
