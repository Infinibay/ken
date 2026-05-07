"""HTTP daemon. One process per ken project.

Endpoints:

    GET  /health                            → { ok, project_id, sessions_active, idle_seconds }
    POST /sessions/start  {session_id,cwd}  → { ok, ken_session_pk }
    POST /sessions/end    {session_id}      → { ok }
    POST /prompts         {session_id,prompt}     → { ok, context_block }
    POST /tools/pre       {session_id,tool,input} → { ok }
    POST /tools/post      {session_id,tool,output,success} → { ok }
    POST /turn-end        {session_id}      → { ok }
    POST /shutdown                          → { ok }   (used by tests)

Auth: every request must carry ``Authorization: Bearer <token>`` matching
``meta.json["auth_token"]``. Localhost-only binding plus the token
prevents another user on the box (or another project's hooks) from
poking us.

Concurrency: ``ThreadingHTTPServer`` gives one worker thread per request.
SQLite connections are not thread-safe, so we serialise DB writes through
a single ``threading.Lock`` around a daemon-owned connection. With our
load (a few writes per second at peak) the lock is invisible.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ken import _paths
from ken.daemon.index_queue import IndexQueue
from ken.daemon.watcher import FileWatcher
from ken.db import connect, init_schema, set_meta
from ken.embedder import get_embedder, vec_to_blob
from ken.gitignore_filter import iter_files

# How long without ANY HTTP activity before we exit. The user's directive
# was "claude should kill it on close, otherwise 10 minutes" — this is the
# upper-bound fallback for when SessionEnd never fires (claude crashed,
# kill -9, etc).
IDLE_TIMEOUT_S = 600.0

# Grace period after the active-session count hits 0. Lets the user open
# a second claude window without paying the spawn cost. SessionEnd → 0 →
# wait 60s → if still 0, exit.
EMPTY_GRACE_S = 60.0

# Background thread checks idle/empty every this many seconds.
SHUTDOWN_TICK_S = 5.0

# Let the first hook/rank request use the already-built index before the
# daemon starts its full filesystem warm pass. This matters on giant repos
# where thousands of hash-skip reindex checks can contend with ranking.
MAINTENANCE_START_DELAY_S = 2.0

# Hard budget for the hook-injected block. Users can still ask for the
# uncapped expanded view with `ken rank --verbose 2` / `ken_rank`.
HOOK_CONTEXT_MAX_CHARS = 3500

logger = logging.getLogger("ken.daemon")


class DaemonState:
    """Mutable state the request handlers need to read/write under lock."""

    def __init__(self, project_root: Path, auth_token: str) -> None:
        self.project_root = project_root
        self.auth_token = auth_token
        self.lock = threading.Lock()
        self.conn: sqlite3.Connection = connect(_paths.db_path(project_root))
        init_schema(self.conn)
        # agent_id (Claude session uuid) -> {"pk": int, "iter": int, "started_at": int}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.last_activity = time.monotonic()
        self.empty_since: float | None = None  # set when sessions hits 0
        self.shutdown_event = threading.Event()
        self.started_at = time.monotonic()

    # ---------- session bookkeeping ------------------------------------

    def session_start(self, agent_id: str) -> int:
        with self.lock:
            now_ms = int(time.time() * 1000)
            if agent_id in self.sessions:
                # Idempotent: re-emit returns the existing pk.
                return self.sessions[agent_id]["pk"]
            cur = self.conn.execute(
                "INSERT INTO cr_sessions(agent_id, started_at) VALUES (?, ?)",
                (agent_id, now_ms),
            )
            pk = int(cur.lastrowid or 0)
            self.sessions[agent_id] = {
                "pk": pk,
                "iter": 0,
                "started_at": now_ms,
                # Anchor for the turn currently being recorded — the most
                # recent user_prompt's context_id. NULL until the first
                # prompt arrives. Tool calls between prompts inherit this
                # so the ranker can apply per-turn decay.
                "last_prompt_context_id": None,
                # Cache of the most recent ranker output for this session
                # so the `ken_rank` MCP tool can re-render at higher
                # verbose without re-running the channels.
                "last_rank_result": None,
                "last_rank_prompt": "",
            }
            self.empty_since = None
            self._touch()
            return pk

    def session_end(self, agent_id: str) -> None:
        with self.lock:
            now_ms = int(time.time() * 1000)
            self.conn.execute(
                "UPDATE cr_sessions SET ended_at = ? WHERE agent_id = ? AND ended_at IS NULL",
                (now_ms, agent_id),
            )
            self.sessions.pop(agent_id, None)
            if not self.sessions:
                self.empty_since = time.monotonic()
            self._touch()

    def next_iteration(self, agent_id: str) -> tuple[int, int]:
        """Return ``(session_pk, iteration)``, incrementing the counter.

        Called from inside the request handler under the daemon lock —
        the caller is responsible for ensuring the session row exists.
        Auto-creates one if Claude Code skipped SessionStart (defensive;
        shouldn't happen in practice).
        """
        with self.lock:
            sess = self.sessions.get(agent_id)
            if sess is None:
                # Lazy session create — keeps a forgotten SessionStart
                # from dropping events on the floor.
                pk = self._lazy_session_locked(agent_id)
                sess = self.sessions[agent_id]
                sess["pk"] = pk
            sess["iter"] += 1
            self._touch()
            return sess["pk"], sess["iter"]

    def _lazy_session_locked(self, agent_id: str) -> int:
        now_ms = int(time.time() * 1000)
        cur = self.conn.execute(
            "INSERT INTO cr_sessions(agent_id, started_at) VALUES (?, ?)",
            (agent_id, now_ms),
        )
        pk = int(cur.lastrowid or 0)
        self.sessions[agent_id] = {
            "pk": pk,
            "iter": 0,
            "started_at": now_ms,
            "last_prompt_context_id": None,
            "last_rank_result": None,
            "last_rank_prompt": "",
        }
        return pk

    # ---------- recording events --------------------------------------

    def record_context(
        self,
        agent_id: str,
        kind: str,
        content: str,
        *,
        embed: bool = False,
    ) -> int:
        """Insert a cr_contexts row, optionally with the content embedding.

        Returns the inserted ``context_id`` so callers (notably
        ``_handle_prompt``) can correlate later events with this one.

        We embed *outside* the lock — fastembed is the slow step (5-50ms
        cold) and we don't want to hold the SQLite lock that long. The
        embedder itself is thread-safe (its own internal lock).

        ``embed`` is opt-in because most contexts (tool_call_pre, etc.)
        don't need to be searchable; only user prompts and assistant
        messages drive predictive ranking.

        For ``kind == "user_prompt"`` we update the session's
        ``last_prompt_context_id`` so that subsequent tool-call
        interactions inherit it as their turn anchor. The ranker then
        weights interactions by how many turns ago they happened.
        """
        session_pk, iteration = self.next_iteration(agent_id)
        emb_blob: bytes | None = None
        if embed and content.strip():
            try:
                vec = get_embedder().embed_query(content)
                emb_blob = vec_to_blob(vec)
            except Exception:  # pragma: no cover
                logger.exception("context embedding failed; storing without")
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO cr_contexts(session_id, kind, content, iteration, embedding, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_pk, kind, content, iteration, emb_blob, int(time.time() * 1000)),
            )
            ctx_id = int(cur.lastrowid or 0)
            if kind == "user_prompt":
                sess = self.sessions.get(agent_id)
                if sess is not None:
                    sess["last_prompt_context_id"] = ctx_id
            self._touch()
            return ctx_id

    def record_interaction(
        self,
        agent_id: str,
        event_type: str,
        target_kind: str,
        *,
        target_path: str | None = None,
        target_id: int | None = None,
        weight: float = 1.0,
    ) -> None:
        session_pk, iteration = self.next_iteration(agent_id)
        with self.lock:
            anchor_id = (self.sessions.get(agent_id) or {}).get("last_prompt_context_id")
            self.conn.execute(
                "INSERT INTO cr_interactions(session_id, context_id, iteration, event_type, "
                "target_kind, target_id, target_path, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_pk,
                    anchor_id,
                    iteration,
                    event_type,
                    target_kind,
                    target_id,
                    target_path,
                    weight,
                    int(time.time() * 1000),
                ),
            )
            self._touch()

    def invalidate_last_interaction(self, agent_id: str, target_path: str) -> None:
        """Drop the most-recent cr_interactions row for this session+target.

        Called from PostToolUse when the tool reported failure — keeping
        the row would let a failed Edit count as ``edit:2.0`` and pull a
        broken file into the rank. The pre/post pairing in Claude Code is
        strictly sequential per tool, so "most recent matching row" is
        always the one ``record_interaction`` just inserted in the pre.
        """
        sess = self.sessions.get(agent_id)
        if sess is None:
            return
        with self.lock:
            self.conn.execute(
                "DELETE FROM cr_interactions WHERE id = ("
                "  SELECT id FROM cr_interactions "
                "  WHERE session_id = ? AND target_path = ? "
                "  ORDER BY id DESC LIMIT 1"
                ")",
                (sess["pk"], target_path),
            )
            self._touch()

    # ---------- shutdown logic ----------------------------------------

    def _touch(self) -> None:
        self.last_activity = time.monotonic()

    def should_shutdown(self) -> str | None:
        """Reason string if it's time to exit, else None.

        Called from the shutdown-watcher thread every SHUTDOWN_TICK_S.
        Two reasons we'd shut down:
          1. Active sessions hit 0 and the grace period passed
             (claude windows closed → fast shutdown).
          2. No HTTP activity at all for IDLE_TIMEOUT_S
             (claude crashed without firing SessionEnd → fallback).
        """
        with self.lock:
            now = time.monotonic()
            if not self.sessions and self.empty_since is not None:
                if now - self.empty_since >= EMPTY_GRACE_S:
                    return f"empty for {now - self.empty_since:.0f}s"
            if now - self.last_activity >= IDLE_TIMEOUT_S:
                return f"idle for {now - self.last_activity:.0f}s"
        return None


# ---------- HTTP handler --------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server: "_ThreadingServer"

    # Silence the default per-request access log — we route everything
    # through the standard logger.
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib name
        logger.info("%s - %s", self.address_string(), fmt % args)

    # -------- routing --------

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorised():
            return
        if self.path == "/health":
            self._respond(200, self._health_payload())
            return
        self._respond(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorised():
            return
        body = self._read_body()
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            self._respond(400, {"error": f"bad json: {exc}"})
            return

        st = self.server.state
        try:
            if self.path == "/sessions/start":
                pk = st.session_start(payload["session_id"])
                self._respond(200, {"ok": True, "ken_session_pk": pk})
            elif self.path == "/sessions/end":
                _handle_session_end(st, payload["session_id"])
                self._respond(200, {"ok": True})
            elif self.path == "/prompts":
                content = str(payload.get("prompt", ""))
                block = _handle_prompt(st, payload["session_id"], content)
                self._respond(200, {"ok": True, "context_block": block})
            elif self.path == "/tools/pre":
                _record_tool_pre(st, payload)
                self._respond(200, {"ok": True})
            elif self.path == "/tools/post":
                _record_tool_post(st, payload)
                self._respond(200, {"ok": True})
            elif self.path == "/interactions/dismiss":
                _record_dismiss(st, payload)
                self._respond(200, {"ok": True})
            elif self.path == "/rank":
                self._respond(200, _handle_rank(st, payload))
            elif self.path == "/explain":
                self._respond(200, _handle_explain(st, payload))
            elif self.path == "/turn-end":
                _handle_turn_end(st, payload)
                self._respond(200, {"ok": True})
            elif self.path == "/shutdown":
                self._respond(200, {"ok": True})
                self.server.state.shutdown_event.set()
            else:
                self._respond(404, {"error": "not found"})
        except KeyError as exc:
            self._respond(400, {"error": f"missing field: {exc.args[0]}"})
        except Exception:  # pragma: no cover
            logger.exception("handler error")
            self._respond(500, {"error": "internal"})

    # -------- helpers --------

    def _authorised(self) -> bool:
        token = self.server.state.auth_token
        sent = self.headers.get("Authorization", "")
        if sent == f"Bearer {token}":
            return True
        self._respond(401, {"error": "unauthorised"})
        return False

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("client disconnected before response path=%s", self.path)

    def _health_payload(self) -> dict[str, Any]:
        st = self.server.state
        with st.lock:
            return {
                "ok": True,
                "project_id": _read_project_id(st.project_root),
                "sessions_active": len(st.sessions),
                "uptime_s": round(time.monotonic() - st.started_at, 1),
                "idle_s": round(time.monotonic() - st.last_activity, 1),
            }


def _handle_prompt(st: DaemonState, agent_id: str, content: str) -> str:
    """Record the prompt + run the ranker, return the formatted block.

    Embedding is computed inline inside ``record_context(embed=True)``;
    the ranker reuses it via a single round-trip — keeps the call to
    `get_embedder()` minimal (one inference per /prompts).

    The RankResult is cached on the session so the ``ken_rank`` MCP
    tool can re-render at a higher verbose level without re-running.
    """
    from ken.embedder import get_embedder
    from ken.ranker import rank
    from ken.ranker.output import render_block

    st.record_context(agent_id, "user_prompt", content, embed=True)
    if not content.strip():
        return ""
    try:
        prompt_vec = get_embedder().embed_query(content)
    except Exception:  # pragma: no cover
        logger.exception("prompt embedding failed during rank")
        return ""

    with st.lock:
        sess = st.sessions.get(agent_id)
        current_iter = sess["iter"] if sess else 0

    try:
        result = rank(
            st.conn,
            agent_id=agent_id,
            current_iteration=current_iter,
            prompt=content,
            prompt_embedding=prompt_vec,
            project_root=st.project_root,
        )
    except Exception:  # pragma: no cover
        logger.exception("ranker failed")
        return ""

    with st.lock:
        sess = st.sessions.get(agent_id)
        if sess is not None:
            sess["last_rank_result"] = result
            sess["last_rank_prompt"] = content

    return render_block(st.conn, result, verbose=0, max_chars=HOOK_CONTEXT_MAX_CHARS)


def _handle_rank(st: DaemonState, payload: dict[str, Any]) -> dict[str, Any]:
    """Re-render (or recompute) the ranker output at a chosen verbose level.

    Called by the ``ken_rank`` MCP tool. Two modes:

    * **No query / empty query** — re-render the cached last RankResult
      from the most-recent active session. Cheap; just changes how much
      detail is in the output.
    * **Query provided** — re-run the ranker with that query, against
      the same session's reactive context (so "what's hot in this
      session" still applies). Costs one embedding + one rank.
    """
    from ken.embedder import get_embedder
    from ken.ranker import rank as rank_fn
    from ken.ranker.output import render_block

    verbose_raw = payload.get("verbose", 1)
    try:
        verbose = int(verbose_raw)
    except (TypeError, ValueError):
        verbose = 1
    verbose = max(0, min(2, verbose))
    max_chars = _optional_positive_int(payload.get("max_chars"))
    query = str(payload.get("query") or "").strip()

    active = _active_rank_context(st)
    agent_id = active["agent_id"]
    cached_result = active["cached_result"]
    cached_prompt = active["cached_prompt"]
    current_iter = active["current_iter"]

    if not query:
        if cached_result is None:
            latest = _latest_prompt_context(st)
            if latest is None:
                return {
                    "ok": False,
                    "error": "no cached prompt — submit one or pass query",
                }
            agent_id = latest["agent_id"]
            query = latest["prompt"]
            current_iter = latest["current_iter"]
        else:
            block = render_block(
                st.conn, cached_result, verbose=verbose, max_chars=max_chars
            )
            stats = _context_stats(block)
            return {
                "ok": True,
                "context_block": block,
                "prompt": cached_prompt,
                "files": len(cached_result.files),
                "symbols": len(cached_result.symbols),
                "findings": len(cached_result.findings),
                **stats,
            }

    try:
        prompt_vec = get_embedder().embed_query(query)
    except Exception:  # pragma: no cover
        logger.exception("rank-on-demand embedding failed")
        return {"ok": False, "error": "embedder failed"}

    try:
        result = rank_fn(
            st.conn,
            agent_id=agent_id,
            current_iteration=current_iter,
            prompt=query,
            prompt_embedding=prompt_vec,
            project_root=st.project_root,
        )
    except Exception:  # pragma: no cover
        logger.exception("rank-on-demand failed")
        return {"ok": False, "error": "ranker failed"}

    block = render_block(st.conn, result, verbose=verbose, max_chars=max_chars)
    stats = _context_stats(block)
    return {
        "ok": True,
        "context_block": block,
        "prompt": query,
        "files": len(result.files),
        "symbols": len(result.symbols),
        "findings": len(result.findings),
        **stats,
    }


def _context_stats(block: str) -> dict[str, int]:
    """Cheap size telemetry for deciding when context is too noisy."""
    chars = len(block)
    # Four chars/token is the standard rough estimate for English/code
    # telemetry. It is intentionally approximate and model-agnostic.
    est_tokens = (chars + 3) // 4 if chars else 0
    return {"context_chars": chars, "context_est_tokens": est_tokens}


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _handle_session_end(st: DaemonState, agent_id: str) -> None:
    """End the session AND snapshot its productivity scores.

    Snapshot first (we still need the in-memory iteration counter),
    then drop the session from the active set.
    """
    from ken.ranker.snapshot import snapshot_session_scores

    with st.lock:
        sess = st.sessions.get(agent_id)
        current_iter = sess["iter"] if sess else 0

    try:
        n = snapshot_session_scores(st.conn, agent_id, current_iter)
        if n:
            logger.info("snapshotted %d session scores for agent_id=%s", n, agent_id)
    except Exception:  # pragma: no cover
        logger.exception("session_scores snapshot failed")

    st.session_end(agent_id)


def _handle_explain(st: DaemonState, payload: dict[str, Any]) -> dict[str, Any]:
    """Per-channel decomposition of the rank for *query* (or last prompt)."""
    from ken.embedder import get_embedder
    from ken.ranker.explain import explain

    query = str(payload.get("query") or "").strip()
    active = _active_rank_context(st)
    agent_id = active["agent_id"]
    cached_prompt = active["cached_prompt"]
    current_iter = active["current_iter"]

    target_prompt = query or cached_prompt
    if not target_prompt:
        latest = _latest_prompt_context(st)
        if latest is None:
            return {"ok": False, "error": "no cached prompt — submit one or pass query"}
        agent_id = latest["agent_id"]
        target_prompt = latest["prompt"]
        current_iter = latest["current_iter"]

    try:
        prompt_vec = get_embedder().embed_query(target_prompt)
    except Exception:  # pragma: no cover
        logger.exception("explain embedding failed")
        return {"ok": False, "error": "embedder failed"}

    try:
        result = explain(
            st.conn,
            agent_id=agent_id,
            current_iteration=current_iter,
            prompt=target_prompt,
            prompt_embedding=prompt_vec,
            project_root=st.project_root,
        )
    except Exception:  # pragma: no cover
        logger.exception("explain failed")
        return {"ok": False, "error": "explain failed"}

    result["ok"] = True
    return result


def _active_rank_context(st: DaemonState) -> dict[str, Any]:
    """Return in-memory rank context, or an inert fallback for MCP queries.

    MCP clients are not guaranteed to have lifecycle hooks installed or
    active. Query-based rank/explain still works without reactive session
    state, and empty-query calls can fall back to the last prompt stored
    in SQLite.
    """
    with st.lock:
        if not st.sessions:
            return {
                "agent_id": "__ken_mcp__",
                "cached_result": None,
                "cached_prompt": "",
                "current_iter": 0,
            }
        agent_id = next(reversed(st.sessions))
        sess = st.sessions[agent_id]
        return {
            "agent_id": agent_id,
            "cached_result": sess.get("last_rank_result"),
            "cached_prompt": sess.get("last_rank_prompt") or "",
            "current_iter": sess.get("iter", 0),
        }


def _latest_prompt_context(st: DaemonState) -> dict[str, Any] | None:
    """Return the most recent persisted user prompt, across sessions."""
    with st.lock:
        row = st.conn.execute(
            """
            SELECT s.agent_id, c.content, c.iteration
            FROM cr_contexts c
            JOIN cr_sessions s ON s.id = c.session_id
            WHERE c.kind = 'user_prompt' AND c.content <> ''
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return {
        "agent_id": row["agent_id"],
        "prompt": row["content"],
        "current_iter": int(row["iteration"] or 0),
    }


def _handle_turn_end(st: DaemonState, payload: dict[str, Any]) -> None:
    """Record turn-end with the assistant's response text + extract cites.

    Files mentioned in the assistant's reply (without necessarily being
    read or edited) are a strong "the model considered this" signal —
    they fire the ``cited`` pattern multiplier (2.5×). We scan the text
    for path-shaped tokens, validate against ci_files, and emit one
    ``cr_interactions(event_type='cited')`` per match.

    The text itself is also stored on a turn_end context so future
    sessions can semantic-match against past *responses*, not just past
    prompts.
    """
    agent_id = payload["session_id"]
    text = str(payload.get("assistant_text") or "")
    # Cap stored text to avoid bloating the DB on long replies.
    st.record_context(agent_id, "turn_end", text[:8000])
    if not text:
        return
    cited = _extract_cited_paths(st.conn, text)
    for path in cited:
        st.record_interaction(
            agent_id,
            event_type="cited",
            target_kind="file",
            target_path=path,
        )


def _extract_cited_paths(conn: sqlite3.Connection, text: str) -> list[str]:
    """Find indexed file paths mentioned in *text*.

    Two-pass match against ci_files:
      1. Exact path match (e.g. ``src/auth.py``).
      2. Bare filename → suffix match (e.g. ``auth.py`` → ``src/auth.py``)
         but only if exactly one ci_files entry suffix-matches; otherwise
         we don't know which file the assistant meant and skip it.
    """
    from ken.ranker.channels import _KNOWN_EXTS, _PATH_RE

    candidates: set[str] = set()
    for m in _PATH_RE.findall(text):
        base = m.split(":")[0]
        ext = base.rsplit(".", 1)[-1].lower()
        if ext not in _KNOWN_EXTS:
            continue
        candidates.add(base)
    if not candidates:
        return []

    full_paths = [c for c in candidates if "/" in c]
    bare_names = [c for c in candidates if "/" not in c]
    hits: set[str] = set()

    if full_paths:
        ph = ",".join("?" * len(full_paths))
        rows = conn.execute(
            f"SELECT path FROM ci_files WHERE path IN ({ph})",
            full_paths,
        ).fetchall()
        hits.update(r["path"] for r in rows)

    for name in bare_names:
        rows = conn.execute(
            "SELECT path FROM ci_files WHERE path LIKE ? LIMIT 2",
            (f"%/{name}",),
        ).fetchall()
        if len(rows) == 1:
            hits.add(rows[0]["path"])

    return sorted(hits)


def _record_dismiss(st: DaemonState, payload: dict[str, Any]) -> None:
    """Record a `dismissed` interaction for the active session.

    Called by the MCP `ken_dismiss` tool. We pick the *most recent*
    active session — there's almost always exactly one, and if the
    user has two claude windows open against the same project, the
    last to start wins (a heuristic that matches "the one the user
    is currently typing in" in practice).
    """
    target = payload.get("target")
    if not isinstance(target, str) or not target.strip():
        return
    with st.lock:
        if not st.sessions:
            logger.warning("dismiss received but no active session")
            return
        # `dict` preserves insertion order; the most recently started
        # session is the last key.
        agent_id = next(reversed(st.sessions))

    st.record_interaction(
        agent_id,
        event_type="dismissed",
        target_kind="file",
        target_path=target.strip(),
        weight=1.0,
    )
    reason = payload.get("reason") or ""
    if reason:
        st.record_context(
            agent_id,
            kind="dismiss_reason",
            content=f"{target}: {reason}",
        )


def _record_tool_pre(st: DaemonState, payload: dict[str, Any]) -> None:
    """Translate a Claude Code PreToolUse payload into a cr_interactions row.

    Tool → event_type mapping (matches infinidev's productivity-pattern
    semantics):
      Read / Glob / Grep            → "read"
      Edit / Write / MultiEdit      → "edit"
      Bash                           → "neutral" (no target)
    """
    agent_id = payload["session_id"]
    tool = str(payload.get("tool", payload.get("tool_name", "")))
    tool_input = payload.get("input") or payload.get("tool_input") or {}
    event_type, target_path = _classify_tool(tool, tool_input)
    st.record_context(
        agent_id,
        kind="tool_call_pre",
        content=json.dumps({"tool": tool, "target": target_path}, ensure_ascii=False),
    )
    if target_path is not None:
        st.record_interaction(
            agent_id,
            event_type=event_type,
            target_kind="file",
            target_path=target_path,
        )


def _record_tool_post(st: DaemonState, payload: dict[str, Any]) -> None:
    """Record the post phase. If the tool reported failure, retract the
    pre-phase interaction so a broken Read/Edit doesn't poison the rank.
    """
    agent_id = payload["session_id"]
    tool = str(payload.get("tool", payload.get("tool_name", "")))
    success = bool(payload.get("success", True))
    st.record_context(
        agent_id,
        kind="tool_call_post",
        content=json.dumps({"tool": tool, "success": success}, ensure_ascii=False),
    )
    if not success:
        tool_input = payload.get("input") or payload.get("tool_input") or {}
        target = _extract_target(tool_input)
        if target:
            st.invalidate_last_interaction(agent_id, target)


def _classify_tool(tool: str, tool_input: Any) -> tuple[str, str | None]:
    name = _canonical_tool_name(tool)
    if name in {"read", "glob", "grep"}:
        target = _extract_target(tool_input)
        return "read", target
    if name in {"edit", "write", "multiedit", "apply_patch"}:
        target = _extract_target(tool_input)
        return "edit", target
    if name in {"bash", "exec_command"}:
        target = _extract_target(tool_input)
        return ("read", target) if target else ("neutral", None)
    return "neutral", _extract_target(tool_input)


def _canonical_tool_name(tool: str) -> str:
    name = tool.strip().lower()
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    if name == "functions.apply_patch":
        return "apply_patch"
    if name == "functions.exec_command":
        return "exec_command"
    return name


def _extract_target(tool_input: Any) -> str | None:
    """Pull the file path out of a tool input dict.

    Claude Code's tool inputs use a small set of field names:
      * Read / Edit / Write: ``file_path``
      * Glob: ``pattern`` (we surface the pattern as path-ish)
      * Grep: ``path`` for scope, ``pattern`` for regex — we use ``path``
    """
    if isinstance(tool_input, str):
        return _extract_path_from_text(tool_input)
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path"):
        if key in tool_input and isinstance(tool_input[key], str):
            return tool_input[key]
    for key in ("cmd", "command", "patch"):
        if key in tool_input and isinstance(tool_input[key], str):
            target = _extract_path_from_text(tool_input[key])
            if target:
                return target
    if "workdir" in tool_input and isinstance(tool_input["workdir"], str):
        return tool_input["workdir"]
    return None


def _extract_path_from_text(text: str) -> str | None:
    """Pull the first source-like path token out of shell or patch text."""
    from ken.ranker.channels import _KNOWN_EXTS, _PATH_RE

    for match in _PATH_RE.findall(text):
        base = match.split(":", 1)[0]
        ext = base.rsplit(".", 1)[-1].lower()
        if ext in _KNOWN_EXTS:
            return base
    return None


# ---------- server lifecycle -------------------------------------------


class _ThreadingServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that carries the shared DaemonState."""

    daemon_threads = True  # die with the main thread on shutdown

    def __init__(self, addr: tuple[str, int], state: DaemonState) -> None:
        super().__init__(addr, _Handler)
        self.state = state


def run(project_root: Path) -> int:
    """Daemon entrypoint. Binds a free localhost port, advertises it via
    ``.ken/daemon.port``, serves until idle / empty / explicit shutdown.
    """
    project_root = project_root.resolve()
    meta_p = _paths.meta_path(project_root)
    if not meta_p.is_file():
        print(f"ken: no .ken/meta.json at {project_root}", flush=True)
        return 2
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    state = DaemonState(project_root, meta["auth_token"])
    set_meta(state.conn, "ken_version", _ken_version())

    server = _ThreadingServer(("127.0.0.1", 0), state)
    bound_port = server.server_address[1]
    _write_runtime_files(project_root, port=bound_port, pid=os.getpid())

    logger.info(
        "ken daemon ready project_root=%s pid=%s port=%s",
        project_root,
        os.getpid(),
        bound_port,
    )

    # Start accepting HTTP before background maintenance. On very large
    # repositories the warm pass can take longer than the hook client's
    # spawn wait; serving first keeps /health responsive and prevents a
    # false "daemon unreachable" on first prompt.
    sd_watcher = threading.Thread(target=_shutdown_watcher, args=(state,), daemon=True)
    sd_watcher.start()
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    maintenance: dict[str, Any] = {}
    maintenance_thread = threading.Thread(
        target=_maintenance_loop,
        args=(state, maintenance),
        name="ken-maintenance-startup",
        daemon=True,
    )
    maintenance_thread.start()

    state.shutdown_event.wait()
    logger.info("ken daemon shutting down")
    _finalize_active_sessions(state)
    server.shutdown()
    server.server_close()
    file_watcher = maintenance.get("file_watcher")
    if file_watcher is not None:
        file_watcher.stop()
    index_queue = maintenance.get("index_queue")
    if index_queue is not None:
        index_queue.stop()
    maintenance_thread.join(timeout=5.0)
    state.conn.close()
    _clear_runtime_files(project_root)
    return 0


def _maintenance_loop(state: DaemonState, holder: dict[str, Any]) -> None:
    if state.shutdown_event.wait(MAINTENANCE_START_DELAY_S):
        return

    project_root = state.project_root
    # Index queue + file watcher run in their own threads with their own
    # SQLite connections. We start the queue first so the watcher's first
    # events have a worker to hand off to.
    #
    # The embedder is the *singleton* — `get_embedder()` returns the same
    # instance the request handlers use for cr_contexts embeddings, so we
    # only pay one model-load cost per process.
    index_queue = IndexQueue(project_root, embedder=get_embedder())
    if state.shutdown_event.is_set():
        return
    index_queue.start()
    holder["index_queue"] = index_queue

    file_watcher = FileWatcher(project_root, index_queue)
    file_watcher.start()
    holder["file_watcher"] = file_watcher

    # Warm pass: enqueue every gitignore-respecting file. The indexer
    # short-circuits on content_hash so this is cheap on a clean DB —
    # but it catches anything that changed while the daemon was dead
    # (between sessions, after a `git pull`, …).
    warm_count = 0
    for rel in iter_files(project_root):
        if state.shutdown_event.is_set():
            break
        index_queue.reindex(rel.as_posix())
        warm_count += 1
    logger.info("warm pass: queued %s files for hash-skip / reindex", warm_count)


def _shutdown_watcher(state: DaemonState) -> None:
    while not state.shutdown_event.is_set():
        if state.shutdown_event.wait(SHUTDOWN_TICK_S):
            return
        reason = state.should_shutdown()
        if reason is not None:
            logger.info("shutdown trigger: %s", reason)
            state.shutdown_event.set()
            return


def _finalize_active_sessions(state: DaemonState) -> None:
    """Snapshot and close any sessions still active when the daemon exits."""
    with state.lock:
        agent_ids = list(state.sessions)
    for agent_id in agent_ids:
        _handle_session_end(state, agent_id)


def _write_runtime_files(project_root: Path, *, port: int, pid: int) -> None:
    _paths.port_path(project_root).write_text(str(port), encoding="utf-8")
    _paths.pid_path(project_root).write_text(str(pid), encoding="utf-8")


def _clear_runtime_files(project_root: Path) -> None:
    for p in (_paths.port_path(project_root), _paths.pid_path(project_root)):
        try:
            p.unlink()
        except OSError:
            pass


def _read_project_id(project_root: Path) -> str:
    try:
        meta = json.loads(_paths.meta_path(project_root).read_text(encoding="utf-8"))
        return str(meta.get("project_id", "?"))
    except OSError:
        return "?"


def _ken_version() -> str:
    from ken import __version__

    return __version__
