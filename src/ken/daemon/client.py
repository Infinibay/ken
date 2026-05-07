"""Client used by hook commands to talk to the daemon.

A hook lifecycle is:

    1. Find project root via walk-up.
    2. Look for `.ken/daemon.port`.
       - exists + responsive  → use it.
       - exists but stale     → spawn a fresh daemon.
       - missing              → spawn one.
    3. POST event, return the response (or None on failure — hooks must
       *never* fail Claude Code; logging-and-shrugging is the contract).

Spawning is detached: the daemon outlives the hook process via
``start_new_session=True`` and stdio redirected to a log file. The hook
then polls `.ken/daemon.port` for up to 5 seconds.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ken import _paths

# How long a hook will wait for a freshly-spawned daemon before giving up.
SPAWN_POLL_TIMEOUT_S = 5.0
SPAWN_POLL_INTERVAL_S = 0.05

# Hook → daemon timeouts. Reads/health small; POSTs slightly bigger to
# tolerate a brief lock-contention spike when many hooks fire at once.
HEALTH_TIMEOUT_S = 1.0
POST_TIMEOUT_S = 3.0

logger = logging.getLogger("ken.client")


class DaemonUnreachable(RuntimeError):
    """Raised when even after a spawn the daemon doesn't come up."""


def post(project_root: Path, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """POST *payload* as JSON to *path* on the daemon. Spawns one if needed.

    Returns the parsed JSON response, or ``None`` if every attempt failed
    (so callers can fall back to silent degradation).
    """
    try:
        return _post_with_spawn(project_root, path, payload)
    except DaemonUnreachable as exc:
        logger.warning("daemon unreachable for %s: %s", path, exc)
        return None
    except Exception:  # pragma: no cover
        logger.exception("daemon POST %s failed", path)
        return None


def health(project_root: Path) -> dict[str, Any] | None:
    """GET /health. Returns parsed JSON or None — never raises."""
    port = _read_port(project_root)
    if port is None:
        return None
    try:
        return _request("GET", project_root, port, "/health", body=None, timeout=HEALTH_TIMEOUT_S)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


# ---------- internals ----------


def _post_with_spawn(project_root: Path, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    port = _read_port(project_root)
    if port is not None:
        try:
            return _request("POST", project_root, port, path, body=payload, timeout=POST_TIMEOUT_S)
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            # Stale port file (daemon crashed without cleanup).  Spawn a
            # fresh one and retry once.
            logger.info("port %s unresponsive; respawning daemon", port)
            _clear_port_file(project_root)

    spawned_port = _spawn_and_wait(project_root)
    return _request("POST", project_root, spawned_port, path, body=payload, timeout=POST_TIMEOUT_S)


def _spawn_and_wait(project_root: Path) -> int:
    """Detach a daemon process and wait for `.ken/daemon.port` to appear."""
    log_p = _paths.log_path(project_root)
    log_p.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_p.open("ab")
    # We use sys.executable to avoid a PATH lookup race when running
    # under uv tool / pipx; a console script wrapper would also work but
    # this is the most portable. ``-m ken`` invokes the package's
    # __main__ → cli.main.
    cmd = [sys.executable, "-m", "ken", "serve", str(project_root), "--background"]
    subprocess.Popen(  # noqa: S603 — args are literal/local-controlled
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(project_root),
        env={**os.environ, "KEN_PROJECT_ROOT": str(project_root)},
    )
    # Don't keep the parent's handle open — daemon dup'd it.
    log_handle.close()

    deadline = time.monotonic() + SPAWN_POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        port = _read_port(project_root)
        if port is not None:
            # Port file written; one more health check before declaring win.
            try:
                if _request("GET", project_root, port, "/health", body=None, timeout=HEALTH_TIMEOUT_S):
                    return port
            except Exception:  # pragma: no cover
                pass
        time.sleep(SPAWN_POLL_INTERVAL_S)
    raise DaemonUnreachable(f"daemon did not come up within {SPAWN_POLL_TIMEOUT_S}s")


def _read_port(project_root: Path) -> int | None:
    p = _paths.port_path(project_root)
    if not p.is_file():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _clear_port_file(project_root: Path) -> None:
    try:
        _paths.port_path(project_root).unlink()
    except OSError:
        pass


def _read_token(project_root: Path) -> str:
    meta = json.loads(_paths.meta_path(project_root).read_text(encoding="utf-8"))
    return str(meta["auth_token"])


def _request(
    method: str,
    project_root: Path,
    port: int,
    path: str,
    *,
    body: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {"Authorization": f"Bearer {_read_token(project_root)}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — localhost-only
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}
