"""Dense vectors on disk, mapped into memory instead of read through SQLite.

Profiled on a 771 563-symbol index (Linux 7.1-rc2), a single `ken rank` spent
20.4 s in the fuzzy channel to do **0.138 s** of actual arithmetic. The cost was
never the database: SQLite hands over the BLOB column at 906 MB/s, within 1.7x of
a raw flat-file read. The cost was materialising 771 563 Python ``Row`` objects
and 2.9 GB of per-row ``np.frombuffer`` calls to feed one matrix-vector product.

So the vectors move out of the relational store and into files that are mapped,
not read. A query becomes ``matrix @ q`` over pages the kernel already has
resident. The relational half — paths, names, line numbers, the graph — stays in
SQLite, where it was never the problem and where it costs 0.51 GB against the
4.10 GB the vectors occupied.

## Why segments

Each space is a series of fixed-capacity segment files, preallocated at creation
and **never resized**. Growth means creating the next segment, never extending a
file that another process may have mapped — the one mmap behaviour that genuinely
differs across platforms. ``open(path, "xb")`` makes segment creation atomic, so
two processes racing to grow the same space cannot corrupt each other; the loser
simply finds the file already there.

## Why allocation lives in SQLite

There is no application-level lock that spans ken's writers. The daemon's
``IndexQueue`` writes through its own connection without taking
``DaemonState.lock``; ``ken install`` and ``ken reembed`` open their own
connections with no daemon awareness. The only arbiter today is WAL plus
``busy_timeout``.

Rather than invent a second, weaker lock, slot allocation is a row in SQLite
(:data:`ALLOC_TABLE` / :data:`FREE_TABLE`) and therefore inherits that
serialisation for free. Once a writer owns a slot, it owns it exclusively, so the
actual byte writes go to disjoint offsets and need no coordination at all.

The caller must hold ``BEGIN IMMEDIATE`` across allocate-then-commit. A deferred
transaction — what ``with conn:`` gives — would let another process hand out the
same slot before the commit lands. :func:`allocate` enforces this rather than
trusting callers to remember.

## Ordering, and what a crash can leave behind

    BEGIN IMMEDIATE
      allocate slots        (SQLite)
      write vectors, flush  (files)
      INSERT rows.vec_slot
    COMMIT

Bytes are durable before any row points at them. A crash anywhere leaves slots
that are allocated but referenced by nothing — a bounded leak that
:func:`VectorStore.verify` reports and ``ken vectors compact`` reclaims. The
reverse order would leave rows pointing at unwritten bytes, which is unfixable.

## What this guarantees, and what it does not

**Atomic** — as observed through the database, yes. A row and its vector become
visible together, because the bytes are written before the transaction that
names them commits. There is no state in which a committed row points at a slot
that was never written. What is *not* atomic is reclamation: a rollback or a kill
strands the allocated slot rather than returning it.

**Consistent** — enforced, not assumed. A partial unique index makes two rows
sharing a slot impossible; the ``AFTER DELETE`` triggers keep the free list in
step with every deletion path including cascades.

**Isolated** — for writers, fully: ``BEGIN IMMEDIATE`` means SQLite hands out
each slot to exactly one transaction, across threads and across processes.

For readers, *not* serializable, deliberately. Scoring reads the mapped bytes
outside any transaction, so a scan concurrent with a re-index can observe a slot
that was freed and immediately reallocated, and pair a stale similarity with the
row that now owns it. The bound on that is what makes it acceptable: the result
is one row carrying a wrong score, never a dangling path and never a crash, and
it requires the same file to be re-indexed inside the millisecond between the
scan and the resolve. Slots written but not yet committed are handled properly —
they resolve to no row and are dropped. Closing the remaining gap would mean
versioning every slot to pay for an anomaly that costs one misranked entry.

**Durable** — to the same degree as the database, on purpose. See
:meth:`VectorStore.write`.

## Threads

A :class:`VectorStore` instance is safe to share: the map cache and the dirty set
are guarded by a lock, and the read path builds its own instance per call anyway.
:class:`immediate` is *not* reentrant across threads sharing one connection — it
counts nesting depth per connection, not per thread. That matches how ken
actually runs: the daemon serialises its shared connection behind
``DaemonState.lock`` and gives its indexer a connection of its own.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FORMAT_VERSION = 1

#: Rows per segment file. 65 536 x 1024 x 4 B = 256 MB — big enough that a large
#: index is a handful of files, small enough that a mostly-empty space costs
#: little and that a corrupt segment loses a bounded amount of work.
SEGMENT_ROWS = 65_536

ALLOC_TABLE = "ci_vec_alloc"
FREE_TABLE = "ci_vec_free"

#: The three spaces that carry real volume. ``cr_contexts`` and ``cr_findings``
#: stay in SQLite on purpose: the first is capped at 50 rows by its own query,
#: the second holds tens. Both measured 0.00 s, so moving them would add risk and
#: buy nothing.
SPACES: dict[str, str] = {
    "ci_files": "ci_files",
    "ci_symbols": "ci_symbols",
    "ci_intent_sources": "ci_intent_sources",
}

_DTYPES = {"float32": np.float32}


class VectorStoreError(RuntimeError):
    """The store is unusable for this query — wrong dim, wrong model, corrupt."""


@dataclass(frozen=True)
class Manifest:
    """What a space is, on disk. Small enough to re-read on every open."""

    format: int
    space: str
    dim: int
    dtype: str
    model: str | None
    segment_rows: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": self.format,
                "space": self.space,
                "dim": self.dim,
                "dtype": self.dtype,
                "model": self.model,
                "segment_rows": self.segment_rows,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> Manifest:
        d = json.loads(raw)
        return cls(
            format=int(d["format"]),
            space=str(d["space"]),
            dim=int(d["dim"]),
            dtype=str(d.get("dtype", "float32")),
            model=d.get("model"),
            segment_rows=int(d.get("segment_rows", SEGMENT_ROWS)),
        )


def vectors_dir(project_root: Path) -> Path:
    from ken import _paths

    return _paths.ken_dir(project_root) / "vectors"


def _atomic_write(path: Path, text: str) -> None:
    """Replace *path* without ever exposing a half-written manifest.

    A reader that catches the file mid-write would see truncated JSON and treat
    the whole space as corrupt, so the new content lands under a temp name in the
    same directory and is renamed over — atomic on every filesystem ken runs on.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


#: Which connections currently hold a ``BEGIN IMMEDIATE`` opened by
#: :class:`immediate`, keyed by identity.
#:
#: ``sqlite3.Connection`` is an immutable C type — it accepts neither attributes
#: nor weak references — so the flag cannot live on the object and cannot be held
#: weakly. The value keeps a *strong* reference to the connection, which is what
#: makes keying on ``id()`` sound: a tracked connection can never be collected,
#: so its id can never be recycled underneath us. ``__exit__`` always drops the
#: entry, so nothing outlives its ``with`` block.
_IMMEDIATE: dict[int, tuple[sqlite3.Connection, int]] = {}


def in_immediate_transaction(conn: sqlite3.Connection) -> bool:
    """Is this connection inside a write transaction it acquired up front?

    ``Connection.in_transaction`` cannot answer this: it is True for a deferred
    transaction too, and the deferred case is exactly the unsafe one. SQLite
    exposes no way to ask "do you hold the write lock", so the answer comes from
    :class:`immediate`, the only sanctioned way to take it.
    """
    entry = _IMMEDIATE.get(id(conn))
    return entry is not None and entry[0] is conn


class immediate:
    """``BEGIN IMMEDIATE`` as a context manager, nestable and honest.

    ``with conn:`` opens a *deferred* transaction — SQLite takes the write lock
    only at the first write, so two processes can both be inside one and both
    read the same ``next_slot``. Every path that allocates a slot must hold the
    write lock from the start.

    Nesting is a no-op rather than an error because the indexer writes a file and
    its symbols through helpers that each want the guarantee but must land in a
    single transaction. Only the outermost block commits.

    Not reentrant across threads sharing one connection. The daemon already
    serialises those behind ``DaemonState.lock``, and its indexer runs on a
    connection of its own.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._outermost = False

    def __enter__(self) -> sqlite3.Connection:
        key = id(self.conn)
        entry = _IMMEDIATE.get(key)
        if entry is not None and entry[0] is self.conn:
            _IMMEDIATE[key] = (self.conn, entry[1] + 1)
            return self.conn
        self.conn.execute("BEGIN IMMEDIATE")
        _IMMEDIATE[key] = (self.conn, 1)
        self._outermost = True
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        key = id(self.conn)
        entry = _IMMEDIATE.get(key)
        if entry is not None and entry[1] > 1:
            _IMMEDIATE[key] = (self.conn, entry[1] - 1)
            return False
        if not self._outermost:
            return False
        _IMMEDIATE.pop(key, None)
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


def allocate(conn: sqlite3.Connection, space: str, count: int) -> list[int]:
    """Reserve *count* slots in *space*, reusing freed ones first.

    Must be called inside :class:`immediate`. Reuse matters more than it looks:
    every content change re-indexes a file by deleting and re-inserting all of
    its symbols, so on an actively edited repo an append-only store would grow
    without bound while the live row count stayed flat.
    """
    if count <= 0:
        return []
    if not in_immediate_transaction(conn):
        raise VectorStoreError(
            "allocate() requires BEGIN IMMEDIATE — a deferred transaction lets "
            "another process hand out the same slot before this one commits; "
            "wrap the call in ken.vectors.immediate(conn)"
        )
    rows = conn.execute(
        f"SELECT slot FROM {FREE_TABLE} WHERE space = ? ORDER BY slot LIMIT ?",
        (space, count),
    ).fetchall()
    reused = [int(r[0]) for r in rows]
    if reused:
        conn.executemany(
            f"DELETE FROM {FREE_TABLE} WHERE space = ? AND slot = ?",
            [(space, s) for s in reused],
        )
    remaining = count - len(reused)
    if remaining <= 0:
        return reused

    row = conn.execute(
        f"SELECT next_slot FROM {ALLOC_TABLE} WHERE space = ?", (space,)
    ).fetchone()
    start = int(row[0]) if row else 0
    fresh = list(range(start, start + remaining))
    conn.execute(
        f"INSERT INTO {ALLOC_TABLE}(space, next_slot) VALUES(?, ?) "
        f"ON CONFLICT(space) DO UPDATE SET next_slot = excluded.next_slot",
        (space, start + remaining),
    )
    return reused + fresh


def release(conn: sqlite3.Connection, space: str, slots: list[int]) -> None:
    """Return slots to the free list. Idempotent.

    Rarely needed directly: the ``AFTER DELETE`` triggers in ``schema.sql`` do
    this automatically, which is the only way to catch rows removed by
    ``ON DELETE CASCADE`` when a file row goes away.
    """
    if not slots:
        return
    conn.executemany(
        f"INSERT OR IGNORE INTO {FREE_TABLE}(space, slot) VALUES(?, ?)",
        [(space, int(s)) for s in slots],
    )


def high_water(conn: sqlite3.Connection, space: str) -> int:
    row = conn.execute(
        f"SELECT next_slot FROM {ALLOC_TABLE} WHERE space = ?", (space,)
    ).fetchone()
    return int(row[0]) if row else 0


class VectorStore:
    """One space's vectors: segment files plus a manifest, mapped read-only.

    Cheap to construct and safe to keep around — segments are mapped lazily and
    the map is rebuilt only when the space grows past what is already mapped.
    """

    def __init__(self, root: Path, space: str, *, dim: int, model: str | None = None,
                 dtype: str = "float32"):
        if dtype not in _DTYPES:
            raise VectorStoreError(f"unsupported dtype {dtype!r}")
        self.root = Path(root)
        self.space = space
        self.dir = vectors_dir(self.root)
        self.dtype = dtype
        self.np_dtype = _DTYPES[dtype]
        self.itemsize = int(np.dtype(self.np_dtype).itemsize)
        self._maps: dict[int, np.ndarray] = {}
        self._dirty: set[int] = set()
        self._lock = threading.Lock()
        self._manifest = self._load_or_create(dim=dim, model=model)
        self.dim = self._manifest.dim
        self.segment_rows = self._manifest.segment_rows

    # ---------------------------------------------------------------- manifest

    @property
    def manifest_path(self) -> Path:
        return self.dir / f"{self.space}.json"

    def _load_or_create(self, *, dim: int, model: str | None) -> Manifest:
        p = self.manifest_path
        if p.is_file():
            try:
                man = Manifest.from_json(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise VectorStoreError(f"corrupt manifest {p}: {exc}") from exc
            if man.format != FORMAT_VERSION:
                raise VectorStoreError(
                    f"{p} is format {man.format}, this ken speaks {FORMAT_VERSION}"
                )
            if man.dim != dim:
                raise VectorStoreError(
                    f"stored vectors are {man.dim}-dimensional but the live embedder "
                    f"produces {dim} — the index was built with a different model; "
                    "run `ken reembed`"
                )
            return man
        man = Manifest(
            format=FORMAT_VERSION,
            space=self.space,
            dim=int(dim),
            dtype=self.dtype,
            model=model,
            segment_rows=SEGMENT_ROWS,
        )
        _atomic_write(p, man.to_json())
        return man

    # ---------------------------------------------------------------- segments

    def _segment_path(self, index: int) -> Path:
        return self.dir / f"{self.space}.{index:04d}.vec"

    def _segment_bytes(self) -> int:
        return self.segment_rows * self.dim * self.itemsize

    def _ensure_segment(self, index: int) -> Path:
        """Create segment *index* at full size if it does not exist yet.

        ``"xb"`` is the whole concurrency story: exactly one racer creates the
        file, everyone else gets ``FileExistsError`` and moves on. The file is
        sized once here and never grows, so a reader's mapping stays valid no
        matter how much the space fills afterwards.
        """
        p = self._segment_path(index)
        if p.is_file():
            return p
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "xb") as fh:
                fh.truncate(self._segment_bytes())
                os.fsync(fh.fileno())
        except FileExistsError:
            pass
        return p

    def _map(self, index: int) -> np.ndarray | None:
        """Read-only view of one segment, or None if it was never created."""
        cached = self._maps.get(index)
        if cached is not None:
            return cached
        p = self._segment_path(index)
        if not p.is_file():
            return None
        mm = np.memmap(p, dtype=self.np_dtype, mode="r",
                       shape=(self.segment_rows, self.dim))
        self._maps[index] = mm
        return mm

    def close(self) -> None:
        self.flush()
        self._maps.clear()

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    # ------------------------------------------------------------------ writes

    def write(self, slots: list[int], vectors: np.ndarray, *, durable: bool = False) -> None:
        """Write *vectors* at *slots*, before any row is made to reference them.

        Vectors are L2-normalised here rather than at read time. That is what
        lets the read path drop ``np.linalg.norm(matrix, axis=1)``, a defensive
        full pass that measured 2.78 s against the 0.142 s matvec it guarded —
        19.6x the cost of the thing it was protecting.

        ``durable`` is off by default, and deliberately so. The database these
        vectors accompany runs ``PRAGMA synchronous = NORMAL``, which does not
        fsync on commit either; syncing here per file would make the sidecar
        strictly more durable than the index it belongs to while costing an
        fsync per file — 65 907 of them on a kernel-sized install. The ordering
        that actually matters holds regardless: the bytes reach the page cache
        before the row that points at them is committed, so a process crash
        loses nothing. Machine-level power loss is the case both layers decline
        to insure against, together. :meth:`flush` forces the issue where it is
        worth paying for, at the end of a chunk.
        """
        if len(slots) == 0:
            return
        arr = np.ascontiguousarray(vectors, dtype=self.np_dtype)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.shape[0] != len(slots):
            raise VectorStoreError(
                f"{len(slots)} slots but {arr.shape[0]} vectors"
            )
        if arr.shape[1] != self.dim:
            raise VectorStoreError(
                f"vectors are {arr.shape[1]}-dimensional, store is {self.dim}"
            )
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        arr = arr / np.maximum(norms, 1e-12)

        row_bytes = self.dim * self.itemsize
        # Group by segment so each file is opened and fsynced once even when a
        # chunk of symbols straddles a boundary.
        by_segment: dict[int, list[tuple[int, int]]] = {}
        for i, slot in enumerate(slots):
            by_segment.setdefault(int(slot) // self.segment_rows, []).append(
                (int(slot) % self.segment_rows, i)
            )
        for seg, entries in by_segment.items():
            path = self._ensure_segment(seg)
            fd = os.open(path, os.O_WRONLY)
            try:
                for offset_row, src in sorted(entries):
                    os.pwrite(fd, arr[src].tobytes(), offset_row * row_bytes)
                if durable:
                    os.fsync(fd)
            finally:
                os.close(fd)
            with self._lock:
                self._dirty.add(seg)
                # A segment mapped before this write may predate the file's
                # creation; drop it so the next read re-maps and sees the new
                # bytes.
                self._maps.pop(seg, None)

    def flush(self) -> None:
        """fsync every segment touched since the last flush.

        The dirty set is swapped out under the lock before iterating: a writer
        thread calling ``write`` mid-flush would otherwise mutate the set being
        iterated and raise ``RuntimeError: Set changed size during iteration``.
        """
        with self._lock:
            dirty, self._dirty = self._dirty, set()
        for seg in sorted(dirty):
            path = self._segment_path(seg)
            if not path.is_file():
                continue
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    # ------------------------------------------------------------------- reads

    def scores(self, query: np.ndarray, *, count: int) -> np.ndarray:
        """Cosine of *query* against slots ``[0, count)``. The hot path.

        Returns a dense array indexed by slot, including slots whose row has been
        deleted — scoring a stale vector costs a few FLOPs, and dropping it needs
        a liveness set that would cost far more than it saves. Dead slots simply
        fail to resolve back to a row, which the caller already handles.
        """
        if count <= 0:
            return np.zeros((0,), dtype=np.float32)
        q = np.ascontiguousarray(query, dtype=np.float32).reshape(-1)
        if q.shape[0] != self.dim:
            raise VectorStoreError(
                f"query is {q.shape[0]}-dimensional but stored vectors are {self.dim} — "
                "the index was built with a different model; run `ken reembed`"
            )
        q = q / max(float(np.linalg.norm(q)), 1e-12)

        out = np.zeros((count,), dtype=np.float32)
        for seg in range((count + self.segment_rows - 1) // self.segment_rows):
            mm = self._map(seg)
            lo = seg * self.segment_rows
            hi = min(lo + self.segment_rows, count)
            if mm is None:
                continue  # never-created segment: leave zeros
            out[lo:hi] = mm[: hi - lo] @ q
        return out

    def read(self, slots: list[int]) -> np.ndarray:
        """Fetch specific vectors. For reembed and verification, not for ranking."""
        out = np.zeros((len(slots), self.dim), dtype=self.np_dtype)
        for i, slot in enumerate(slots):
            mm = self._map(int(slot) // self.segment_rows)
            if mm is not None:
                out[i] = mm[int(slot) % self.segment_rows]
        return out

    # ------------------------------------------------------------ housekeeping

    def verify(self, conn: sqlite3.Connection) -> dict[str, int]:
        """Cross-check the store against the DB. Powers ``ken vectors verify``.

        ``leaked`` counts slots below the high-water mark that neither a row nor
        the free list claims — the residue a crash between the byte write and the
        commit leaves behind.
        """
        table = SPACES[self.space]
        hw = high_water(conn, self.space)
        referenced = {
            int(r[0])
            for r in conn.execute(
                f"SELECT vec_slot FROM {table} WHERE vec_slot IS NOT NULL"
            )
        }
        freed = {
            int(r[0])
            for r in conn.execute(
                f"SELECT slot FROM {FREE_TABLE} WHERE space = ?", (self.space,)
            )
        }
        out_of_range = sum(1 for s in referenced if s < 0 or s >= hw)
        overlap = len(referenced & freed)
        leaked = hw - len(referenced) - len(freed) + overlap
        return {
            "high_water": hw,
            "referenced": len(referenced),
            "free": len(freed),
            "leaked": max(0, leaked),
            "out_of_range": out_of_range,
            "double_booked": overlap,
            "segments": sum(
                1 for i in range((hw + self.segment_rows - 1) // self.segment_rows)
                if self._segment_path(i).is_file()
            ),
        }

    def bytes_on_disk(self) -> int:
        """Blocks actually allocated, not the apparent size.

        Segments are preallocated to full capacity and written sparsely, so a
        space holding 4 180 vectors reports 256 MB of apparent size against 17 MB
        of real blocks. Reporting the former would make `ken vectors status` look
        alarming about disk that was never taken.
        """
        total = 0
        for p in self.dir.glob(f"{self.space}.*.vec"):
            try:
                st = p.stat()
                blocks = getattr(st, "st_blocks", None)
                total += blocks * 512 if blocks is not None else st.st_size
            except OSError:
                pass
        return total


def open_store(
    conn: sqlite3.Connection,
    project_root: Path,
    space: str,
    *,
    dim: int,
    model: str | None = None,
) -> VectorStore:
    """Open *space* for a project, or raise :class:`VectorStoreError`.

    Callers on a hook path should catch and fall back to the SQLite BLOB column:
    a missing or mismatched store must degrade to slow, never to broken.
    """
    if space not in SPACES:
        raise VectorStoreError(f"unknown space {space!r}")
    return VectorStore(project_root, space, dim=dim, model=model)


def project_root_for(conn: sqlite3.Connection) -> Path | None:
    """Recover a project root from the connection's own file.

    The ranker channels take a connection and a query vector and nothing else;
    threading a project root through every one of them would touch a dozen
    signatures to deliver a fact the connection already knows. An in-memory
    database — every ranker unit test — has no file, returns None, and falls
    back to the inline column, which is exactly the behaviour those tests want.
    """
    try:
        for _seq, name, filename in conn.execute("PRAGMA database_list"):
            if name == "main" and filename:
                db = Path(filename)
                if db.parent.name == "\x2eken":
                    return db.parent.parent
                return db.parent
    except sqlite3.Error:
        return None
    return None


def migrate_inline_vectors(
    conn: sqlite3.Connection,
    project_root: Path,
    *,
    dim: int,
    model: str | None = None,
    batch: int = 2000,
    progress=None,
) -> dict[str, int]:
    """Move vectors out of the `embedding` columns and into the mapped store.

    The one-time upgrade for an index built before the store existed. Runs in
    batches rather than one transaction: on a kernel-sized index it moves 3.6 GB,
    and holding SQLite's write lock for that would fail every hook in the daemon
    rather than merely delay it. A batch is atomic, so an interrupted run leaves
    a partly-converted index — which still answers correctly, because every read
    path falls back to the inline column for rows that have no slot yet.

    Rows keep their vectors bit-for-bit; only where they live changes.
    """
    say = progress or (lambda _m: None)
    moved: dict[str, int] = {}
    for space, table in SPACES.items():
        store = VectorStore(project_root, space, dim=dim, model=model)
        count = 0
        try:
            while True:
                rows = conn.execute(
                    f"SELECT id, embedding FROM {table} "
                    f"WHERE embedding IS NOT NULL AND vec_slot IS NULL LIMIT ?",
                    (batch,),
                ).fetchall()
                if not rows:
                    break
                mats, ids = [], []
                for r in rows:
                    vec = np.frombuffer(bytes(r["embedding"]), dtype=np.float32)
                    if vec.shape[0] != dim:
                        # Written by a different model. Leave it inline and let
                        # `ken reembed` deal with it; silently dropping vectors
                        # here would be worse than a slow channel.
                        continue
                    mats.append(vec)
                    ids.append(int(r["id"]))
                if not ids:
                    break
                with immediate(conn):
                    slots = allocate(conn, space, len(ids))
                    store.write(slots, np.stack(mats))
                    conn.executemany(
                        f"UPDATE {table} SET vec_slot = ?, embedding = NULL WHERE id = ?",
                        list(zip(slots, ids)),
                    )
                count += len(ids)
                say(f"{space}: {count:,}")
        finally:
            store.close()
        moved[space] = count
    return moved


def reclaim_database(conn: sqlite3.Connection) -> tuple[int, int]:
    """VACUUM the database and report the bytes before and after.

    Moving vectors out sets the `embedding` column to NULL, which frees pages
    *inside* the file and shrinks nothing: SQLite keeps them on its free list.
    On a kernel-sized index that is the difference between a 4.10 GB file and a
    214 MB one, so the migration is not really done until this runs.

    Returns ``(0, 0)`` when the size cannot be read — an in-memory database has
    no file to shrink, and neither does one whose path SQLite will not report.
    """
    path = None
    for _seq, name, filename in conn.execute("PRAGMA database_list"):
        if name == "main" and filename:
            path = Path(filename)
            break
    if path is None or not path.is_file():
        return (0, 0)
    before = path.stat().st_size
    # VACUUM rewrites the whole file and cannot run inside a transaction. It
    # also needs scratch space of roughly the database's size; letting the
    # OperationalError escape would turn a successful migration into a failed
    # command, so callers treat this as advisory.
    conn.execute("VACUUM")
    # In WAL mode the rewritten pages live in the journal until a checkpoint,
    # so the main file's size still reads as it was — reporting it here would
    # tell the user nothing was reclaimed right after reclaiming it.
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    return (before, path.stat().st_size)


def compact(
    conn: sqlite3.Connection, project_root: Path, *, dim: int, progress=None
) -> dict[str, dict[str, int]]:
    """Renumber every live vector into a dense prefix and drop the rest.

    Reclaims two things a long-lived index accumulates: slots leaked by a crash
    between the byte write and the commit, and the tail of a store that shrank
    after files were deleted. Rewrites into a fresh directory and swaps, so a
    failure partway leaves the original untouched.
    """
    say = progress or (lambda _m: None)
    out: dict[str, dict[str, int]] = {}
    staging = vectors_dir(project_root).with_name("vectors.compact")
    import shutil

    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        for space, table in SPACES.items():
            src = VectorStore(project_root, space, dim=dim)
            dst = VectorStore.__new__(VectorStore)
            VectorStore.__init__(dst, project_root, space, dim=dim)
            dst.dir = staging  # write the compacted copy beside the original
            dst.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(dst.manifest_path, src._manifest.to_json())

            rows = conn.execute(
                f"SELECT id, vec_slot FROM {table} WHERE vec_slot IS NOT NULL "
                f"ORDER BY vec_slot"
            ).fetchall()
            before = high_water(conn, space)
            for i in range(0, len(rows), 4096):
                chunk = rows[i : i + 4096]
                old = [int(r["vec_slot"]) for r in chunk]
                new = list(range(i, i + len(chunk)))
                dst.write(new, src.read(old))
            dst.flush()
            src.close()
            dst.close()

            with immediate(conn):
                conn.executemany(
                    f"UPDATE {table} SET vec_slot = ? WHERE id = ?",
                    [(i, int(r["id"])) for i, r in enumerate(rows)],
                )
                conn.execute(f"DELETE FROM {FREE_TABLE} WHERE space = ?", (space,))
                conn.execute(
                    f"INSERT INTO {ALLOC_TABLE}(space, next_slot) VALUES(?, ?) "
                    f"ON CONFLICT(space) DO UPDATE SET next_slot = excluded.next_slot",
                    (space, len(rows)),
                )
            out[space] = {"before": before, "after": len(rows)}
            say(f"{space}: {before:,} -> {len(rows):,} slots")

        live = vectors_dir(project_root)
        for p in staging.glob("*"):
            os.replace(p, live / p.name)
        # Segments past the new high-water mark are dead weight.
        for space in SPACES:
            kept = (out[space]["after"] + SEGMENT_ROWS - 1) // SEGMENT_ROWS
            for p in sorted(live.glob(f"{space}.*.vec")):
                idx = int(p.stem.rsplit(".", 1)[-1])
                if idx >= max(1, kept):
                    p.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return out


def live_scores(
    conn: sqlite3.Connection, space: str, query: np.ndarray
) -> tuple[np.ndarray, np.ndarray] | None:
    """``(slots, sims)`` for every live slot in *space*, or None if unavailable.

    Freed slots are dropped rather than scored. That is not an optimisation: the
    ranker's adaptive threshold is ``mean + 1.5·std`` over the similarity
    distribution, so leaving recycled slots in at a similarity of 0.0 would drag
    the threshold down and quietly widen every result set on a repo that has seen
    edits. Slots leaked by a crash are the residue this cannot see; they are
    bounded, and ``ken vectors verify`` counts them.

    Returns None — never raises — when there is no store, no project root, or a
    dimension mismatch. Every caller is expected to fall back to the inline
    column on None.
    """
    root = project_root_for(conn)
    if root is None or not vectors_dir(root).is_dir():
        return None
    try:
        store = VectorStore(root, space, dim=int(query.shape[0]))
    except VectorStoreError:
        return None
    except OSError:
        return None

    hw = high_water(conn, space)
    if hw <= 0:
        return None
    try:
        sims = store.scores(query, count=hw)
    except (VectorStoreError, OSError):
        return None
    finally:
        store.close()

    free = np.fromiter(
        (int(r[0]) for r in conn.execute(
            f"SELECT slot FROM {FREE_TABLE} WHERE space = ?", (space,)
        )),
        dtype=np.int64,
    )
    if free.size == 0:
        return np.arange(hw, dtype=np.int64), sims
    free = free[(free >= 0) & (free < hw)]
    mask = np.ones(hw, dtype=bool)
    mask[free] = False
    return np.flatnonzero(mask).astype(np.int64), sims[mask]
