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
            self.sessions[agent_id] = {"pk": pk, "iter": 0, "started_at": now_ms}
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
        self.sessions[agent_id] = {"pk": pk, "iter": 0, "started_at": now_ms}
        return pk

    # ---------- recording events --------------------------------------

    def record_context(
        self,
        agent_id: str,
        kind: str,
        content: str,
    ) -> None:
        session_pk, iteration = self.next_iteration(agent_id)
        with self.lock:
            self.conn.execute(
                "INSERT INTO cr_contexts(session_id, kind, content, iteration, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_pk, kind, content, iteration, int(time.time() * 1000)),
            )
            self._touch()

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
            self.conn.execute(
                "INSERT INTO cr_interactions(session_id, iteration, event_type, target_kind, "
                "target_id, target_path, weight, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_pk,
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
                st.session_end(payload["session_id"])
                self._respond(200, {"ok": True})
            elif self.path == "/prompts":
                content = str(payload.get("prompt", ""))
                st.record_context(payload["session_id"], "user_prompt", content)
                # Phase 5 will compute the actual ranking. For now, no
                # injection — the hook prints nothing extra to stdout.
                self._respond(200, {"ok": True, "context_block": ""})
            elif self.path == "/tools/pre":
                _record_tool_pre(st, payload)
                self._respond(200, {"ok": True})
            elif self.path == "/tools/post":
                _record_tool_post(st, payload)
                self._respond(200, {"ok": True})
            elif self.path == "/turn-end":
                # Phase 5: snapshot session_scores. For now just touch.
                st.record_context(payload["session_id"], "turn_end", "")
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
    agent_id = payload["session_id"]
    tool = str(payload.get("tool", payload.get("tool_name", "")))
    success = bool(payload.get("success", True))
    st.record_context(
        agent_id,
        kind="tool_call_post",
        content=json.dumps({"tool": tool, "success": success}, ensure_ascii=False),
    )


def _classify_tool(tool: str, tool_input: dict[str, Any]) -> tuple[str, str | None]:
    name = tool.lower()
    if name in {"read", "glob", "grep"}:
        target = _extract_target(tool_input)
        return "read", target
    if name in {"edit", "write", "multiedit"}:
        target = _extract_target(tool_input)
        return "edit", target
    return "neutral", None


def _extract_target(tool_input: dict[str, Any]) -> str | None:
    """Pull the file path out of a tool input dict.

    Claude Code's tool inputs use a small set of field names:
      * Read / Edit / Write: ``file_path``
      * Glob: ``pattern`` (we surface the pattern as path-ish)
      * Grep: ``path`` for scope, ``pattern`` for regex — we use ``path``
    """
    for key in ("file_path", "path"):
        if key in tool_input and isinstance(tool_input[key], str):
            return tool_input[key]
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

    # Index queue + file watcher run in their own threads with their own
    # SQLite connections. We start the queue first so the watcher's first
    # events have a worker to hand off to.
    index_queue = IndexQueue(project_root)
    index_queue.start()

    file_watcher = FileWatcher(project_root, index_queue)
    file_watcher.start()

    # Warm pass: enqueue every gitignore-respecting file. The indexer
    # short-circuits on content_hash so this is cheap on a clean DB —
    # but it catches anything that changed while the daemon was dead
    # (between sessions, after a `git pull`, …).
    warm_count = 0
    for rel in iter_files(project_root):
        index_queue.reindex(rel.as_posix())
        warm_count += 1
    logger.info("warm pass: queued %s files for hash-skip / reindex", warm_count)

    # Idle/empty shutdown watcher and the HTTP serve loop.
    sd_watcher = threading.Thread(target=_shutdown_watcher, args=(state,), daemon=True)
    sd_watcher.start()
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    state.shutdown_event.wait()
    logger.info("ken daemon shutting down")
    server.shutdown()
    server.server_close()
    file_watcher.stop()
    index_queue.stop()
    state.conn.close()
    _clear_runtime_files(project_root)
    return 0


def _shutdown_watcher(state: DaemonState) -> None:
    while not state.shutdown_event.is_set():
        if state.shutdown_event.wait(SHUTDOWN_TICK_S):
            return
        reason = state.should_shutdown()
        if reason is not None:
            logger.info("shutdown trigger: %s", reason)
            state.shutdown_event.set()
            return


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
