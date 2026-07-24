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

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
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
# The built-in recommendation. A user can override it for *new* projects with
# `ken default-model <name>` (stored in the user config); see recommended_model().
RECOMMENDED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

META_EMBED_MODEL = "embed_model"
META_UPGRADE_SEEN = "embed_upgrade_seen_at"
META_DOC_SPACE = "embed_doc_space"
META_REEMBED_SEEN = "embed_reembed_seen_at"

# ── Query / passage prompts ──────────────────────────────────────────
#
# Some models are *asymmetric*: they were trained with a task instruction on
# the query side and either nothing or a different marker on the document side.
# Encoding a stored document with the query prompt (or vice versa) files it in
# the wrong region of the space, so the policy lives here — one table both
# backends consult — rather than in whichever backend happened to need it.
#
# fastembed does NOT do this for us: its ``query_embed``/``passage_embed`` are
# plain aliases of ``embed`` for every model except Jina v3.
#
# model-name prefix → (query_prompt, passage_prompt). Longest match wins.
MODEL_PROMPTS: tuple[tuple[str, str, str], ...] = (
    (
        "Qwen/Qwen3-Embedding",
        "Instruct: Given a developer's question, retrieve the code file that "
        "answers it\nQuery: ",
        "",
    ),
    ("intfloat/multilingual-e5", "query: ", "passage: "),
    ("intfloat/e5", "query: ", "passage: "),
)

# The document-encoding generation. Bumped when the *meaning* of a stored
# vector changes for some model, so a project encoded under an older scheme can
# be detected and offered a `ken reembed`:
#   1 — pre-0.6: documents were encoded with the query prompt, and the ONNX
#       backend applied no prompt at all.
#   2 — documents use the passage prompt on both backends.
DOC_SPACE_VERSION = 2


def prompts_for(model: str) -> tuple[str, str]:
    """``(query_prompt, passage_prompt)`` for *model* — ``("", "")`` if symmetric."""
    best = ("", "")
    best_len = -1
    for prefix, query_prompt, passage_prompt in MODEL_PROMPTS:
        if model.startswith(prefix) and len(prefix) > best_len:
            best, best_len = (query_prompt, passage_prompt), len(prefix)
    return best


def is_asymmetric(model: str) -> bool:
    """Whether *model* encodes queries and documents differently."""
    return prompts_for(model) != ("", "")


# ── User-level config: default model for NEW projects ────────────────


def _config_path() -> Path:
    """Location of the user config. Honors KEN_CONFIG_DIR (tests / custom),
    then XDG_CONFIG_HOME, else ~/.config/ken/."""
    base = os.environ.get("KEN_CONFIG_DIR")
    if base:
        return Path(base) / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "ken" / "config.json"


def _read_config() -> dict:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_user_default_model() -> str | None:
    """The model the user pinned for new projects, or None if unset."""
    m = _read_config().get("default_model")
    return m if isinstance(m, str) and m.strip() else None


def set_user_default_model(model: str | None) -> Path:
    """Set (or, with model=None, clear) the default model for new projects.
    Returns the config path written."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_config()
    if model:
        data["default_model"] = model
    else:
        data.pop("default_model", None)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def recommended_model() -> str:
    """The default model a fresh project should use: the user's configured
    default if set, else the built-in RECOMMENDED_MODEL."""
    return get_user_default_model() or RECOMMENDED_MODEL


class Embedder(Protocol):
    """Minimal embedder contract.

    ``embed_passages`` is for text that will be **stored** and searched;
    ``embed_query`` / ``embed_queries`` for text used to **search**. On an
    asymmetric model the two are encoded differently, so the choice is part of
    the contract, not an optimisation.
    """

    @property
    def dim(self) -> int: ...
    def embed_passages(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_query(self, text: str) -> np.ndarray: ...
    def embed_queries(self, texts: list[str]) -> list[np.ndarray]: ...


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
    return LEGACY_MODEL if _has_embeddings(conn) else recommended_model()


def record_model(conn: sqlite3.Connection, model: str) -> None:
    """Pin a project's model in ``meta`` so future processes resolve it
    without inference. Call from write paths (fresh index / reembed)."""
    from ken.db import set_meta

    set_meta(conn, META_EMBED_MODEL, model)


def doc_space_version(conn: sqlite3.Connection) -> int:
    """The document-encoding generation this project's vectors were written in.

    A DB with no marker predates the marker; if it holds vectors at all they
    are generation 1, and a brand-new DB is already current.
    """
    from ken.db import get_meta

    raw = get_meta(conn, META_DOC_SPACE)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return 1 if _has_embeddings(conn) else DOC_SPACE_VERSION


def record_doc_space(conn: sqlite3.Connection) -> None:
    """Pin this project's vectors to the current document-encoding generation."""
    from ken.db import set_meta

    set_meta(conn, META_DOC_SPACE, str(DOC_SPACE_VERSION))


def pending_reembed(conn: sqlite3.Connection) -> str | None:
    """Why this project needs a ``ken reembed``, or ``None``.

    Fires when the stored vectors predate the current document encoding *and*
    the active model is asymmetric — only then do the two encodings actually
    differ. On the symmetric default models the old and new bytes are
    identical, so there is nothing to migrate and nothing to say.

    This matters because the indexer cannot repair it on its own: an unchanged
    file keeps its stored vector (same hash, same parser version), so editing
    one file would leave the index split across two encodings rather than
    converging on the new one.
    """
    model = resolve_model(conn)
    if not is_asymmetric(model):
        return None
    if doc_space_version(conn) >= DOC_SPACE_VERSION:
        return None
    if not _has_embeddings(conn):
        return None
    return (
        f"{model} encodes questions and documents differently, and this index "
        "was built before ken applied that distinction to stored vectors"
    )


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
        return (LEGACY_MODEL, recommended_model())
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
    return recommended_model()


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
        record_doc_space(conn)  # ...and its document encoding, so it is never nudged
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


class EmbeddingSpaceMismatch(RuntimeError):
    """Stored vectors were written by a different model than the live one."""


def stack_embeddings(
    blobs, *, dim: int, strict: bool = True
) -> tuple[np.ndarray, list[int]]:
    """Stack stored embedding blobs into an ``(n, dim)`` matrix.

    Returns ``(matrix, kept)`` where *kept* holds the positions of the blobs
    that survived. Rows of a different dimensionality are dropped: they were
    written by another model, so a similarity against them is meaningless.
    Without this, a DB holding two generations of vectors makes numpy build a
    ragged array and raise far from the actual cause.

    When *nothing* matches, the whole index belongs to another model. With
    ``strict`` (the default) that raises :class:`EmbeddingSpaceMismatch`, which
    names ``ken reembed`` — right for a tool the user invoked directly and is
    waiting on. Background scorers (the ranker's channels, intent history) pass
    ``strict=False`` and get an empty result instead: they run inside hooks,
    where a raised error costs the user their context injection, and the
    session brief is what tells them to reembed.
    """
    kept: list[int] = []
    vecs: list[np.ndarray] = []
    stored_dims: set[int] = set()
    for i, blob in enumerate(blobs):
        if blob is None:
            continue
        vec = blob_to_vec(blob)
        stored_dims.add(int(vec.shape[0]))
        if vec.shape[0] != dim:
            continue
        kept.append(i)
        vecs.append(vec)
    if not kept:
        if stored_dims and strict:
            raise EmbeddingSpaceMismatch(
                f"stored embeddings are {sorted(stored_dims)}-dimensional but the "
                f"live embedder produces {dim} — the index was built with a "
                "different model; run `ken reembed`"
            )
        return np.zeros((0, dim), dtype=np.float32), []
    return np.asarray(vecs, dtype=np.float32), kept


def rank_against(query: np.ndarray, blobs, *, strict: bool = True):
    """Cosine of *query* against stored blobs, plus the indices that survived.

    The convenience form of ``stack_embeddings`` + ``cosine_against`` for the
    common shape: callers keep ``rows`` aligned with the scores by reindexing
    through the returned ``kept`` list.
    """
    mat, kept = stack_embeddings(blobs, dim=int(query.shape[0]), strict=strict)
    return cosine_against(query, mat), kept


def cosine_against(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of a query vector against each row of *matrix*.

    Both sides are normalised here rather than assumed: backends return unit
    vectors today, but a DB can outlive that guarantee, and an unnormalised row
    would otherwise score by magnitude instead of by direction.
    """
    if matrix.size == 0:
        return np.zeros((matrix.shape[0],), dtype=np.float32)
    q = query / (np.linalg.norm(query) + 1e-12)
    norms = np.linalg.norm(matrix, axis=1) + 1e-12
    return (matrix @ q) / norms
