"""Static-table embedder: a lookup and a sum, with no transformer at inference.

A transformer embedder answers "what does this text mean" by running every token
through 28 layers of attention and MLP — 0.88 GFLOP per token for
Qwen3-Embedding-0.6B. This backend answers the same question with a table: one
vector per token, summed, projected once per *text*, normalised. Per token that
is a gather of ``r`` floats and ``r`` adds; the only matrix multiply left is a
single ``r x dim`` matvec for the whole text.

    ids    = tokenize(text)            # the teacher's own BPE
    rows   = lut[ids]                  # whole-vocab map, branch-free, OOV hashed
    pooled = Σ A[rows]                 # gather + segment sum
    vec    = normalise(pooled · B)     # one matvec per text

The table is not hand-built: it is a ridge regression fitted so that this
function reproduces a strong teacher's vectors on 964 475 texts, which were
built by the three functions above from source parsed with ken's own parsers,
balanced across the sixteen languages ken indexes.

What makes the approximation viable at all is a property of ken's corpus rather
than a general claim — the texts ken stores are short (median 5 tokens, p99 31),
and a bag of tokens loses to a transformer mainly through word order, which
barely matters at that length. Shuffling the words of a real ken text moves the
teacher's own vector only to cosine 0.94.

What makes it *generalise* is much duller, and it was not obvious in advance:
vocabulary coverage. Every token outside the fitted table collapses into a
shared hash bucket, and inside a sum one polluted row is enough to ruin a
ten-token text. The first table was fitted on one workspace and left 21% of the
tokens in unfamiliar code with no row of their own; it scored 0.627 on the
fixture set drawn from that same workspace and 0.281 on held-out code. This one
leaves 1.6% uncovered and reaches 0.708 against the teacher's 0.728.

Two lessons are recorded here because both cost a day to learn. The fixture
number was the misleading one: an in-domain evaluation is structurally blind to
a vocabulary failure, since in-domain there is no unfamiliar token, and it
ranked candidate tables in exactly the reverse of the held-out order. And the
corpus has to be balanced by language rather than merely large — a corpus of
600 000 texts scraped from Python libraries reached 94% of the teacher pooled,
while 964 475 texts spread evenly over sixteen languages reached 97%, with the
gain concentrated where the first corpus was thin.

**No prompt is prepended, on either side.** Asymmetric teachers want a task
instruction on the query, and for this backend that is actively harmful: the
instruction is ~30 constant tokens, and inside a *sum* it drowns a 14-token
question — measured at recall@10 0.563 without it against 0.540 with it. For the
same reason there is no separate query head; one table serves both sides, which
is what the measurements preferred.

Dependencies: ``numpy`` and ``tokenizers``, both of which ken already has. No
torch, no ONNX, nothing to compile.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger("ken.embedder")

# Artifact layout (a single .npz, self-contained on purpose — one file to
# distribute, and no tokenizer download that could drift from the table):
#   lut        int32   (vocab,)       token id -> table row, OOV pre-hashed
#   A          int8    (rows, r)      the token table (or float16/float32)
#   A_scale    float32 (rows,)        one scale per row; present iff A is int8
#   B          float32 (r, dim)       the shared projection
#   tokenizer  bytes                  the teacher's tokenizer.json, verbatim
#   meta       bytes                  JSON: model id, teacher, dim, provenance
#
# The table is quantised per *row* rather than per tensor because a row is one
# token's vector — the granularity at which the values are actually homogeneous.
# On 4 351 held-out queries across fourteen languages this was free: recall@10
# moved by -0.0003 to +0.0005 with intervals containing zero, while float8 (both
# e4m3 and e5m2) was measurably worse at the same width, because it spends four
# or five bits on an exponent this data does not need. It is dequantised to
# float32 at load, so the arithmetic is unchanged and only the download shrinks.
_REQUIRED = ("lut", "A", "B", "tokenizer", "meta")


# The table that ships inside the wheel. It is the model, so it travels with the
# code rather than being fetched: a first run works offline, the version in the
# name always matches the version this build was written against, and there is
# no download path to fail. It costs ~23 MB of wheel.
_BUNDLED = Path(__file__).resolve().parent / "data"


def _artifact_path(model_name: str) -> Path:
    """Where the table for *model_name* lives, most specific source first.

    1. ``KEN_STATIC_HEAD`` — an explicit file, so a freshly trained table can be
       tried without installing anything. It wins even when absent, which is
       what lets a test say "pretend there is no table".
    2. the per-user cache, the same shape fastembed uses for its managed
       downloads — so a newer table can be dropped in without reinstalling ken.
    3. the copy inside the package, which is always there.
    """
    override = os.environ.get("KEN_STATIC_HEAD")
    if override:
        return Path(override).expanduser()
    filename = f"{model_name.replace('/', '__')}.npz"
    root = os.environ.get("KEN_CACHE_DIR")
    base = Path(root).expanduser() if root else Path.home() / ".cache" / "ken"
    cached = base / "heads" / filename
    return cached if cached.is_file() else _BUNDLED / filename


def artifact_available(model_name: str) -> bool:
    """Whether the table for *model_name* is on this machine.

    Cheap and side-effect free: this is called during model *resolution*, on
    every short-lived CLI command, so it must not load 14 MB of table or touch
    the network to answer.
    """
    try:
        return _artifact_path(model_name).is_file()
    except Exception:  # pragma: no cover - a broken HOME should not break ken
        return False


class StaticHeadEmbedder:
    """Lazy, dependency-light embedder over a fitted token table."""

    def __init__(self, model_name: str, *, path: str | Path | None = None) -> None:
        self.model_name = model_name
        self._path = Path(path) if path else _artifact_path(model_name)
        self._lock = threading.Lock()
        self._lut: np.ndarray | None = None
        self._A: np.ndarray | None = None
        self._B: np.ndarray | None = None
        self._tok = None
        self._dim = 0
        self.meta: dict = {}

    # ── loading ──────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._lut is not None:
            return
        with self._lock:
            if self._lut is not None:
                return
            if not self._path.is_file():
                raise RuntimeError(
                    f"static embedding table not found at {self._path}. Point "
                    "KEN_STATIC_HEAD at a .npz built by `ken.embedder.static_head`, "
                    "or choose a different model with `ken default-model`."
                )
            from tokenizers import Tokenizer

            npz = np.load(self._path, allow_pickle=False)
            missing = [k for k in _REQUIRED if k not in npz.files]
            if missing:
                raise RuntimeError(
                    f"{self._path} is not a ken static head (missing {missing})"
                )
            A = npz["A"]
            if A.dtype == np.int8:
                if "A_scale" not in npz.files:
                    raise RuntimeError(
                        f"{self._path} stores an int8 table without A_scale; "
                        "the rows cannot be dequantised"
                    )
                A = A.astype(np.float32) * npz["A_scale"].astype(np.float32)[:, None]
            self._A = np.ascontiguousarray(A, dtype=np.float32)
            self._B = np.ascontiguousarray(npz["B"], dtype=np.float32)
            # int32 is enough for any vocabulary and halves the gather's traffic;
            # numpy indexing wants intp, so convert once here rather than per call.
            self._lut = np.asarray(npz["lut"], dtype=np.intp)
            self.meta = json.loads(bytes(npz["meta"]).decode("utf-8"))
            self._tok = Tokenizer.from_str(bytes(npz["tokenizer"]).decode("utf-8"))
            self._dim = int(self._B.shape[1])
            logger.info(
                "loaded static head %s (%d rows x %d, dim %d) from %s",
                self.model_name, self._A.shape[0], self._A.shape[1], self._dim,
                self._path,
            )

    @property
    def dim(self) -> int:
        if self._dim == 0:
            self._load()
        return self._dim

    # ── encoding ─────────────────────────────────────────────────────

    def _encode(self, texts: list[str]) -> list[np.ndarray]:
        self._load()
        encs = self._tok.encode_batch(texts, add_special_tokens=False)
        lengths = np.fromiter((len(e.ids) for e in encs), dtype=np.int64, count=len(encs))
        flat = np.fromiter(
            (i for e in encs for i in e.ids), dtype=np.int64, count=int(lengths.sum())
        )
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        if flat.size:
            rows = self._lut[flat]
            gathered = self._A[rows]
            starts = np.concatenate(([0], np.cumsum(lengths)[:-1]))
            # ``reduceat`` needs every start index to be in range, and it treats a
            # zero-length segment as "take the single element at start" rather
            # than as an empty sum — so empty texts are clamped here and zeroed
            # below. An empty text is not a failure: ken embeds whatever the
            # indexer found, and a file with no symbols really does yield one.
            safe = np.minimum(starts, max(len(rows) - 1, 0))
            pooled = np.add.reduceat(gathered, safe, axis=0)
            pooled[lengths == 0] = 0.0
            out = pooled @ self._B
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return list(out / np.maximum(norms, 1e-12))

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        return self._encode(texts)

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        # One table for both sides: see the module docstring. A separately
        # fitted query head was measured and it was worse than reusing this one.
        if not texts:
            return []
        return self._encode(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([text])[0]
