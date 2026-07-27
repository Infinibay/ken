"""Re-encode every stored embedding with the current embedding model.

Changing the embedding model invalidates every vector in the database —
cosine similarity between vectors from two different models is meaningless,
and mixing dimensions breaks the ranker's matrix operations outright.

This is cheap to fix because ken stores the *source text* of every
embedding in plain text: prompts in ``cr_contexts.content``, docstrings in
``ci_intent_sources.text``, symbol names/docstrings in ``ci_symbols``, and
file-level text is derived from ``ci_files`` plus its symbols. Nothing here
needs the worktree or a re-parse, so swapping models never requires
re-indexing the repository.

The active model and dimension are recorded in ``meta`` so a mismatch can be
detected before the ranker trips over it.
"""

from __future__ import annotations

import base64
import sqlite3
import time
from collections.abc import Callable

from ken.db import get_meta, set_meta
from ken.embedder import (
    blob_to_vec,
    embed_file_text,
    embed_intent_text,
    embed_symbol_text,
    get_embedder,
    record_doc_space,
    vec_to_blob,
)

META_MODEL = "embed_model"
META_DIM = "embed_dim"
META_AT = "embed_reencoded_at"
META_PROBE_TEXT = "embed_probe_text"
META_PROBE_VEC = "embed_probe_vec"

# A fixed sentence encoded alongside every re-embed. Storing the model *name*
# is not enough to guarantee the vector space is unchanged: the same name can
# produce different vectors across library versions (fastembed switched
# paraphrase-multilingual-MiniLM from CLS to mean pooling, for example).
# Re-encoding this probe and comparing against the stored vector detects that
# drift directly, which a name comparison silently misses.
PROBE_TEXT = "Hola mundo — ken embedding probe / prueba de codificación"

# Cosine below this means the live model no longer matches the stored space.
PROBE_MIN_COSINE = 0.9995

_BATCH = 256


def stored_embedding_info(conn: sqlite3.Connection) -> tuple[str | None, int | None]:
    """Return ``(model, dim)`` the database was last encoded with."""
    model = get_meta(conn, META_MODEL)
    raw_dim = get_meta(conn, META_DIM)
    try:
        dim = int(raw_dim) if raw_dim is not None else None
    except ValueError:
        dim = None
    return model, dim


def embedding_mismatch(conn: sqlite3.Connection, current_model: str) -> str | None:
    """Describe a model mismatch between the DB and *current_model*, if any."""
    stored, _dim = stored_embedding_info(conn)
    if stored is None or stored == current_model:
        return None
    return (
        f"database was encoded with '{stored}' but the active model is "
        f"'{current_model}' — run `ken reembed` to re-encode"
    )


def _store_probe(conn: sqlite3.Connection, vec: "np.ndarray") -> None:
    set_meta(conn, META_PROBE_TEXT, PROBE_TEXT)
    set_meta(conn, META_PROBE_VEC, base64.b64encode(vec_to_blob(vec)).decode("ascii"))


def validate_embeddings(conn: sqlite3.Connection) -> dict:
    """Check the live embedder still produces the DB's vector space.

    Re-encodes :data:`PROBE_TEXT` and compares it to the vector stored at the
    last ``reembed``. Catches both an outright model swap and a silent change
    in how the *same* model is encoded (library/pooling changes), which a name
    check cannot see.
    """
    import numpy as np

    stored_model, stored_dim = stored_embedding_info(conn)
    raw = get_meta(conn, META_PROBE_VEC)
    probe_text = get_meta(conn, META_PROBE_TEXT) or PROBE_TEXT
    emb = get_embedder()
    live_model = getattr(emb, "model_name", "unknown")
    out: dict = {
        "stored_model": stored_model,
        "stored_dim": stored_dim,
        "live_model": live_model,
    }
    if raw is None:
        out.update(ok=False, reason="no probe stored — run `ken reembed`")
        return out
    stored_vec = blob_to_vec(base64.b64decode(raw))
    live_vec = emb.embed_query(probe_text).astype("float32")
    out["live_dim"] = int(live_vec.shape[0])
    if live_vec.shape != stored_vec.shape:
        out.update(
            ok=False,
            reason=(
                f"dimension changed {stored_vec.shape[0]} -> {live_vec.shape[0]}; "
                "every stored vector is unusable — run `ken reembed`"
            ),
        )
        return out
    cos = float(
        np.dot(stored_vec, live_vec)
        / ((np.linalg.norm(stored_vec) * np.linalg.norm(live_vec)) + 1e-12)
    )
    out["probe_cosine"] = round(cos, 6)
    if cos < PROBE_MIN_COSINE:
        out.update(
            ok=False,
            reason=(
                f"probe cosine {cos:.4f} < {PROBE_MIN_COSINE} — the live embedder no "
                "longer matches the stored vector space; run `ken reembed`"
            ),
        )
        return out
    out["ok"] = True
    return out


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _flush(conn: sqlite3.Connection, sql: str, rows: list[tuple]) -> None:
    if rows:
        conn.executemany(sql, rows)
        rows.clear()


#: Set while a re-encode is running, cleared when it finishes.
#:
#: A reembed cannot be one transaction: on a kernel-sized index it runs for
#: minutes, and holding SQLite's write lock that long would make every hook in
#: the daemon fail on `busy_timeout` rather than merely wait. So it stays
#: batched — and instead of pretending that is atomic, it says so. An index
#: whose marker survives was interrupted partway and is a mix of two encodings;
#: `ken status` reports it and re-running finishes the job. That converts a
#: silent inconsistency into a visible, recoverable one, which is the property
#: that was actually missing.
META_IN_PROGRESS = "reembed_in_progress"


def interrupted_reembed(conn: sqlite3.Connection) -> str | None:
    """Timestamp of an unfinished re-encode, or None."""
    from ken.db import get_meta

    return get_meta(conn, META_IN_PROGRESS)


def _reembed_vectors(
    conn: sqlite3.Connection,
    store,
    table: str,
    space: str,
    ids: list[int],
    vecs: list,
) -> None:
    """Write a batch of re-encoded vectors, reusing each row's existing slot.

    Rows that have no slot yet — a legacy index whose vectors are still inline —
    get one here, which makes `ken reembed` a migration path as well as a
    re-encode.
    """
    from ken.vectors import allocate, immediate

    if not ids:
        return
    with immediate(conn):
        placeholders = ",".join("?" * len(ids))
        existing = {
            int(r["id"]): r["vec_slot"]
            for r in conn.execute(
                f"SELECT id, vec_slot FROM {table} WHERE id IN ({placeholders})", ids
            )
        }
        needed = [i for i in ids if existing.get(i) is None]
        fresh = iter(allocate(conn, space, len(needed)) if needed else ())
        slots = [
            int(existing[i]) if existing.get(i) is not None else next(fresh) for i in ids
        ]
        import numpy as np

        store.write(slots, np.stack(vecs))
        conn.executemany(
            f"UPDATE {table} SET embedding = NULL, vec_slot = ? WHERE id = ?",
            list(zip(slots, ids)),
        )


def reembed(
    conn: sqlite3.Connection,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Re-encode all stored embeddings. Returns per-table counts."""
    emb = get_embedder()
    model_name = getattr(emb, "model_name", "unknown")
    say = progress or (lambda _m: None)
    say(f"model: {model_name}")

    counts = {"files": 0, "symbols": 0, "intent": 0, "prompts": 0, "findings": 0}
    dim: int | None = None

    stores = _open_reembed_stores(conn, emb, model_name, say)
    set_meta(conn, META_IN_PROGRESS, str(int(time.time() * 1000)))

    def encode(texts: list[str]):
        """Encode stored *documents* (files, symbols, intents, findings)."""
        nonlocal dim
        vecs = emb.embed_passages(texts)
        if vecs and dim is None:
            dim = int(len(vecs[0]))
        return vecs

    def encode_queries(texts: list[str]):
        """Encode stored *queries*, batched.

        ``cr_contexts`` holds user prompts, which the ranker compares against a
        freshly embedded prompt — both sides are queries. Re-encoding them as
        passages would move them out of the space the live ranker searches in
        whenever the model is asymmetric (e5, Qwen3).
        """
        nonlocal dim
        vecs = emb.embed_queries(texts)
        if vecs and dim is None:
            dim = int(len(vecs[0]))
        return vecs

    # ── symbols ──────────────────────────────────────────────────────
    # `vec_slot IS NOT NULL` catches rows whose vector already moved to the
    # store; without it a second reembed would find nothing to do.
    sym_rows = conn.execute(
        "SELECT id, kind, name, docstring FROM ci_symbols "
        "WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL"
    ).fetchall()
    pending: list[tuple] = []
    for i in range(0, len(sym_rows), _BATCH):
        chunk = sym_rows[i : i + _BATCH]
        vecs = encode([embed_symbol_text(r["kind"], r["name"], r["docstring"]) for r in chunk])
        if stores is not None:
            _reembed_vectors(
                conn, stores["ci_symbols"], "ci_symbols", "ci_symbols",
                [int(r["id"]) for r in chunk], vecs,
            )
        else:
            pending.extend((vec_to_blob(v), r["id"]) for r, v in zip(chunk, vecs))
            _flush(conn, "UPDATE ci_symbols SET embedding=? WHERE id=?", pending)
    counts["symbols"] = len(sym_rows)
    say(f"symbols: {counts['symbols']}")

    # ── files (text derived from path/language + top symbol names) ────
    file_rows = conn.execute("SELECT id, path, language FROM ci_files").fetchall()
    texts, ids = [], []
    for f in file_rows:
        top = conn.execute(
            "SELECT name FROM ci_symbols WHERE file_id=? ORDER BY line_start LIMIT 8",
            (f["id"],),
        ).fetchall()
        texts.append(
            embed_file_text(f["language"], _stem(f["path"]), [str(r["name"]) for r in top])
        )
        ids.append(f["id"])
    for i in range(0, len(texts), _BATCH):
        vecs = encode(texts[i : i + _BATCH])
        batch_ids = [int(x) for x in ids[i : i + _BATCH]]
        if stores is not None:
            _reembed_vectors(
                conn, stores["ci_files"], "ci_files", "ci_files", batch_ids, vecs
            )
        else:
            pending.extend((vec_to_blob(v), fid) for fid, v in zip(batch_ids, vecs))
            _flush(conn, "UPDATE ci_files SET embedding=? WHERE id=?", pending)
    counts["files"] = len(ids)
    say(f"files: {counts['files']}")

    # ── intent sources ───────────────────────────────────────────────
    int_rows = conn.execute(
        "SELECT id, source_kind, text FROM ci_intent_sources "
        "WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL"
    ).fetchall()
    for i in range(0, len(int_rows), _BATCH):
        chunk = int_rows[i : i + _BATCH]
        vecs = encode([embed_intent_text(r["source_kind"], r["text"]) for r in chunk])
        if stores is not None:
            _reembed_vectors(
                conn, stores["ci_intent_sources"], "ci_intent_sources",
                "ci_intent_sources", [int(r["id"]) for r in chunk], vecs,
            )
        else:
            pending.extend((vec_to_blob(v), r["id"]) for r, v in zip(chunk, vecs))
            _flush(conn, "UPDATE ci_intent_sources SET embedding=? WHERE id=?", pending)
    counts["intent"] = len(int_rows)
    say(f"intent: {counts['intent']}")

    # ── prompts ──────────────────────────────────────────────────────
    ctx_rows = conn.execute(
        "SELECT id, content FROM cr_contexts WHERE embedding IS NOT NULL"
    ).fetchall()
    for i in range(0, len(ctx_rows), _BATCH):
        chunk = ctx_rows[i : i + _BATCH]
        vecs = encode_queries([str(r["content"]) for r in chunk])
        pending.extend((vec_to_blob(v), r["id"]) for r, v in zip(chunk, vecs))
        _flush(conn, "UPDATE cr_contexts SET embedding=? WHERE id=?", pending)
    counts["prompts"] = len(ctx_rows)
    say(f"prompts: {counts['prompts']}")

    # ── findings ─────────────────────────────────────────────────────
    find_rows = conn.execute(
        "SELECT id, topic, content FROM cr_findings WHERE embedding IS NOT NULL"
    ).fetchall()
    for i in range(0, len(find_rows), _BATCH):
        chunk = find_rows[i : i + _BATCH]
        vecs = encode([f"{r['topic']}\n\n{str(r['content'])[:1024]}" for r in chunk])
        pending.extend((vec_to_blob(v), r["id"]) for r, v in zip(chunk, vecs))
        _flush(conn, "UPDATE cr_findings SET embedding=? WHERE id=?", pending)
    counts["findings"] = len(find_rows)
    say(f"findings: {counts['findings']}")

    if stores is not None:
        for store in stores.values():
            store.close()

    probe_vec = emb.embed_query(PROBE_TEXT)
    _store_probe(conn, probe_vec)
    # Every vector in the DB now uses the current document/query split, so this
    # project stops being a reembed candidate.
    record_doc_space(conn)
    set_meta(conn, META_MODEL, model_name)
    if dim is not None:
        set_meta(conn, META_DIM, str(dim))
    set_meta(conn, META_AT, str(int(time.time() * 1000)))
    conn.execute("DELETE FROM meta WHERE key = ?", (META_IN_PROGRESS,))
    counts["model"] = model_name
    counts["dim"] = dim
    return counts


def _open_reembed_stores(conn, emb, model_name: str, say) -> dict | None:
    """Open (or rebuild) the vector spaces this re-encode will write into.

    A model swap that changes dimensionality invalidates every stored vector and
    the files that hold them: the manifest pins a width, and a 1024-wide segment
    cannot be reinterpreted as 384-wide. So a dimension change wipes the store
    and starts over, resetting the slot bookkeeping with it — which is safe
    precisely because reembed is the operation that regenerates every vector
    anyway. Same-dimension re-encodes rewrite in place and keep their slots.
    """
    from ken.vectors import SPACES, VectorStore, VectorStoreError, project_root_for

    root = project_root_for(conn)
    if root is None:
        return None
    dim = int(getattr(emb, "dim", 0) or 0)
    if dim <= 0:
        return None
    try:
        return {s: VectorStore(root, s, dim=dim, model=model_name) for s in SPACES}
    except VectorStoreError:
        say("vector store has a different width; rebuilding it from scratch")
        _reset_vector_store(conn, root)
        try:
            return {s: VectorStore(root, s, dim=dim, model=model_name) for s in SPACES}
        except (VectorStoreError, OSError):
            return None
    except OSError:
        return None


def _reset_vector_store(conn, root) -> None:
    import shutil

    from ken.vectors import ALLOC_TABLE, FREE_TABLE, SPACES, vectors_dir

    shutil.rmtree(vectors_dir(root), ignore_errors=True)
    for space in SPACES:
        conn.execute(f"DELETE FROM {ALLOC_TABLE} WHERE space = ?", (space,))
        conn.execute(f"DELETE FROM {FREE_TABLE} WHERE space = ?", (space,))
        conn.execute(f"UPDATE {space} SET vec_slot = NULL")
