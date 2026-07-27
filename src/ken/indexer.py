"""Initial + incremental code index.

The pipeline per file:
  1. Read bytes, hash with blake2b-256.
  2. Skip if `ci_files.content_hash + parser_version` already match
     (idempotent re-run, infinidev-style).
  3. Pick a language by extension; fall back to "treat as plain text"
     (no symbols, but the file row is created so context-rank can score
     it via path / mtime even without parsing).
  4. Run the parser, persist file + symbols + imports atomically.
  5. If an embedder was supplied, embed every symbol plus the file as a
     whole, store as float32 BLOB.

Files are processed in **chunks**, and step 5 happens once per chunk
rather than once per file. Every embedder here has a fixed per-call cost
— tokeniser setup, array allocation, for the model backends a padded
forward pass — that dwarfs the marginal cost of one more text. Encoding
file-by-file spent that cost on batches averaging six texts: profiled on
a 751-file project it ran at 1 243 texts/s against the ~10 000 texts/s
the same embedder reaches when handed a real batch, and embedding was
60% of the whole install. Chunking is the only change; each file still
gets its own transaction, and vectors are unaffected because every
backend encodes each text independently (the static table has an
explicit test for that, and the model backends mask their padding).

Callers that don't pass an embedder (e.g. `ken install` on a slow
laptop) get structural-only indexing; the daemon's IndexQueue passes
its lazy embedder so live edits get embeddings on the spot.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ken.parsers import detect_language

if TYPE_CHECKING:  # pragma: no cover
    from ken.embedder import Embedder

PARSER_VERSION = 4


@dataclass
class IndexStats:
    visited: int = 0
    parsed: int = 0
    unchanged: int = 0
    skipped_no_lang: int = 0
    skipped_too_large: int = 0
    skipped_io_error: int = 0
    symbols: int = 0
    imports: int = 0
    elapsed_s: float = 0.0


# How many files are read and parsed before their texts are embedded together.
# The only thing this trades is peak memory against per-call embedder overhead,
# and the memory is small: file bytes are dropped as soon as the parser has run,
# so a chunk holds parse results and a few thousand short strings. 128 files is
# roughly 1 500 texts on a real project — far past the point where the fixed
# per-call cost stops mattering, and far short of anything a laptop notices.
_EMBED_CHUNK_FILES = 128

# Parsing is the other half of an install and it is embarrassingly parallel, but
# only across *processes*: py-tree-sitter holds the GIL for the duration of a
# parse, so a thread pool measured 0.72-0.81x — slower than serial, purely from
# contention. A process pool measured 5.1x on 637 files with the `spawn` start
# method and 7.0x with `fork`.
#
# `spawn` is used anyway. `fork` in a process that has already loaded BLAS and
# ONNX Runtime thread pools can deadlock in the child, and the 1.4x it would buy
# is not worth a hang that only reproduces on someone else's machine. The cost
# of `spawn` is one interpreter start per worker, which is why the pool is
# created once per `index_files` call and only when there is enough work to pay
# for it — the daemon re-indexing a single edited file stays serial.
_PARALLEL_MIN_FILES = 64


def _parse_job(job: tuple[str, str, bytes]):
    """Parse one file in a worker process. Module-level so it can be pickled.

    Returns ``None`` on any parser failure, which the caller reports exactly as
    the serial path does — a worker must not be able to abort an install.
    """
    from ken.parsers import LANGUAGE_BY_EXT

    language, rel_posix, data = job
    fn = next((f for lang, f in LANGUAGE_BY_EXT.values() if lang == language), None)
    if fn is None:  # pragma: no cover - the caller only sends known languages
        return None
    try:
        return fn(data, rel_posix)
    except Exception:
        return None


def _worker_count(n_files: int) -> int:
    """How many parser processes to run, or 0 for serial.

    ``KEN_INDEX_WORKERS`` overrides: ``0`` disables the pool entirely, which is
    the escape hatch for a sandbox that forbids process creation or a host that
    embeds ken from an unguarded ``__main__``.
    """
    override = os.environ.get("KEN_INDEX_WORKERS")
    if override:
        try:
            return max(0, int(override))
        except ValueError:
            pass
    if n_files < _PARALLEL_MIN_FILES:
        return 0
    cpus = os.cpu_count() or 1
    if cpus < 2:
        return 0
    # Above eight the curve flattens (the pool spends its time on the pipe, not
    # the parse) while every extra worker is another interpreter to start.
    return min(8, cpus - 1, max(2, n_files // 32))


@dataclass
class _Pending:
    """One file, read and parsed, waiting for its vectors and its write.

    ``slots`` names where each embedded vector belongs, parallel to ``texts``,
    so the flat batch handed to the embedder can be taken apart again without
    anyone having to keep two orderings in their head.
    """

    rel: str
    language: str | None
    content_hash: bytes
    mtime_ns: int
    order: int = 0                        # position in the chunk, for progress
    parsed: object | None = None          # ParsedFile, for the parsed branch
    intent_texts: list[str] | None = None  # plain-text branch only
    texts: list[str] = field(default_factory=list)
    slots: list[tuple] = field(default_factory=list)
    blobs: dict[tuple, bytes] = field(default_factory=dict)


def index_files(
    conn: sqlite3.Connection,
    project_root: Path,
    rels: Iterable[Path],
    *,
    max_file_bytes: int = 1024 * 1024,
    on_progress=None,
    embedder: "Embedder | None" = None,
) -> IndexStats:
    """Index every relative path in *rels* into *conn*.

    *on_progress* is `(rel: str, status: str) -> None`.  `status` is one
    of ``"indexed"`` / ``"unchanged"`` / ``"skipped:<reason>"``.  Used by
    `ken install` to print a verbose log; the daemon path passes a
    quieter callback (or None).
    """
    stats = IndexStats()
    t0 = time.monotonic()
    todo = list(rels)
    pool = _open_pool(_worker_count(len(todo)))
    try:
        for start in range(0, len(todo), _EMBED_CHUNK_FILES):
            chunk = todo[start : start + _EMBED_CHUNK_FILES]
            events: list[tuple[int, str, str]] = []
            pending = _prepare_chunk(
                conn, project_root, chunk, max_file_bytes, embedder, stats,
                events, pool,
            )
            _embed_pending(pending, embedder)
            _write_pending(conn, pending, stats, events)
            if on_progress:
                # Sorted by position in the chunk, so the log reads in the same
                # order the files were walked. Skips are decided before the
                # writes happen, so without this they would all print first.
                for _order, rel_posix, status in sorted(events):
                    on_progress(rel_posix, status)
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    stats.elapsed_s = time.monotonic() - t0
    _resolve_internal_imports(conn, project_root)
    return stats


def _open_pool(workers: int):
    """A parser pool, or ``None`` if we are staying serial.

    Returning ``None`` rather than raising on failure is deliberate: a sandbox
    that forbids process creation should index a little slower, not fail.
    """
    if workers <= 0:
        return None
    try:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor

        return ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        )
    except Exception:  # pragma: no cover - depends on the host's sandbox
        return None


def _parse_all(jobs: list[tuple[str, str, bytes]], pool) -> list:
    """Parse *jobs* through *pool*, falling back to serial if it breaks.

    A pool that dies mid-run (OOM-killed worker, a host that kills children)
    must not take the install with it, so the whole batch is simply redone in
    this process. Redoing is safe because parsing has no side effects.
    """
    if pool is None or not jobs:
        return [_parse_job(job) for job in jobs]
    try:
        return list(pool.map(_parse_job, jobs, chunksize=8))
    except Exception:
        return [_parse_job(job) for job in jobs]


def _prepare_chunk(
    conn: sqlite3.Connection,
    project_root: Path,
    chunk: list[Path],
    max_file_bytes: int,
    embedder: "Embedder | None",
    stats: IndexStats,
    events: list[tuple[int, str, str]],
    pool=None,
) -> list[_Pending]:
    """Read, hash and parse every file in *chunk*; collect the texts to embed.

    Nothing is written and nothing is embedded here. File bytes are dropped as
    soon as the parser has consumed them, so what survives into the chunk is
    parse results and short strings.

    The cheap-and-serial part (stat, read, hash, the unchanged check) stays in
    this process on purpose: it is under a tenth of a second for the whole
    chunk, and doing it here is what lets an unchanged file be skipped *before*
    its bytes are shipped to a worker. Only parsing crosses the process
    boundary.
    """
    from ken.embedder import (
        embed_file_text,
        embed_intent_text,
        embed_symbol_text,
    )

    pending: list[_Pending] = []
    jobs: list[tuple[str, str, bytes]] = []
    awaiting: list[_Pending] = []
    for order, rel in enumerate(chunk):
        stats.visited += 1
        rel_posix = rel.as_posix()
        abs_path = project_root / rel
        try:
            st = abs_path.stat()
        except OSError:
            stats.skipped_io_error += 1
            events.append((order, rel_posix, "skipped:io_error"))
            continue
        if st.st_size > max_file_bytes:
            stats.skipped_too_large += 1
            events.append((order, rel_posix, "skipped:too_large"))
            continue

        lang_match = detect_language(rel)
        if lang_match is None:
            try:
                data = abs_path.read_bytes()
            except OSError:
                stats.skipped_io_error += 1
                events.append((order, rel_posix, "skipped:io_error"))
                continue
            content_hash = _hash(data)
            if _is_unchanged(
                conn, rel_posix, content_hash, need_embedding=embedder is not None
            ):
                stats.unchanged += 1
                events.append((order, rel_posix, "unchanged"))
                continue

            intent_texts = _plain_text_intents(rel_posix, data)
            del data
            item = _Pending(
                rel=rel_posix,
                language=None,
                content_hash=content_hash,
                mtime_ns=st.st_mtime_ns,
                order=order,
                intent_texts=intent_texts,
            )
            if embedder is not None:
                stem = Path(rel_posix).stem
                # A file embedding is a *document*, so it must go through
                # embed_passages. Asymmetric models (e5, Qwen3) prepend a
                # question instruction on the query side; encoding a stored
                # vector with it puts the index in the wrong space.
                item.texts.append(embed_file_text(None, stem, intent_texts[:1]))
                item.slots.append(("file",))
                for i, text in enumerate(intent_texts):
                    item.texts.append(embed_intent_text("plain_text", text))
                    item.slots.append(("plain_intent", i))
            pending.append(item)
            continue

        language, _parser_fn = lang_match
        try:
            data = abs_path.read_bytes()
        except OSError:
            stats.skipped_io_error += 1
            events.append((order, rel_posix, "skipped:io_error"))
            continue

        content_hash = _hash(data)
        if _is_unchanged(
            conn, rel_posix, content_hash, need_embedding=embedder is not None
        ):
            stats.unchanged += 1
            events.append((order, rel_posix, "unchanged"))
            continue

        # Queued rather than parsed: the whole chunk goes through the pool in
        # one call below, so the workers stay busy instead of being handed one
        # file at a time.
        jobs.append((language, rel_posix, data))
        awaiting.append(
            _Pending(
                rel=rel_posix,
                language=language,
                content_hash=content_hash,
                mtime_ns=st.st_mtime_ns,
                order=order,
            )
        )

    for item, parsed in zip(awaiting, _parse_all(jobs, pool)):
        if parsed is None:
            stats.skipped_io_error += 1
            events.append((item.order, item.rel, "skipped:parse_error"))
            continue
        item.parsed = parsed
        if embedder is not None:
            for i, s in enumerate(parsed.symbols):
                item.texts.append(embed_symbol_text(s.kind, s.name, s.docstring))
                item.slots.append(("symbol", i))
                if s.docstring:
                    item.texts.append(
                        embed_intent_text("symbol_docstring", s.docstring)
                    )
                    item.slots.append(("symbol_doc", i))
            stem = Path(item.rel).stem
            top_names = [s.name for s in parsed.symbols[:8]]
            # Documents, not queries — see the note on the no-parse path above.
            item.texts.append(embed_file_text(item.language, stem, top_names))
            item.slots.append(("file",))
            if parsed.docstring:
                item.texts.append(
                    embed_intent_text("module_docstring", parsed.docstring)
                )
                item.slots.append(("module_doc",))
        pending.append(item)
    return pending


def _embed_pending(pending: list[_Pending], embedder: "Embedder | None") -> None:
    """One embedder call for the whole chunk, then hand the vectors back out.

    This is the entire point of chunking. Splitting the batch by file would
    give identical vectors — every backend encodes each text independently —
    at eight times the cost.
    """
    if embedder is None:
        return
    flat = [t for item in pending for t in item.texts]
    if not flat:
        return
    from ken.embedder import vec_to_blob

    vecs = embedder.embed_passages(flat)
    pos = 0
    for item in pending:
        for slot in item.slots:
            item.blobs[slot] = vec_to_blob(vecs[pos])
            pos += 1
        item.texts = []


def _write_pending(
    conn: sqlite3.Connection,
    pending: list[_Pending],
    stats: IndexStats,
    events: list[tuple[int, str, str]],
) -> None:
    """One transaction per file, as before — chunking changed when vectors are
    computed, not how durably a file lands."""
    for item in pending:
        if item.language is None:
            _write_plain(conn, item)
            stats.skipped_no_lang += 1
            events.append((item.order, item.rel, "indexed:noparse"))
        else:
            _write_parsed(conn, item)
            stats.parsed += 1
            stats.symbols += len(item.parsed.symbols)
            stats.imports += len(item.parsed.imports)
            events.append((item.order, item.rel, "indexed"))


def _write_plain(conn: sqlite3.Connection, item: _Pending) -> None:
    with conn:
        file_id = _upsert_file_row(
            conn,
            item.rel,
            language=None,
            content_hash=item.content_hash,
            mtime_ns=item.mtime_ns,
            symbol_count=0,
            embedding=item.blobs.get(("file",)),
        )
        conn.execute("DELETE FROM ci_symbols WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM ci_imports WHERE from_file_id = ?", (file_id,))
        conn.execute("DELETE FROM ci_intent_sources WHERE file_id = ?", (file_id,))
        for i, intent_text in enumerate(item.intent_texts or ()):
            _insert_file_intent_source(
                conn,
                file_id,
                source_kind="plain_text",
                text=intent_text,
                embedding=item.blobs.get(("plain_intent", i)),
                weight=0.55,
            )


def _write_parsed(conn: sqlite3.Connection, item: _Pending) -> None:
    parsed = item.parsed
    with conn:  # implicit BEGIN/COMMIT around the whole file write
        file_id = _upsert_file_row(
            conn,
            item.rel,
            language=item.language,
            content_hash=item.content_hash,
            mtime_ns=item.mtime_ns,
            symbol_count=len(parsed.symbols),
            embedding=item.blobs.get(("file",)),
        )
        # Wipe and re-insert symbols/imports for this file. Cheap:
        # CASCADE drops references too, and the file's symbols are
        # bounded.
        conn.execute("DELETE FROM ci_symbols WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM ci_imports WHERE from_file_id = ?", (file_id,))
        conn.execute("DELETE FROM ci_intent_sources WHERE file_id = ?", (file_id,))
        if parsed.docstring:
            _insert_file_intent_source(
                conn,
                file_id,
                source_kind="module_docstring",
                text=parsed.docstring,
                embedding=item.blobs.get(("module_doc",)),
            )
        for i, s in enumerate(parsed.symbols):
            cur = conn.execute(
                "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, docstring, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id,
                    s.kind,
                    s.name,
                    s.qualname,
                    s.line_start,
                    s.line_end,
                    s.docstring,
                    item.blobs.get(("symbol", i)),
                ),
            )
            if s.docstring:
                _insert_symbol_intent_source(
                    conn,
                    file_id,
                    int(cur.lastrowid),
                    source_kind="symbol_docstring",
                    text=s.docstring,
                    embedding=item.blobs.get(("symbol_doc", i)),
                )
        if parsed.imports:
            conn.executemany(
                "INSERT INTO ci_imports(from_file_id, to_module, line) VALUES (?, ?, ?)",
                [(file_id, imp.module, imp.line) for imp in parsed.imports],
            )




def delete_file(conn: sqlite3.Connection, rel: str) -> bool:
    """Drop a file from the index (cascades to symbols / imports / refs).

    Returns True if a row was actually deleted.  Used by the watcher when
    a file disappears from disk.
    """
    with conn:
        cur = conn.execute("DELETE FROM ci_files WHERE path = ?", (rel,))
        return cur.rowcount > 0


def delete_path(conn: sqlite3.Connection, rel: str) -> int:
    """Drop an indexed file or every indexed file below a deleted directory.

    Filesystem backends may report a branch-switch directory removal as a
    single delete event for ``src/pkg`` instead of one event per child.  Matching
    both the exact path and the ``rel/`` prefix prevents stale indexed files
    from surviving that compact event.
    """
    prefix = rel.rstrip("/") + "/"
    with conn:
        cur = conn.execute(
            "DELETE FROM ci_files WHERE path = ? OR substr(path, 1, ?) = ?",
            (rel.rstrip("/"), len(prefix), prefix),
        )
        return cur.rowcount


def _hash(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=32).digest()


def _is_unchanged(
    conn: sqlite3.Connection,
    rel: str,
    content_hash: bytes,
    *,
    need_embedding: bool,
) -> bool:
    """A row is unchanged iff hash + parser match.

    With ``need_embedding=True``, we additionally require the row's
    ``embedding`` column to be populated. This lets the daemon's warm
    pass (running with an embedder) re-process files that were
    structurally indexed by ``ken install`` (no embedder) without
    forcing the user to wait for fastembed during the install.
    """
    row = conn.execute(
        "SELECT content_hash, parser_version, embedding IS NOT NULL AS has_emb "
        "FROM ci_files WHERE path = ?",
        (rel,),
    ).fetchone()
    if not row:
        return False
    if row["content_hash"] != content_hash or row["parser_version"] != PARSER_VERSION:
        return False
    if need_embedding and not row["has_emb"]:
        return False
    return True


def _upsert_file_row(
    conn: sqlite3.Connection,
    rel: str,
    *,
    language: str | None,
    content_hash: bytes,
    mtime_ns: int,
    symbol_count: int,
    embedding: bytes | None = None,
) -> int:
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, parser_version, symbol_count, mtime, indexed_at, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "  language = excluded.language, "
        "  content_hash = excluded.content_hash, "
        "  parser_version = excluded.parser_version, "
        "  symbol_count = excluded.symbol_count, "
        "  mtime = excluded.mtime, "
        "  indexed_at = excluded.indexed_at, "
        "  embedding = excluded.embedding",
        (rel, language, content_hash, PARSER_VERSION, symbol_count, mtime_ns, now_ms, embedding),
    )
    row = conn.execute("SELECT id FROM ci_files WHERE path = ?", (rel,)).fetchone()
    return int(row["id"])


def _insert_file_intent_source(
    conn: sqlite3.Connection,
    file_id: int,
    *,
    source_kind: str,
    text: str,
    embedding: bytes | None,
    weight: float = 1.0,
) -> None:
    conn.execute(
        "INSERT INTO ci_intent_sources(file_id, source_kind, text, embedding, weight, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, source_kind, text, embedding, weight, int(time.time() * 1000)),
    )


def _insert_symbol_intent_source(
    conn: sqlite3.Connection,
    file_id: int,
    symbol_id: int,
    *,
    source_kind: str,
    text: str,
    embedding: bytes | None,
) -> None:
    conn.execute(
        "INSERT INTO ci_intent_sources(file_id, symbol_id, source_kind, text, embedding, weight, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1.0, ?)",
        (file_id, symbol_id, source_kind, text, embedding, int(time.time() * 1000)),
    )


# Extension precedence when a JS/TS relative import omits the suffix. TS first
# so `./foo` resolves to foo.ts over a co-located foo.js when both exist.
_JS_EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs")


def _resolve_internal_imports(
    conn: sqlite3.Connection, project_root: Path | None = None
) -> None:
    """Resolve import module strings to indexed files.

    Resolution is dispatched by the *importing* file's language because every
    ecosystem locates modules differently: JS/TS use relative paths plus
    ``tsconfig``/``package.json`` aliases (read from the nearest config), Java
    maps a dotted package to a directory path, Python uses dotted modules. A
    generic path-based pass covers the rest.
    """
    imports = conn.execute(
        "SELECT i.id, i.to_module, f.path AS src, f.language AS lang "
        "FROM ci_imports i JOIN ci_files f ON f.id = i.from_file_id "
        "WHERE i.to_file_id IS NULL"
    ).fetchall()
    if not imports:
        return
    file_rows = conn.execute("SELECT id, path FROM ci_files").fetchall()
    files = [r["path"] for r in file_rows]
    files_set = set(files)
    by_path = {r["path"]: int(r["id"]) for r in file_rows}

    # Language-specific config-aware resolvers, built once.
    alias_resolver = None
    if project_root is not None:
        from ken.jsresolve import build_alias_resolver

        alias_resolver = build_alias_resolver(project_root, files, files_set)
    java_files = [p for p in files if p.endswith(".java")]
    cargo_dirs = sorted(
        (p.rsplit("/", 1)[0] if "/" in p else "" for p in files if p.endswith("Cargo.toml")),
        key=len, reverse=True,
    )
    go_mods = _go_modules(project_root, files) if project_root is not None else []
    go_by_dir = _files_by_dir(p for p in files if p.endswith(".go"))
    kotlin_files = [p for p in files if p.endswith((".kt", ".kts"))]
    php_psr4 = _php_psr4_maps(project_root, files)
    py_suffixes = _python_suffix_index(files)

    updates: list[tuple[int, int]] = []
    resolutions: list[tuple[str, int]] = []
    for row in imports:
        module = str(row["to_module"])
        src = row["src"]
        lang = row["lang"]
        import_id = int(row["id"])
        # 1. structural pass (relative JS/TS, dotted Python, generic path match)
        target = _resolve_import_target(
            module, files, files_set=files_set, source_path=src, py_suffixes=py_suffixes
        )
        # 2. config-aware JS/TS aliases + workspace packages
        if target is None and lang in ("typescript", "javascript") and alias_resolver is not None:
            target = alias_resolver.resolve(module, src, _match_js_module)
        # 3. Java dotted package -> directory path
        if target is None and lang == "java":
            target = _resolve_java_import(module, java_files)
        # 4. Rust crate/super/self module tree (Cargo crate root + mod.rs rules)
        if target is None and lang == "rust":
            target = _resolve_rust_import(module, src, files_set, cargo_dirs)
        # 5. Go module path (go.mod) -> package directory -> representative file
        if target is None and lang == "go":
            target = _resolve_go_import(module, src, go_mods, go_by_dir)
        # 6. Ruby require_relative -> sibling .rb file
        if target is None and lang == "ruby":
            target = _resolve_ruby_import(module, src, files_set)
        # 7. C/C++ quoted #include -> header (relative or unique path suffix)
        if target is None and lang == "cpp":
            target = _resolve_cpp_import(module, src, files_set)
        # 8. Kotlin dotted import -> file declaring that package directory
        if target is None and lang == "kotlin":
            target = _resolve_kotlin_import(module, kotlin_files)
        # 9. PHP `use` namespace -> PSR-4 (composer.json) or unique tail class
        if target is None and lang == "php":
            target = _resolve_php_import(module, php_psr4, files_set)

        if target is not None and target in by_path:
            updates.append((by_path[target], import_id))
            resolutions.append(("internal", import_id))
        else:
            resolutions.append((
                _classify_unresolved(module, lang, src, alias_resolver, go_mods, files_set),
                import_id,
            ))
    if updates:
        conn.executemany("UPDATE ci_imports SET to_file_id = ? WHERE id = ?", updates)
    if resolutions:
        conn.executemany("UPDATE ci_imports SET resolution = ? WHERE id = ?", resolutions)
    # Backfill rows resolved on earlier runs (before this column existed).
    conn.execute(
        "UPDATE ci_imports SET resolution = 'internal' "
        "WHERE to_file_id IS NOT NULL AND resolution IS NULL"
    )


def _classify_unresolved(module, lang, src, alias_resolver, go_mods, files_set) -> str:
    """Label an unresolved import 'external' (a real third-party/stdlib dep) or
    'unresolved' (looks internal but ken could not map it — a resolution gap).

    Shape-based: every ecosystem gives internal imports a recognisable form
    (relative, ``crate::``/``self::``/``super::``, a tsconfig alias, a workspace
    name, the project's own go module prefix, a dotted path that exists in the
    tree). Anything else is an external package.
    """
    m = module.strip().strip('"').strip("'").rstrip(";").strip()
    if lang in ("typescript", "javascript"):
        if m.startswith("./") or m.startswith("../"):
            return "unresolved"
        if alias_resolver is not None and alias_resolver.is_internal_shape(m, src):
            return "unresolved"
        return "external"
    if lang == "rust":
        head = m.split("::", 1)[0].split("{", 1)[0].strip()
        return "unresolved" if head in ("crate", "super", "self") else "external"
    if lang == "go":
        for _mdir, mpath in go_mods:
            if m == mpath or m.startswith(mpath + "/"):
                return "unresolved"
        return "external"
    if lang == "python":
        if m.startswith("."):
            return "unresolved"
        slash = m.replace(".", "/")
        if any(p == f"{slash}.py" or p.endswith(f"/{slash}.py")
               or p.endswith(f"/{slash}/__init__.py") for p in files_set):
            return "unresolved"  # target exists but was ambiguous
        return "external"
    if lang == "java":
        if m.startswith(("java.", "javax.", "jakarta.")):
            return "external"
        suffix = m.replace(".", "/") + ".java"
        return "unresolved" if any(p.endswith("/" + suffix) for p in files_set) else "external"
    if lang == "kotlin":
        if m.startswith((
            "kotlin.", "kotlinx.", "java.", "javax.", "jakarta.",
            "android.", "androidx.",
        )):
            return "external"
        pkg = m.rstrip("*").rstrip(".").rsplit(".", 1)[0] if "." in m else m
        pkgpath = pkg.replace(".", "/")
        return (
            "unresolved"
            if any(
                p.endswith((".kt", ".kts"))
                and ((d := p.rsplit("/", 1)[0] if "/" in p else "") == pkgpath
                     or d.endswith("/" + pkgpath))
                for p in files_set
            )
            else "external"
        )
    if lang == "php":
        # `use` names carry backslashes; require/include literals are paths.
        if "\\" in module or (not m.startswith((".", "/")) and not m.endswith(".php")):
            tail = m.lstrip("\\").replace("\\", "/").rsplit("/", 1)[-1]
            return (
                "unresolved"
                if any(p.endswith(f"/{tail}.php") or p == f"{tail}.php" for p in files_set)
                else "external"
            )
        return "unresolved" if (m.startswith((".", "/")) or m.endswith(".php")) else "external"
    if lang == "cpp":
        if module.lstrip().startswith('"'):  # quoted include = project-intent
            base = m.rsplit("/", 1)[-1]
            return (
                "unresolved"
                if any(p == m or p.endswith("/" + m) or p.endswith("/" + base)
                       for p in files_set)
                else "external"
            )
        return "external"  # angle-bracket / system header
    # Other languages: a relative-looking include is internal, else external.
    return "unresolved" if (m.startswith(".") or m.startswith("/")) else "external"


def _resolve_java_import(module: str, java_files: list[str]) -> str | None:
    """Resolve `com.foo.Bar` (or a static `com.foo.Bar.member`) to a .java file.

    Java packages map directly to directories, so the dotted name becomes a
    path suffix. We require a unique match and skip wildcard imports.
    """
    mod = module.strip().strip(";").strip()
    if not mod or mod.endswith(".*") or mod.endswith("*"):
        return None
    for candidate in (mod, mod.rsplit(".", 1)[0]):  # type, then static-member parent
        suffix = candidate.replace(".", "/") + ".java"
        matches = [p for p in java_files if p == suffix or p.endswith("/" + suffix)]
        if len(matches) == 1:
            return matches[0]
    return None


def _nearest_dir(dirs: list[str], source_path: str) -> str | None:
    """Longest directory in *dirs* (sorted desc by length) that contains source."""
    src_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
    for d in dirs:
        if d == "" or src_dir == d or src_dir.startswith(d + "/"):
            return d
    return None


def _resolve_rust_import(
    module: str, source_path: str, files_set: set[str], cargo_dirs: list[str]
) -> str | None:
    """Resolve crate::/super::/self:: (and bare internal modules) to a .rs file.

    Cargo puts the crate root at ``<crate>/src``; a module ``a::b`` lives at
    ``a/b.rs`` or ``a/b/mod.rs``. The final path segment is often an item
    (type/fn) rather than a module, so we try progressively shorter module
    paths and require a unique on-disk match.
    """
    mod = module.split("{", 1)[0].strip().strip(":")
    if not mod:
        return None
    parts = [p for p in mod.split("::") if p]
    # Glob import `use super::*;` / `self::*;` — the `*` is not a path segment.
    # These overwhelmingly appear in inline `#[cfg(test)] mod tests`, where
    # `super`/`self` refers to the importing file's own module, so resolve to
    # that file rather than treating `*` as a child or climbing a real dir.
    if parts and parts[-1] == "*":
        parts = parts[:-1]
        if parts and all(p in ("super", "self") for p in parts):
            return source_path if source_path in files_set else None
    cargo = _nearest_dir(cargo_dirs, source_path)
    croot = (cargo + "/src").lstrip("/") if cargo is not None else None
    src_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""

    head = parts[0] if parts else ""
    if head == "crate":
        bases, segs = ([croot] if croot else []), parts[1:]
    elif head == "self":
        bases, segs = [src_dir], parts[1:]
    elif head == "super":
        base = src_dir
        rest = parts
        while rest and rest[0] == "super":
            base = base.rsplit("/", 1)[0] if "/" in base else ""
            rest = rest[1:]
        bases, segs = [base], rest
    else:
        # Bare internal module path (declared in the crate root), e.g. `config::X`.
        bases, segs = ([croot] if croot else []), parts

    for base in bases:
        if base is None:
            continue
        for k in range(len(segs), 0, -1):
            stem = "/".join([base, *segs[:k]]).strip("/")
            for cand in (f"{stem}.rs", f"{stem}/mod.rs"):
                if cand in files_set:
                    return cand
    return None


def _go_modules(project_root: Path, files: list[str]) -> list[tuple[str, str]]:
    """Read every go.mod into (dir, module_path), longest dir first."""
    mods: list[tuple[str, str]] = []
    for rel in files:
        if not rel.endswith("go.mod"):
            continue
        d = rel.rsplit("/", 1)[0] if "/" in rel else ""
        try:
            text = (project_root.resolve() / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("module "):
                mods.append((d, line[len("module "):].strip()))
                break
    return sorted(mods, key=lambda m: len(m[0]), reverse=True)


def _files_by_dir(paths) -> dict[str, list[str]]:
    by_dir: dict[str, list[str]] = {}
    for p in paths:
        d = p.rsplit("/", 1)[0] if "/" in p else ""
        by_dir.setdefault(d, []).append(p)
    return by_dir


def _resolve_go_import(
    module: str, source_path: str, go_mods: list[tuple[str, str]],
    go_by_dir: dict[str, list[str]],
) -> str | None:
    """Map a Go import path to its package directory's representative file.

    Go imports name a package (directory), not a file. We strip the nearest
    ``go.mod`` module prefix to get the in-repo directory and return its
    lexically-first non-test ``.go`` file as the edge target.
    """
    mod = module.strip().strip('"')
    src_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
    for mdir, mpath in go_mods:
        if mdir and not (src_dir == mdir or src_dir.startswith(mdir + "/")):
            continue
        if mod == mpath or mod.startswith(mpath + "/"):
            rel = mod[len(mpath):].strip("/")
            pkg_dir = f"{mdir}/{rel}".strip("/") if rel else mdir
            candidates = sorted(
                f for f in go_by_dir.get(pkg_dir, []) if not f.endswith("_test.go")
            )
            if candidates:
                return candidates[0]
            return None
    return None


def _resolve_ruby_import(
    module: str, source_path: str, files_set: set[str]
) -> str | None:
    """Resolve a Ruby ``require_relative`` path to an indexed ``.rb`` file.

    ``require_relative 'bar/baz'`` is the only reliably-internal Ruby load form;
    the parser normalises it to a ``./``-prefixed path with the implicit ``.rb``
    extension dropped. We join against the requiring file's directory and try the
    bare path then the ``.rb`` suffix.
    """
    mod = module.strip().strip("'\"")
    if not (mod.startswith("./") or mod.startswith("../")):
        return None
    joined = _join_relative(source_path, mod)
    for cand in (joined, f"{joined}.rb"):
        if cand in files_set:
            return cand
    return None


def _resolve_cpp_import(
    module: str, source_path: str, files_set: set[str]
) -> str | None:
    """Resolve a quoted ``#include "path"`` to an indexed header.

    The parser keeps the quote style: ``"util/helper.hpp"`` (project-intent) vs a
    bare ``vector`` (angle-bracket system header). Only quoted includes resolve —
    relative against the including file's dir, else as a unique path suffix.
    """
    if not module.lstrip().startswith('"'):
        return None  # angle-bracket / system header — never in-tree
    inc = module.strip().strip('"')
    if not inc:
        return None
    if inc.startswith("./") or inc.startswith("../"):
        joined = _join_relative(source_path, inc)
        return joined if joined in files_set else None
    matches = [p for p in files_set if p == inc or p.endswith("/" + inc)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:  # prefer a header inside the importer's own subtree
        src_top = source_path.split("/", 1)[0]
        same = [p for p in matches if p.split("/", 1)[0] == src_top]
        if len(same) == 1:
            return same[0]
    return None


def _resolve_kotlin_import(module: str, kotlin_files: list[str]) -> str | None:
    """Resolve a dotted Kotlin import to the file declaring its package.

    Unlike Java a Kotlin file name need not match the imported class, so we map
    the import's *package* prefix (all but the final symbol segment) to the
    directory holding ``.kt`` files and require a unique containing file.
    """
    mod = module.strip().strip(";").strip()
    if not mod or mod.endswith("*"):
        return None
    pkg = mod.rsplit(".", 1)[0]  # drop the trailing class/fn symbol
    if not pkg:
        return None
    pkgpath = pkg.replace(".", "/")
    matches = [
        p for p in kotlin_files
        if (d := p.rsplit("/", 1)[0] if "/" in p else "") == pkgpath
        or d.endswith("/" + pkgpath)
    ]
    return matches[0] if len(matches) == 1 else None


def _php_psr4_maps(project_root: Path | None, files: list[str]) -> list[tuple[str, str]]:
    """Read every composer.json's PSR-4 map as (namespace_prefix, base_dir).

    ``autoload."psr-4"`` (and ``autoload-dev``) map a backslash namespace prefix
    (``App\\``) to a base dir (``src/``) relative to the composer.json's dir.
    Longest prefix first so the most specific map wins.
    """
    if project_root is None:
        return []
    maps: list[tuple[str, str]] = []
    for rel in files:
        if not rel.endswith("composer.json"):
            continue
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        try:
            data = json.loads((project_root.resolve() / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for section in ("autoload", "autoload-dev"):
            psr4 = (data.get(section) or {}).get("psr-4") or {}
            for prefix, dirs in psr4.items():
                for d in dirs if isinstance(dirs, list) else [dirs]:
                    full = f"{base}/{d}".strip("/") if base else str(d).strip("/")
                    maps.append((prefix, full))
    return sorted(maps, key=lambda m: len(m[0]), reverse=True)


def _resolve_php_import(
    module: str, psr4_maps: list[tuple[str, str]], files_set: set[str]
) -> str | None:
    """Resolve a PHP ``use`` namespace via PSR-4, else by unique tail-class match."""
    name = module.strip().strip(";").lstrip("\\")
    if not name:
        return None
    for prefix, base in psr4_maps:
        pfx = prefix.lstrip("\\")
        if name.startswith(pfx):
            rest = name[len(pfx):].strip("\\").replace("\\", "/")
            cand = f"{base}/{rest}.php".strip("/")
            if cand in files_set:
                return cand
    tail = name.replace("\\", "/").rsplit("/", 1)[-1]
    matches = [p for p in files_set if p.endswith(f"/{tail}.php") or p == f"{tail}.php"]
    return matches[0] if len(matches) == 1 else None


def _python_suffix_index(files: Iterable[str]) -> dict[str, list[str]]:
    """``"/a/b.py" -> [paths ending in it]``, for the dotted-Python fallback.

    Without it, that fallback is a scan of every indexed file for every
    unresolved import — 751 files x 2 350 imports came to 1.18 million
    ``str.endswith`` calls on one real project, half a second of the install.
    Only ``.py`` paths are indexed because that is the only suffix the fallback
    ever asks about, and only at ``/`` boundaries, which is what ``endswith``
    was matching.
    """
    index: dict[str, list[str]] = {}
    for path in files:
        if not path.endswith(".py"):
            continue
        parts = path.split("/")
        for i in range(1, len(parts)):
            index.setdefault("/" + "/".join(parts[i:]), []).append(path)
    return index


def _resolve_import_target(
    module: str,
    files: list[str],
    *,
    files_set: set[str] | None = None,
    source_path: str | None = None,
    py_suffixes: dict[str, list[str]] | None = None,
) -> str | None:
    mod = module.strip().strip("'\"")
    if not mod:
        return None
    if files_set is None:
        files_set = set(files)

    # JS/TS relative import: resolve against the importing file's directory,
    # with extension and index-file fallbacks. This is the bulk of real
    # internal edges in TS/JS projects and cannot be resolved globally.
    if source_path is not None and (mod.startswith("./") or mod.startswith("../")):
        return _match_js_module(_join_relative(source_path, mod), files_set)

    if mod.startswith("."):
        mod = mod.lstrip(".")
    slash = mod.replace(".", "/")
    candidates = {
        f"{slash}.py",
        f"{slash}/__init__.py",
        f"{slash}.ts",
        f"{slash}.tsx",
        f"{slash}.js",
        f"{slash}.jsx",
        f"{slash}.go",
        f"{slash}.java",
        f"{slash}.rs",
        f"{slash}.dart",
    }
    if "/" in mod:
        candidates.update({mod, f"{mod}.py", f"{mod}.ts", f"{mod}.js"})
    if py_suffixes is None:
        py_suffixes = _python_suffix_index(files)
    matches = set(candidates) & files_set
    matches.update(py_suffixes.get(f"/{slash}.py", ()))
    unique = sorted(matches)
    return unique[0] if len(unique) == 1 else None


def _join_relative(source_path: str, mod: str) -> str:
    """Resolve a `./` or `../` module against the importer's directory (posix)."""
    parts = source_path.split("/")[:-1]  # directory of the importing file
    for seg in mod.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _match_js_module(joined: str, files_set: set[str]) -> str | None:
    """Map a resolved relative base path to an indexed file (ext / index fallback).

    Handles the TS ESM convention where source ``foo.ts`` is imported as
    ``foo.js``: we strip a trailing code extension before trying the real ones,
    so ``./foo.js`` resolves to ``foo.ts`` when that is what is on disk.
    """
    if not joined:
        return None
    if joined in files_set:  # exact path (incl. non-code assets like .json)
        return joined
    stem = joined
    for ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
        if joined.endswith(ext):
            stem = joined[: -len(ext)]
            break
    for ext in _JS_EXTS:
        if stem + ext in files_set:
            return stem + ext
    for ext in _JS_EXTS:
        candidate = f"{stem}/index{ext}"
        if candidate in files_set:
            return candidate
    return None


_PLAIN_TEXT_EXTS = {
    ".md",
    ".rst",
    ".txt",
    ".sh",
    ".toml",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
}
_PLAIN_TEXT_MAX_CHARS = 4000
_PLAIN_TEXT_CHUNK_CHARS = 1200


def _plain_text_intents(rel_posix: str, data: bytes) -> list[str]:
    """Extract compact purpose strings from unparsed project text files."""
    path = Path(rel_posix)
    if path.suffix.lower() not in _PLAIN_TEXT_EXTS:
        return []
    if len(path.parts) > 2:
        return []

    raw = data.decode("utf-8", errors="ignore")
    if path.suffix.lower() in {".md", ".rst"}:
        return _section_intents(raw)
    intent = _clean_plain_text(raw, path)
    return [intent] if intent else []


def _section_intents(raw: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if text.startswith("#") and current:
            _append_intent_chunk(chunks, current)
            current = []
        if text:
            current.append(text.lstrip("#").strip())
    _append_intent_chunk(chunks, current)
    return chunks[:8]


def _append_intent_chunk(chunks: list[str], lines: list[str]) -> None:
    text = " ".join(" ".join(lines).split())
    if text:
        chunks.append(text[:_PLAIN_TEXT_CHUNK_CHARS])


def _clean_plain_text(raw: str, path: Path) -> str | None:
    lines: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("<!--") or text.startswith("//"):
            continue
        if path.suffix.lower() == ".sh" and text.startswith("#") and not text.startswith("#!"):
            continue
        if path.suffix.lower() in {".json", ".jsonl"} and text in {"{", "}", "[", "]"}:
            continue
        lines.append(text.lstrip("#").strip())
        if sum(len(item) for item in lines) >= _PLAIN_TEXT_MAX_CHARS:
            break
    if not lines:
        return None
    text = " ".join(lines)
    return " ".join(text.split())[:_PLAIN_TEXT_MAX_CHARS]
