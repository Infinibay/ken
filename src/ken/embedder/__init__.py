"""Text embedder used by the indexer (file/symbol embeddings) and by
the daemon (cr_contexts embeddings, query embeddings for the ranker).

Two backends:

* ``onnx_fastembed.OnnxEmbedder`` — the default, wraps ``fastembed`` (ONNX
  Runtime). Small, CPU-fast, GPU-capable. Serves every model fastembed ships.
* ``st_backend.SentenceTransformerEmbedder`` — opt-in, wraps
  ``sentence-transformers`` (torch). Enables stronger models fastembed does
  not ship (e.g. ``Qwen/Qwen3-Embedding-0.6B``). Requires the ``torch`` extra:
  ``pip install 'ken-rank[torch]'``.

``get_embedder()`` picks the backend automatically from the model name and
returns a process-wide singleton.

Model selection is **safe across upgrades** (see ``resolve_model``): a
project's active model is whatever its DB was encoded with. Bumping
``RECOMMENDED_MODEL`` only affects brand-new projects; existing ones keep
their model until the user runs ``ken reembed``. The session-start brief
surfaces a one-time upgrade suggestion instead of switching silently.

    from ken.embedder import get_embedder
    e = get_embedder()       # process-wide singleton, backend auto-selected
    vecs = e.embed_passages(["hello", "world"])  # → list[np.ndarray]

Embedders are **lazy**: the model is only loaded on the first ``embed_*`` call.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from typing import Protocol

import numpy as np

logger = logging.getLogger("ken.embedder")

EMBEDDING_DIM = 384

# ── Model policy ─────────────────────────────────────────────────────
#
# LEGACY_MODEL is what ken shipped as the default before multilingual
# support: an English-only model that collapses on non-English prompts.
# RECOMMENDED_MODEL is the current default for *new* projects — a
# multilingual model (50+ languages) that is a true fastembed drop-in:
# same 384 dims as the legacy default (the DB does not grow) and faster.
LEGACY_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RECOMMENDED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Bare fallback when there is no project context and no override. Kept at the
# recommended model so anything genuinely fresh gets the better default.
DEFAULT_MODEL = RECOMMENDED_MODEL

META_EMBED_MODEL = "embed_model"
META_UPGRADE_SEEN = "embed_upgrade_seen_at"


class Embedder(Protocol):
    """Minimal embedder contract."""

    @property
    def dim(self) -> int: ...
    def embed_passages(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_query(self, text: str) -> np.ndarray: ...


_lock = threading.Lock()
_singleton: Embedder | None = None
_singleton_model: str | None = None
_forced_model: str | None = None  # set by configure_embedder()


# ── Backend selection ────────────────────────────────────────────────


def _is_fastembed_model(model: str) -> bool:
    """True when fastembed ships this model (→ OnnxEmbedder), else it needs
    the torch backend. On any doubt, assume fastembed — it errors clearly."""
    try:
        from fastembed import TextEmbedding

        return model in {m.get("model") for m in TextEmbedding.list_supported_models()}
    except Exception:  # pragma: no cover - fastembed always importable in practice
        return True


def _build_backend(model: str) -> Embedder:
    if _is_fastembed_model(model):
        from ken.embedder.onnx_fastembed import OnnxEmbedder

        return OnnxEmbedder(model)
    # The torch backend module imports fine without sentence-transformers (its
    # heavy import is lazy), so probe the actual dependency here and fail fast
    # with an actionable message rather than deep inside the first embed call.
    import importlib.util

    if importlib.util.find_spec("sentence_transformers") is None:
        raise RuntimeError(
            f"embedding model {model!r} is not a fastembed model and needs the "
            "torch backend. Install it with:  pip install 'ken-rank[torch]'"
        )
    from ken.embedder.st_backend import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(model)


# ── Model resolution (upgrade-safe) ──────────────────────────────────


def _has_embeddings(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM ci_files WHERE embedding IS NOT NULL LIMIT 1"
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def resolve_model(conn: sqlite3.Connection) -> str:
    """The model a project's DB is (or should be) encoded with.

    Priority: an explicit ``KEN_EMBED_MODEL`` override → the model recorded in
    ``meta`` → inferred. Inference is the safety net: a DB that already holds
    vectors but predates model-recording was built with the LEGACY model, so
    we keep using that (never silently switch it). A brand-new DB with no
    vectors gets the RECOMMENDED model.
    """
    env = os.environ.get("KEN_EMBED_MODEL")
    if env:
        return env
    from ken.db import get_meta

    stored = get_meta(conn, META_EMBED_MODEL)
    if stored:
        return stored
    return LEGACY_MODEL if _has_embeddings(conn) else RECOMMENDED_MODEL


def record_model(conn: sqlite3.Connection, model: str) -> None:
    """Pin a project's model in ``meta`` so future processes resolve it
    without inference. Call from write paths (fresh index / reembed)."""
    from ken.db import set_meta

    set_meta(conn, META_EMBED_MODEL, model)


def pending_upgrade(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """``(current, recommended)`` when the project is on the old English-only
    default and a better multilingual drop-in is available; else ``None``.

    Deliberately narrow: only nudges off the known LEGACY model. A user who
    reembedded to some other model (custom, or the stronger torch model) is
    left alone — no "downgrade" nagging — and an explicit override silences it.
    """
    if os.environ.get("KEN_EMBED_MODEL"):
        return None
    if resolve_model(conn) == LEGACY_MODEL:
        return (LEGACY_MODEL, RECOMMENDED_MODEL)
    return None


# ── Singleton wiring ─────────────────────────────────────────────────


def configure_embedder(model: str) -> None:
    """Pin the process to *model* before any embedding happens. The daemon /
    installer call this with the project's resolved model so a global default
    bump never changes an existing project's active model. Resets the
    singleton if it was already built for a different model."""
    global _forced_model, _singleton, _singleton_model
    with _lock:
        _forced_model = model
        if _singleton is not None and _singleton_model != model:
            _singleton = None
            _singleton_model = None


def _resolve_active_model() -> str:
    if _forced_model:
        return _forced_model
    env = os.environ.get("KEN_EMBED_MODEL")
    if env:
        return env
    # No explicit configuration: discover the project from the cwd and use
    # whatever its DB was encoded with. This keeps short-lived CLI commands
    # (search, recall, …) correct after a `ken reembed` without each having
    # to resolve the model itself.
    try:
        from ken._paths import db_path, find_project_root

        root = find_project_root()
        if root is not None:
            dbp = db_path(root)
            if dbp.is_file():
                from ken.db import connect

                conn = connect(dbp)
                try:
                    return resolve_model(conn)
                finally:
                    conn.close()
    except Exception:  # pragma: no cover - discovery is best-effort
        pass
    return DEFAULT_MODEL


def get_embedder() -> Embedder:
    """Return the process-wide embedder singleton, building it on first use."""
    global _singleton, _singleton_model
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is None:
            model = _resolve_active_model()
            _singleton = _build_backend(model)
            _singleton_model = model
    return _singleton


def configure_for_project(conn: sqlite3.Connection) -> str:
    """Resolve a project's embedding model, pin the process to it, and record
    it in ``meta`` when the DB is brand-new — so a future process resolves the
    same model without inference. Returns the active model.

    This is the single entry point the daemon and installer call right after
    opening the DB, before any embedding. It is what makes a global default
    bump safe: an existing project resolves to its own stored/inferred model,
    never the new default.
    """
    from ken.db import get_meta

    model = resolve_model(conn)
    configure_embedder(model)
    if get_meta(conn, META_EMBED_MODEL) is None and not _has_embeddings(conn):
        record_model(conn, model)  # pin the recommended model for this fresh DB
    return model


def reset_embedder() -> None:
    """Drop the singleton (tests; and after an in-process model change)."""
    global _singleton, _singleton_model, _forced_model
    with _lock:
        _singleton = None
        _singleton_model = None
        _forced_model = None


# ── Canonical embedding-text builders (unchanged) ────────────────────


def embed_symbol_text(kind: str, name: str, docstring: str | None) -> str:
    """Canonical text we hand the embedder for a symbol.

    Mirrors infinidev's format so retrieval calibration carries over.
    """
    tail = (docstring or "").strip()
    return f"{kind} {name} — {tail}" if tail else f"{kind} {name}"


def embed_file_text(language: str | None, stem: str, top_symbols: list[str]) -> str:
    """Canonical file-level embedding text. Captures the file *role* —
    language + base name + a few top-of-file symbol names — without
    embedding the whole content (which would dominate any retrieval).
    """
    lang = language or "text"
    if top_symbols:
        return f"{lang} {stem} — {' '.join(top_symbols)}"
    return f"{lang} {stem}"


def embed_intent_text(source_kind: str, text: str) -> str:
    """Canonical text for explicit purpose/intent sources such as docstrings."""
    return f"{source_kind} — {' '.join(text.split())}"


def vec_to_blob(vec: np.ndarray) -> bytes:
    """Serialise a float32 array for SQLite storage."""
    return np.ascontiguousarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes | memoryview) -> np.ndarray:
    """Deserialise; returns a read-only view backed by the supplied bytes."""
    return np.frombuffer(bytes(blob), dtype=np.float32)
