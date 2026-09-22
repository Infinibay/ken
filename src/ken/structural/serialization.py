"""Serialize IR in bounded batches without cloning the whole object graph."""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import fields
from functools import lru_cache
from itertools import islice
from sys import getsizeof
from typing import Any, TypeVar

from .model import IR

T = TypeVar("T")


@lru_cache(maxsize=8)
def _field_names(kind: type) -> tuple[str, ...]:
    return tuple(field.name for field in fields(kind))


def _record(value: Any) -> dict[str, Any]:
    return {name: getattr(value, name) for name in _field_names(value.__class__)}


def _json(value: Any) -> bytes:
    return json.dumps(
        value, default=_record, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _batches(values: Iterable[T], size: int = 512) -> Iterator[list[T]]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


def compressed_ir(ir: IR) -> bytes:
    """The existing JSON/zlib cache format, with only one small JSON batch live.

    Public ``IR.to_dict`` retains its independent-copy contract. Cache writes
    instead read the immutable snapshot directly; large entity/fact/operation
    collections go through the fast JSON encoder a bounded batch at a time.
    """
    compressor = zlib.compressobj()
    chunks: list[bytes] = []

    def write(data: bytes) -> None:
        compressed = compressor.compress(data)
        if compressed:
            chunks.append(compressed)

    write(b"{")
    for position, field in enumerate(fields(ir)):
        if position:
            write(b",")
        write(_json(field.name) + b":")
        value = getattr(ir, field.name)
        if field.name in {"entities", "operations", "facts"}:
            mapping = field.name == "entities"
            write(b"{" if mapping else b"[")
            for batch_number, batch in enumerate(
                _batches(value.items() if mapping else value)
            ):
                if batch_number:
                    write(b",")
                write(_json(dict(batch) if mapping else batch)[1:-1])
            write(b"}" if mapping else b"]")
        else:
            write(_json(sorted(value) if isinstance(value, set) else value))
    write(b"}")
    chunks.append(compressor.flush())
    return b"".join(chunks)


class _StringPool:
    """Share immutable JSON strings within one cache read, with bounded memory.

    Node IDs, paths and tokens recur in many facts. JSON otherwise allocates a
    separate string for every occurrence. Containers remain independent and
    the pool is discarded after decoding; it never retains previous projects.
    """

    def __init__(self, max_entries: int = 131_072, max_bytes: int = 16_000_000):
        self.strings: dict[str, str] = {}
        self.max_entries = max_entries
        self.remaining_bytes = max_bytes

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            existing = self.strings.get(value)
            if existing is not None:
                return existing
            if len(self.strings) < self.max_entries and self.remaining_bytes > 0:
                size = getsizeof(value)
                if size <= self.remaining_bytes:
                    self.strings[value] = value
                    self.remaining_bytes -= size
        elif isinstance(value, list):
            for position, item in enumerate(value):
                value[position] = self.value(item)
        return value

    def object(self, value: dict[str, Any]) -> dict[str, Any]:
        return {self.value(key): self.value(item) for key, item in value.items()}


def decoded_json(payload: bytes) -> Any:
    """Decode the compatible cache format without duplicating identifier text."""
    return json.loads(payload, object_hook=_StringPool().object)
