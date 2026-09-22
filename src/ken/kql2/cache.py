"""Byte-bounded LRU for immutable compilation artifacts, with single-flight.

Retention is separate from callers' working references. Failed computations are
never cached; all waiters see the failure and a later call can retry.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import fields, is_dataclass
import sys
from threading import RLock
from typing import Callable, Generic, TypeVar
from collections.abc import Mapping

T = TypeVar('T')


def retained_size(value: object) -> int:
    """Conservative object graph accounting, including slot-backed syntax nodes."""
    seen: set[int] = set()
    pending = [value]
    total = 0
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(item)
        if is_dataclass(item) and not isinstance(item, type):
            if hasattr(item,'__dict__'):
                pending.append(vars(item))
            pending.extend(getattr(item, field.name) for field in fields(item))
        elif isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (tuple, list, set, frozenset)):
            pending.extend(item)
    return total


class ArtifactCache(Generic[T]):
    def __init__(self, max_bytes: int):
        self._lock = RLock()
        self._entries: OrderedDict[str, tuple[T, int]] = OrderedDict()
        self._running: dict[tuple[int, str], Future[T]] = {}
        self._epoch = 0
        self.max_bytes = max(0, max_bytes)
        self.bytes = 0
        self.hits = self.misses = self.waits = self.evictions = 0

    def configure(self, max_bytes: int) -> None:
        if max_bytes < 0:
            raise ValueError('cache capacity must be nonnegative')
        with self._lock:
            self.max_bytes = max_bytes
            if not max_bytes:
                # A computation started under an earlier enabled configuration
                # must not repopulate the cache after clear/disable.
                self._epoch += 1
            self._evict()

    def clear(self) -> None:
        with self._lock:
            self._epoch += 1
            self._entries.clear()
            self.bytes = 0

    def _evict(self) -> None:
        while self._entries and self.bytes > self.max_bytes:
            _, (_, size) = self._entries.popitem(last=False)
            self.bytes -= size
            self.evictions += 1

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> tuple[T, str]:
        with self._lock:
            if not self.max_bytes:
                disabled = True
            else:
                disabled = False
                entry = self._entries.get(key)
                if entry is not None:
                    self._entries.move_to_end(key)
                    self.hits += 1
                    return entry[0], 'hit'
                flight_key = self._epoch, key
                future = self._running.get(flight_key)
                leader = future is None
                if leader:
                    future = Future()
                    self._running[flight_key] = future
                    self.misses += 1
                else:
                    self.waits += 1
        if disabled:
            return compute(), 'disabled'
        assert future is not None
        if not leader:
            return future.result(), 'shared'
        try:
            result = compute()
            # Count the key, object graph and a conservative LRU-entry overhead.
            size = retained_size(result) + sys.getsizeof(key) + 256
            with self._lock:
                if flight_key[0] == self._epoch and size <= self.max_bytes:
                    self._entries[key] = result, size
                    self.bytes += size
                    self._evict()
                self._running.pop(flight_key, None)
            future.set_result(result)
            return result, 'miss'
        except BaseException as exc:
            with self._lock:
                self._running.pop(flight_key, None)
            future.set_exception(exc)
            raise

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {'retained_bytes': self.bytes, 'capacity_bytes': self.max_bytes,
                    'entries':len(self._entries), 'hits':self.hits,'misses':self.misses,
                    'shared':self.waits,'evictions':self.evictions,'in_flight':len(self._running)}
