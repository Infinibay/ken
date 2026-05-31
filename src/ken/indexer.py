"""Initial + incremental code index.

The pipeline per file:
  1. Read bytes, hash with blake2b-256.
  2. Skip if `ci_files.content_hash + parser_version` already match
     (idempotent re-run, infinidev-style).
  3. Pick a language by extension; fall back to "treat as plain text"
     (no symbols, but the file row is created so context-rank can score
     it via path / mtime even without parsing).
  4. Run the parser, persist file + symbols + imports atomically.
  5. If an embedder was supplied, embed every symbol (one batch per
     file) plus the file as a whole, store as float32 BLOB.

Callers that don't pass an embedder (e.g. `ken install` on a slow
laptop) get structural-only indexing; the daemon's IndexQueue passes
its lazy embedder so live edits get embeddings on the spot.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
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

    for rel in rels:
        stats.visited += 1
        rel_posix = rel.as_posix()
        abs_path = project_root / rel
        try:
            st = abs_path.stat()
        except OSError:
            stats.skipped_io_error += 1
            if on_progress:
                on_progress(rel_posix, "skipped:io_error")
            continue
        if st.st_size > max_file_bytes:
            stats.skipped_too_large += 1
            if on_progress:
                on_progress(rel_posix, "skipped:too_large")
            continue

        lang_match = detect_language(rel)
        if lang_match is None:
            # Track the file row anyway — context-rank can score files
            # without symbols (path, mtime, edit history). For small
            # project docs/config/scripts, also keep a restrained
            # intent source so setup prompts can find README.md,
            # install.sh, pyproject.toml, etc. without a language parser.
            try:
                data = abs_path.read_bytes()
            except OSError:
                stats.skipped_io_error += 1
                if on_progress:
                    on_progress(rel_posix, "skipped:io_error")
                continue
            content_hash = _hash(data)
            if _is_unchanged(
                conn,
                rel_posix,
                content_hash,
                need_embedding=embedder is not None,
            ):
                stats.unchanged += 1
                if on_progress:
                    on_progress(rel_posix, "unchanged")
                continue

            file_blob: bytes | None = None
            intent_texts = _plain_text_intents(rel_posix, data)
            intent_blobs: list[bytes | None] = [None] * len(intent_texts)
            if embedder is not None:
                from ken.embedder import embed_file_text, embed_intent_text, vec_to_blob

                stem = Path(rel_posix).stem
                top_terms = intent_texts[:1]
                file_blob = vec_to_blob(
                    embedder.embed_query(embed_file_text(None, stem, top_terms))
                )
                if intent_texts:
                    intent_vecs = embedder.embed_passages(
                        [embed_intent_text("plain_text", text) for text in intent_texts]
                    )
                    intent_blobs = [vec_to_blob(vec) for vec in intent_vecs]

            with conn:
                file_id = _upsert_file_row(
                    conn,
                    rel_posix,
                    language=None,
                    content_hash=content_hash,
                    mtime_ns=st.st_mtime_ns,
                    symbol_count=0,
                    embedding=file_blob,
                )
                conn.execute("DELETE FROM ci_symbols WHERE file_id = ?", (file_id,))
                conn.execute("DELETE FROM ci_imports WHERE from_file_id = ?", (file_id,))
                conn.execute("DELETE FROM ci_intent_sources WHERE file_id = ?", (file_id,))
                for intent_text, intent_blob in zip(intent_texts, intent_blobs):
                    _insert_file_intent_source(
                        conn,
                        file_id,
                        source_kind="plain_text",
                        text=intent_text,
                        embedding=intent_blob,
                        weight=0.55,
                    )
            stats.skipped_no_lang += 1
            if on_progress:
                on_progress(rel_posix, "indexed:noparse")
            continue

        language, parser_fn = lang_match

        try:
            data = abs_path.read_bytes()
        except OSError:
            stats.skipped_io_error += 1
            if on_progress:
                on_progress(rel_posix, "skipped:io_error")
            continue

        content_hash = _hash(data)
        if _is_unchanged(conn, rel_posix, content_hash, need_embedding=embedder is not None):
            stats.unchanged += 1
            if on_progress:
                on_progress(rel_posix, "unchanged")
            continue

        try:
            parsed = parser_fn(data, rel_posix)
        except Exception:  # pragma: no cover — tree-sitter never raises in practice
            stats.skipped_io_error += 1
            if on_progress:
                on_progress(rel_posix, "skipped:parse_error")
            continue

        # Compute embeddings *outside* the transaction — fastembed can
        # take tens of ms on a cold session, and we don't want to hold
        # the SQLite write lock that long.
        symbol_blobs: list[bytes | None] = [None] * len(parsed.symbols)
        intent_file_blob: bytes | None = None
        intent_symbol_blobs: list[bytes | None] = [None] * len(parsed.symbols)
        file_blob: bytes | None = None
        if embedder is not None:
            from ken.embedder import (
                embed_file_text,
                embed_intent_text,
                embed_symbol_text,
                vec_to_blob,
            )

            if parsed.symbols:
                texts = [
                    embed_symbol_text(s.kind, s.name, s.docstring) for s in parsed.symbols
                ]
                vecs = embedder.embed_passages(texts)
                symbol_blobs = [vec_to_blob(v) for v in vecs]
                intent_texts = [
                    embed_intent_text("symbol_docstring", s.docstring or "")
                    if s.docstring
                    else ""
                    for s in parsed.symbols
                ]
                doc_indices = [i for i, text in enumerate(intent_texts) if text]
                if doc_indices:
                    intent_vecs = embedder.embed_passages(
                        [intent_texts[i] for i in doc_indices]
                    )
                    for i, vec in zip(doc_indices, intent_vecs):
                        intent_symbol_blobs[i] = vec_to_blob(vec)
            stem = Path(rel_posix).stem
            top_names = [s.name for s in parsed.symbols[:8]]
            file_text = embed_file_text(language, stem, top_names)
            file_blob = vec_to_blob(embedder.embed_query(file_text))
            if parsed.docstring:
                intent_file_blob = vec_to_blob(
                    embedder.embed_query(
                        embed_intent_text("module_docstring", parsed.docstring)
                    )
                )

        with conn:  # implicit BEGIN/COMMIT around the whole file write
            file_id = _upsert_file_row(
                conn,
                rel_posix,
                language=language,
                content_hash=content_hash,
                mtime_ns=st.st_mtime_ns,
                symbol_count=len(parsed.symbols),
                embedding=file_blob,
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
                    embedding=intent_file_blob,
                )
            if parsed.symbols:
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
                            symbol_blobs[i],
                        ),
                    )
                    if s.docstring:
                        _insert_symbol_intent_source(
                            conn,
                            file_id,
                            int(cur.lastrowid),
                            source_kind="symbol_docstring",
                            text=s.docstring,
                            embedding=intent_symbol_blobs[i],
                        )
            if parsed.imports:
                conn.executemany(
                    "INSERT INTO ci_imports(from_file_id, to_module, line) VALUES (?, ?, ?)",
                    [(file_id, imp.module, imp.line) for imp in parsed.imports],
                )

        stats.parsed += 1
        stats.symbols += len(parsed.symbols)
        stats.imports += len(parsed.imports)
        if on_progress:
            on_progress(rel_posix, "indexed")

    stats.elapsed_s = time.monotonic() - t0
    _resolve_internal_imports(conn)
    return stats


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


def _resolve_internal_imports(conn: sqlite3.Connection) -> None:
    """Resolve import module strings to indexed files when the mapping is obvious."""
    imports = conn.execute(
        "SELECT id, to_module FROM ci_imports WHERE to_file_id IS NULL"
    ).fetchall()
    if not imports:
        return
    file_rows = conn.execute("SELECT id, path FROM ci_files").fetchall()
    files = [r["path"] for r in file_rows]
    by_path = {r["path"]: int(r["id"]) for r in file_rows}
    updates: list[tuple[int, int]] = []
    for row in imports:
        target = _resolve_import_target(str(row["to_module"]), files)
        if target is not None:
            updates.append((by_path[target], int(row["id"])))
    if updates:
        conn.executemany("UPDATE ci_imports SET to_file_id = ? WHERE id = ?", updates)


def _resolve_import_target(module: str, files: list[str]) -> str | None:
    mod = module.strip().strip("'\"")
    if not mod:
        return None
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
    if mod.startswith("./") or mod.startswith("../") or "/" in mod:
        candidates.update({mod, f"{mod}.py", f"{mod}.ts", f"{mod}.js"})
    matches = [path for path in files if path in candidates or path.endswith(f"/{slash}.py")]
    unique = sorted(set(matches))
    return unique[0] if len(unique) == 1 else None


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
