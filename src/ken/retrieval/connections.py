"""Bound persistent search connections so source/vector caches have a useful lifetime."""
from __future__ import annotations

import atexit
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading

from ken.db import connect

_connections: OrderedDict[tuple[str, int, int], sqlite3.Connection] = OrderedDict()
_lock = threading.RLock()


@contextmanager
def project_connection(root: Path) -> Iterator[sqlite3.Connection]:
    """Share a serial search connection; every search still opens a fresh WAL snapshot."""
    database = (root/'.ken'/'ken.db').resolve()
    stat = database.stat()
    key = (str(database), stat.st_dev, stat.st_ino)
    with _lock:
        if key not in _connections:
            _connections[key] = connect(database)
        _connections.move_to_end(key)
        while len(_connections) > 2:
            _, expired = _connections.popitem(last=False)
            expired.close()
        yield _connections[key]


@atexit.register
def close_search_connections() -> None:
    with _lock:
        for connection in _connections.values():
            connection.close()
        _connections.clear()
