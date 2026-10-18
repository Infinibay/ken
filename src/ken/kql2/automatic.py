"""Shared CLI/MCP client of the project's persistent prepared query service."""

from __future__ import annotations

import json
import fcntl
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ken._paths import resolve_project_path
from ken.structural_store.store import MIN_PERSISTENT_MB

from .compilation import implementation_fingerprint
from .execution_control import ExecutionBudget
from .host import retention
from .session import PersistentStorageRequired

IMPLEMENTATION = implementation_fingerprint()
STARTUP_TIMEOUT_S = 10.0
REQUEST_TIMEOUT_S = 300.0


def runtime_path(root: Path) -> Path:
    return root / '.ken/structural/v2/queries.json'


def _endpoint(root: Path) -> dict[str, Any] | None:
    try:
        endpoint = json.loads(runtime_path(root).read_text())
        if not isinstance(endpoint['port'], int) or not isinstance(endpoint['token'], str):
            return None
        return endpoint
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _wire(endpoint: dict[str, Any], message: dict[str, Any], *, timeout: float = REQUEST_TIMEOUT_S) -> dict[str, Any]:
    payload = json.dumps({**message, 'token':endpoint['token']}, separators=(',', ':')).encode() + b'\n'
    with socket.create_connection(('127.0.0.1', endpoint['port']), timeout=timeout) as connection:
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.sendall(payload)
        with connection.makefile('rb') as incoming:
            line = incoming.readline()
        if not line:
            raise ConnectionError('prepared query service closed without a response')
    response = json.loads(line)
    if 'error' in response:
        if response['error']['kind'] == 'PersistentStorageRequired':
            raise PersistentStorageRequired(response['error']['message'])
        if response['error']['kind'] in {'ValueError', 'CompileError', 'ParseError', 'TypeError'}:
            raise ValueError(response['error']['message'])
        raise RuntimeError(response['error']['message'])
    return response


def _ensure(root: Path, failed: dict[str, Any] | None = None) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    endpoint = _endpoint(root)
    if endpoint is not None and endpoint != failed and endpoint.get('implementation') == IMPLEMENTATION:
        return endpoint, 0.0
    directory = runtime_path(root).parent
    directory.mkdir(parents=True, exist_ok=True)
    # Every client restart uses this lock; a stale client may not remove an
    # endpoint another startup has already published.
    with (directory / 'queries.start.lock').open('ab') as startup:
        fcntl.flock(startup.fileno(), fcntl.LOCK_EX)
        endpoint = _endpoint(root)
        if endpoint is not None and endpoint != failed and endpoint.get('implementation') == IMPLEMENTATION:
            return endpoint, (time.monotonic() - started) * 1000
        if endpoint is not None:
            try:
                _wire(endpoint, {'action':'shutdown'}, timeout=1)
            except OSError:
                pass
            if _endpoint(root) == endpoint:
                runtime_path(root).unlink(missing_ok=True)
        process = None
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if process is None or process.poll() is not None:
                with (directory / 'queries.log').open('ab') as log:
                    process = subprocess.Popen(
                        [sys.executable, '-m', 'ken.kql2.worker', str(root)],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        cwd=root, start_new_session=True,
                    )
            endpoint = _endpoint(root)
            if endpoint is not None and endpoint.get('implementation') == IMPLEMENTATION:
                try:
                    _wire(endpoint, {'action':'health'}, timeout=.5)
                    return endpoint, (time.monotonic() - started) * 1000
                except OSError:
                    pass
            time.sleep(.02)
    raise RuntimeError('prepared query service did not start; see .ken/structural/v2/queries.log')


def search(root: Path, source: str | None = None, *, saved_query: str | None = None, backend: str = 'indexed',
           cache_directory: Path | None = None, cache_mb: float | None = None,
           timeout_ms: float | None = None, **options: Any) -> dict[str, Any]:
    """Automatically wait for current inputs, then query a reusable owner."""
    started = time.monotonic()
    from .module_inputs import validate_entry

    validate_entry(source, saved_query)
    if saved_query is not None:
        options = {**options, 'saved_query': saved_query}
    ExecutionBudget(timeout_ms, options.get('max_states'), options.get('max_rows'))
    root = root.resolve()
    if not root.is_dir():
        raise ValueError('project root does not exist or is not a directory')
    target = resolve_project_path(root, options.get('path', '.'))
    if not target.exists():
        raise ValueError('query path does not exist')
    budget = retention(root, cache_mb)
    disk_budget = budget - min(budget / 5, 100)
    if backend != 'indexed' or disk_budget < MIN_PERSISTENT_MB:
        from .service import search as one_shot

        return one_shot(root, source, backend=backend, cache_directory=cache_directory,
                        cache_mb=cache_mb, timeout_ms=timeout_ms, **options)
    if cache_directory is not None:
        raise ValueError('cache_directory requires the exploration backend')
    endpoint, startup_ms = _ensure(root)
    message: dict[str, Any] = {'action':'query', 'source':source,
               'options':{**options, 'cache_mb':budget, 'timeout_ms':timeout_ms,
                          'arrived_at':started + startup_ms / 1000}}
    try:
        try:
            response = _wire(endpoint, message)
        except ConnectionError:
            # A dead owner is restarted; a timed-out live request is never replayed.
            endpoint, restart_ms = _ensure(root, failed=endpoint)
            startup_ms += restart_ms
            message['options']['arrived_at'] = started + startup_ms / 1000
            response = _wire(endpoint, message)
    except PersistentStorageRequired:
        from .service import search as one_shot

        attempt_ms = (time.monotonic() - started) * 1000 - startup_ms
        result = one_shot(root, source, cache_mb=budget, timeout_ms=timeout_ms, **options)
        result['analysis'].update(total_ms=(time.monotonic() - started) * 1000,
                                  startup_ms=startup_ms, session_attempt_ms=attempt_ms)
        return result
    result = response['result']
    analysis = result['analysis']
    total_ms = (time.monotonic() - started) * 1000
    prepared_ms = total_ms - startup_ms - analysis['preparation_ms'] - analysis.get('index_wait_ms', 0.0)
    analysis.update(server_ms=analysis['total_ms'], total_ms=total_ms,
                    startup_ms=startup_ms, prepared_query_ms=prepared_ms)
    if timeout_ms is not None and prepared_ms >= timeout_ms and result['complete']:
        result['complete'], result['reason'] = False, 'timeout'
    return result


def shutdown(root: Path) -> None:
    """Close readers in their owner before stopping a project's query service."""
    root = root.resolve()
    endpoint = _endpoint(root)
    if endpoint is None:
        return
    try:
        _wire(endpoint, {'action':'shutdown'}, timeout=5)
    except (OSError, ConnectionError):
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _endpoint(root) == endpoint:
        time.sleep(.01)
