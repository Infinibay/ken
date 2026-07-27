"""The vector store, tested where it can actually go wrong.

Round-tripping a vector is the easy part. What earns tests here is the
bookkeeping: slots must never be handed out twice, must come back when a row
dies through a cascade nobody wrote Python for, and a crash between the byte
write and the commit must leave a leak rather than a row pointing at nothing.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from ken import vectors
from ken.db import connect, init_schema
from ken.vectors import (
    VectorStore,
    VectorStoreError,
    allocate,
    high_water,
    immediate,
    release,
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".ken").mkdir()
    conn = connect(tmp_path / ".ken" / "ken.db")
    init_schema(conn)
    yield tmp_path, conn
    conn.close()


def _unit(seed: int, dim: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------- allocation


def test_allocate_requires_an_immediate_transaction(project):
    _root, conn = project
    # A deferred transaction is exactly the unsafe case: SQLite takes the write
    # lock at the first write, so two processes can both read the same next_slot.
    with pytest.raises(VectorStoreError, match="BEGIN IMMEDIATE"):
        allocate(conn, "ci_symbols", 4)


def test_allocate_is_monotonic_and_contiguous(project):
    _root, conn = project
    with immediate(conn):
        first = allocate(conn, "ci_symbols", 3)
        second = allocate(conn, "ci_symbols", 2)
    assert first == [0, 1, 2]
    assert second == [3, 4]
    assert high_water(conn, "ci_symbols") == 5


def test_spaces_allocate_independently(project):
    _root, conn = project
    with immediate(conn):
        syms = allocate(conn, "ci_symbols", 2)
        files = allocate(conn, "ci_files", 2)
    assert syms == [0, 1]
    assert files == [0, 1]


def test_freed_slots_are_reused_before_the_high_water_mark(project):
    _root, conn = project
    with immediate(conn):
        allocate(conn, "ci_symbols", 5)
        release(conn, "ci_symbols", [1, 3])
    with immediate(conn):
        got = allocate(conn, "ci_symbols", 3)
    # Reuse is not an optimisation here: re-indexing a file deletes and
    # re-inserts every one of its symbols, so append-only would grow without
    # bound on an actively edited repo while the live row count stayed flat.
    assert got == [1, 3, 5]
    assert high_water(conn, "ci_symbols") == 6


def test_release_is_idempotent(project):
    _root, conn = project
    with immediate(conn):
        allocate(conn, "ci_symbols", 2)
        release(conn, "ci_symbols", [0])
        release(conn, "ci_symbols", [0])
    n = conn.execute("SELECT COUNT(*) FROM ci_vec_free WHERE space='ci_symbols'").fetchone()[0]
    assert n == 1


def test_rollback_returns_the_slots(project):
    _root, conn = project
    with pytest.raises(RuntimeError):
        with immediate(conn):
            allocate(conn, "ci_symbols", 4)
            raise RuntimeError("boom")
    assert high_water(conn, "ci_symbols") == 0


def test_immediate_nests_without_committing_early(project):
    _root, conn = project
    with immediate(conn):
        allocate(conn, "ci_symbols", 1)
        with immediate(conn):  # inner block must not commit
            allocate(conn, "ci_symbols", 1)
        assert conn.in_transaction
    assert high_water(conn, "ci_symbols") == 2


# ------------------------------------------------------------------ triggers


def test_deleting_a_symbol_frees_its_slot(project):
    _root, conn = project
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at) VALUES('a.py', x'00', 0, 0)"
    )
    fid = conn.execute("SELECT id FROM ci_files").fetchone()[0]
    conn.execute(
        "INSERT INTO ci_symbols(file_id, kind, name, line_start, line_end, vec_slot) "
        "VALUES(?, 'function', 'f', 1, 2, 7)",
        (fid,),
    )
    conn.execute("DELETE FROM ci_symbols WHERE vec_slot = 7")
    freed = conn.execute(
        "SELECT slot FROM ci_vec_free WHERE space='ci_symbols'"
    ).fetchall()
    assert [r[0] for r in freed] == [7]


def test_cascade_from_a_deleted_file_frees_symbol_slots(project):
    """The case a Python-side hook would miss entirely."""
    _root, conn = project
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
        "VALUES('a.py', x'00', 0, 0, 3)"
    )
    fid = conn.execute("SELECT id FROM ci_files").fetchone()[0]
    for i, slot in enumerate((10, 11)):
        conn.execute(
            "INSERT INTO ci_symbols(file_id, kind, name, line_start, line_end, vec_slot) "
            "VALUES(?, 'function', ?, 1, 2, ?)",
            (fid, f"f{i}", slot),
        )
    conn.execute(
        "INSERT INTO ci_intent_sources(file_id, source_kind, text, updated_at, vec_slot) "
        "VALUES(?, 'module_docstring', 'doc', 0, 20)",
        (fid,),
    )
    conn.execute("DELETE FROM ci_files WHERE path = 'a.py'")

    freed = {
        (r[0], r[1]) for r in conn.execute("SELECT space, slot FROM ci_vec_free")
    }
    assert freed == {
        ("ci_files", 3),
        ("ci_symbols", 10),
        ("ci_symbols", 11),
        ("ci_intent_sources", 20),
    }


def test_vec_slot_is_unique_per_table(project):
    _root, conn = project
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
        "VALUES('a.py', x'00', 0, 0, 1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
            "VALUES('b.py', x'00', 0, 0, 1)"
        )


def test_many_rows_may_share_a_null_slot(project):
    _root, conn = project
    for name in ("a.py", "b.py"):
        conn.execute(
            "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
            "VALUES(?, x'00', 0, 0, NULL)",
            (name,),
        )
    assert conn.execute("SELECT COUNT(*) FROM ci_files").fetchone()[0] == 2


# ------------------------------------------------------------- store i/o


def test_write_then_score_recovers_the_ranking(project):
    root, _conn = project
    store = VectorStore(root, "ci_symbols", dim=8)
    vecs = np.stack([_unit(i) for i in range(5)])
    store.write([0, 1, 2, 3, 4], vecs)

    sims = store.scores(vecs[2], count=5)
    assert sims.shape == (5,)
    assert int(np.argmax(sims)) == 2
    assert sims[2] == pytest.approx(1.0, abs=1e-5)


def test_vectors_are_normalised_on_write(project):
    """So the read path can drop np.linalg.norm(matrix, axis=1) — a defensive
    full pass that measured 2.78 s against the 0.142 s matvec it guarded."""
    root, _conn = project
    store = VectorStore(root, "ci_files", dim=8)
    store.write([0], _unit(1) * 37.0)
    got = store.read([0])[0]
    assert np.linalg.norm(got) == pytest.approx(1.0, abs=1e-6)


def test_scores_are_zero_for_never_written_slots(project):
    root, _conn = project
    store = VectorStore(root, "ci_files", dim=8)
    store.write([0], _unit(1))
    sims = store.scores(_unit(1), count=4)
    assert sims[0] == pytest.approx(1.0, abs=1e-5)
    assert list(sims[1:]) == [0.0, 0.0, 0.0]


def test_sparse_slots_do_not_allocate_intervening_segments(project):
    root, _conn = project
    store = VectorStore(root, "ci_files", dim=8)
    store.segment_rows = 4  # keep the test honest without writing 64k rows
    store.write([9], _unit(3))
    assert (store.dir / "ci_files.0002.vec").is_file()
    assert not (store.dir / "ci_files.0001.vec").is_file()
    sims = store.scores(_unit(3), count=10)
    assert int(np.argmax(sims)) == 9


def test_writes_spanning_a_segment_boundary(project):
    root, _conn = project
    store = VectorStore(root, "ci_symbols", dim=8)
    store.segment_rows = 4
    vecs = np.stack([_unit(i) for i in range(6)])
    store.write([2, 3, 4, 5, 6, 7], vecs)
    for i in range(6):
        sims = store.scores(vecs[i], count=8)
        assert int(np.argmax(sims)) == i + 2


def test_reopening_sees_previously_written_vectors(project):
    root, _conn = project
    v = _unit(11)
    with VectorStore(root, "ci_symbols", dim=8) as store:
        store.write([0], v)
    with VectorStore(root, "ci_symbols", dim=8) as reopened:
        assert reopened.scores(v, count=1)[0] == pytest.approx(1.0, abs=1e-5)


def test_segment_files_are_preallocated_and_never_resized(project):
    """Growth creates a new file instead of extending a mapped one — the single
    mmap behaviour that genuinely differs across platforms."""
    root, _conn = project
    store = VectorStore(root, "ci_files", dim=8)
    store.segment_rows = 4
    store.write([0], _unit(1))
    seg = store.dir / "ci_files.0000.vec"
    size_before = seg.stat().st_size
    assert size_before == 4 * 8 * 4
    store.write([3], _unit(2))
    assert seg.stat().st_size == size_before


# --------------------------------------------------------------- mismatches


def test_dimension_mismatch_on_open_names_reembed(project):
    root, _conn = project
    VectorStore(root, "ci_symbols", dim=8)
    with pytest.raises(VectorStoreError, match="ken reembed"):
        VectorStore(root, "ci_symbols", dim=16)


def test_dimension_mismatch_on_query_names_reembed(project):
    root, _conn = project
    store = VectorStore(root, "ci_symbols", dim=8)
    with pytest.raises(VectorStoreError, match="ken reembed"):
        store.scores(np.ones(16, dtype=np.float32), count=1)


def test_slot_and_vector_counts_must_agree(project):
    root, _conn = project
    store = VectorStore(root, "ci_symbols", dim=8)
    with pytest.raises(VectorStoreError):
        store.write([0, 1], _unit(1).reshape(1, -1))


def test_corrupt_manifest_is_reported_not_ignored(project):
    root, _conn = project
    store = VectorStore(root, "ci_files", dim=8)
    store.manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(VectorStoreError, match="corrupt manifest"):
        VectorStore(root, "ci_files", dim=8)


def test_unknown_space_is_rejected(project):
    root, conn = project
    with pytest.raises(VectorStoreError, match="unknown space"):
        vectors.open_store(conn, root, "cr_findings", dim=8)


# ------------------------------------------------------------------- verify


def test_verify_is_clean_when_rows_and_slots_agree(project):
    root, conn = project
    store = VectorStore(root, "ci_files", dim=8)
    with immediate(conn):
        slots = allocate(conn, "ci_files", 2)
        store.write(slots, np.stack([_unit(1), _unit(2)]))
        for i, slot in enumerate(slots):
            conn.execute(
                "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
                "VALUES(?, x'00', 0, 0, ?)",
                (f"f{i}.py", slot),
            )
    report = store.verify(conn)
    assert report["referenced"] == 2
    assert report["leaked"] == 0
    assert report["out_of_range"] == 0
    assert report["double_booked"] == 0


def test_verify_reports_slots_leaked_by_a_crash(project):
    """A kill between the byte write and the COMMIT strands slots. That is the
    designed failure: a bounded leak, never a row pointing at unwritten bytes."""
    root, conn = project
    store = VectorStore(root, "ci_files", dim=8)
    with immediate(conn):
        allocate(conn, "ci_files", 3)  # allocated, no row ever written
    report = store.verify(conn)
    assert report["leaked"] == 3
    assert report["referenced"] == 0


# ------------------------------------------------ atomicity & concurrency


def test_two_connections_never_receive_the_same_slot(project):
    """The property the whole design rests on. ken has no application lock that
    spans its writers, so allocation borrows SQLite's."""
    root, conn = project
    other = connect(root / ".ken" / "ken.db")
    try:
        with immediate(conn):
            mine = allocate(conn, "ci_symbols", 3)
        with immediate(other):
            theirs = allocate(other, "ci_symbols", 3)
        assert set(mine).isdisjoint(theirs)
        assert sorted(mine + theirs) == list(range(6))
    finally:
        other.close()


def test_a_second_writer_is_blocked_not_interleaved(project):
    """BEGIN IMMEDIATE has to actually hold the write lock, or the disjointness
    above would be luck rather than a guarantee."""
    root, conn = project
    other = connect(root / ".ken" / "ken.db")
    other.execute("PRAGMA busy_timeout = 50")
    try:
        with immediate(conn):
            allocate(conn, "ci_symbols", 1)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
    finally:
        other.close()


def test_rolled_back_write_leaves_no_row_pointing_at_the_vector(project):
    """Atomicity as observed through the database: the bytes may survive a
    rollback, but nothing references them."""
    root, conn = project
    store = VectorStore(root, "ci_files", dim=8)
    with pytest.raises(RuntimeError):
        with immediate(conn):
            slot = allocate(conn, "ci_files", 1)[0]
            store.write([slot], _unit(5))
            conn.execute(
                "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
                "VALUES('a.py', x'00', 0, 0, ?)",
                (slot,),
            )
            raise RuntimeError("killed mid-write")
    assert conn.execute("SELECT COUNT(*) FROM ci_files").fetchone()[0] == 0
    assert high_water(conn, "ci_files") == 0


def test_uncommitted_vectors_are_scored_but_resolve_to_nothing(project):
    """A reader scanning mid-write sees the bytes — and drops them, because no
    committed row claims that slot. This is why the read path never needs a
    liveness set."""
    root, conn = project
    reader = connect(root / ".ken" / "ken.db")
    store = VectorStore(root, "ci_files", dim=8)
    v = _unit(9)
    try:
        with immediate(conn):
            slot = allocate(conn, "ci_files", 1)[0]
            store.write([slot], v)
            # Deliberately still inside the transaction.
            sims = store.scores(v, count=slot + 1)
            assert sims[slot] == pytest.approx(1.0, abs=1e-5)
            found = reader.execute(
                "SELECT 1 FROM ci_files WHERE vec_slot = ?", (slot,)
            ).fetchone()
            assert found is None
    finally:
        reader.close()


def test_flush_tolerates_a_concurrent_write(project):
    """`flush` used to iterate the dirty set directly; a writer thread adding to
    it mid-iteration raised `Set changed size during iteration`."""
    import threading

    root, _conn = project
    store = VectorStore(root, "ci_symbols", dim=8)
    store.write(list(range(64)), np.stack([_unit(i) for i in range(64)]))

    errors: list[BaseException] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            try:
                store.write([64 + (i % 64)], _unit(i))
            except BaseException as exc:  # noqa: BLE001 — the test is the assertion
                errors.append(exc)
                return
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(50):
            try:
                store.flush()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                break
    finally:
        stop.set()
        t.join(timeout=5)
    assert errors == []


def test_verify_flags_a_slot_past_the_high_water_mark(project):
    root, conn = project
    store = VectorStore(root, "ci_files", dim=8)
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, vec_slot) "
        "VALUES('a.py', x'00', 0, 0, 99)"
    )
    assert store.verify(conn)["out_of_range"] == 1


# ---------------------------------------------------------------- migration


def test_migration_moves_inline_vectors_and_reclaims_the_file(project):
    """Setting `embedding` to NULL frees pages inside the file and shrinks
    nothing; without the VACUUM a user sees no space back and reasonably
    concludes the migration did not work."""
    from ken.vectors import migrate_inline_vectors, reclaim_database

    root, conn = project
    dim = 128
    rng = np.random.default_rng(3)
    for i in range(400):
        v = rng.normal(size=dim).astype(np.float32)
        conn.execute(
            "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, embedding) "
            "VALUES(?, x'00', 0, 0, ?)",
            (f"f{i}.py", (v / np.linalg.norm(v)).tobytes()),
        )

    moved = migrate_inline_vectors(conn, root, dim=dim)
    assert moved["ci_files"] == 400
    assert conn.execute(
        "SELECT COUNT(*) FROM ci_files WHERE embedding IS NOT NULL"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM ci_files WHERE vec_slot IS NOT NULL"
    ).fetchone()[0] == 400

    before, after = reclaim_database(conn)
    assert before > 0 and after < before

    store = VectorStore(root, "ci_files", dim=dim)
    assert store.verify(conn)["leaked"] == 0
    assert store.verify(conn)["referenced"] == 400


def test_migration_preserves_the_vectors_bit_for_bit(project):
    """Only where they live changes."""
    from ken.vectors import migrate_inline_vectors

    root, conn = project
    dim = 64
    originals = {}
    for i in range(20):
        v = _unit(i, dim)
        originals[f"f{i}.py"] = v
        conn.execute(
            "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, embedding) "
            "VALUES(?, x'00', 0, 0, ?)",
            (f"f{i}.py", v.tobytes()),
        )
    migrate_inline_vectors(conn, root, dim=dim)

    store = VectorStore(root, "ci_files", dim=dim)
    for path, want in originals.items():
        slot = conn.execute(
            "SELECT vec_slot FROM ci_files WHERE path = ?", (path,)
        ).fetchone()["vec_slot"]
        assert np.allclose(store.read([int(slot)])[0], want, atol=1e-6), path


def test_migration_leaves_foreign_dimension_rows_inline(project):
    """A vector from another model must not be silently dropped — reembed is
    what fixes those, and it needs to still find them."""
    from ken.vectors import migrate_inline_vectors

    root, conn = project
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, embedding) "
        "VALUES('old.py', x'00', 0, 0, ?)",
        (_unit(1, 32).tobytes(),),
    )
    migrate_inline_vectors(conn, root, dim=64)
    row = conn.execute("SELECT embedding, vec_slot FROM ci_files").fetchone()
    assert row["embedding"] is not None
    assert row["vec_slot"] is None


def test_migration_is_idempotent(project):
    from ken.vectors import migrate_inline_vectors

    root, conn = project
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at, embedding) "
        "VALUES('a.py', x'00', 0, 0, ?)",
        (_unit(1, 64).tobytes(),),
    )
    first = migrate_inline_vectors(conn, root, dim=64)
    second = migrate_inline_vectors(conn, root, dim=64)
    assert first["ci_files"] == 1
    assert second["ci_files"] == 0
    assert high_water(conn, "ci_files") == 1
