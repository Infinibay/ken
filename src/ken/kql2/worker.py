"""A lightweight, authenticated local service; one thread owns all query readers."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import secrets
import select
import socket
import socketserver
import sys
import time
from pathlib import Path
from typing import Any

from .automatic import IMPLEMENTATION, runtime_path
from .host import QueryHost
from .process import prepare_process

IDLE_SECONDS = 600.0
logger = logging.getLogger('ken.kql2.worker')


def client_disconnected(connection: socket.socket) -> bool:
    """Read EOF without consuming the request or waiting on an open client."""
    try:
        readable, _, _ = select.select([connection], [], [], 0)
        return bool(readable) and connection.recv(1, socket.MSG_PEEK) == b''
    except (OSError, ValueError):
        return True


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        self.connection.settimeout(10)
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        response: dict[str, Any]
        try:
            request = json.loads(self.rfile.readline())
            if not secrets.compare_digest(str(request.get('token', '')), self.server.token):
                raise ValueError('unauthorised query request')
            self.server.last_activity = time.monotonic()
            action = request['action']
            if action == 'query':
                from .request import cancellable
                with cancellable(lambda: client_disconnected(self.connection)):
                    response = {'result':self.server.host.search(request['source'], **request.get('options', {}))}
            elif action == 'health':
                response = {'ok':True, 'pid':os.getpid()}
            elif action == 'shutdown':
                response = {'ok':True}
                self.server.closing = True
            else:
                raise ValueError('unknown query service action')
        except Exception as exc:
            response = {'error':{'kind':type(exc).__name__, 'message':str(exc)}}
        try:
            self.wfile.write(json.dumps(response, separators=(',', ':')).encode() + b'\n')
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Server(socketserver.TCPServer):
    """Serial requests preserve SQLite ownership; watchers only invalidate."""

    def __init__(self, root: Path, token: str):
        self.host = QueryHost(root)
        self.token = token
        self.last_activity = time.monotonic()
        self.closing = False
        try:
            super().__init__(('127.0.0.1', 0), _Handler)
        except BaseException:
            self.host.close()
            raise
        self.timeout = .25

    def handle_timeout(self) -> None:
        try:
            self.host.maintain()
        except Exception:
            logger.exception('query index maintenance failed; retrying on next request')


def run(root: Path) -> int:
    root = root.resolve()
    runtime = runtime_path(root)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    prepare_process(freeze=True)
    with (runtime.parent / 'queries.lock').open('ab') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # Another startup won; clients discover its endpoint.
        with _Server(root, token) as server:
            endpoint = {'port':server.server_address[1], 'token':token,
                        'pid':os.getpid(), 'implementation':IMPLEMENTATION}
            temporary = runtime.with_suffix('.next')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w') as file:
                json.dump(endpoint, file)
            temporary.replace(runtime)
            try:
                while not server.closing and time.monotonic() - server.last_activity < IDLE_SECONDS:
                    server.handle_request()
            finally:
                try:
                    server.host.close()
                finally:
                    if runtime.exists() and json.loads(runtime.read_text()).get('token') == token:
                        runtime.unlink()
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(run(Path(sys.argv[1])))
