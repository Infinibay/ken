"""Versioned FlatBuffers syntax vectors, validated before execution.

The adapter uses the official Builder/Table APIs for the adjacent ast.fbs.
Anonymous tokens and source field roles are retained; query scans expose named
nodes. Views are read-only and retain their immutable owning buffer.
"""

from __future__ import annotations

import struct
from array import array

import flatbuffers
import numpy as np
from flatbuffers import number_types as N
from flatbuffers.table import Table

FIELDS = ("kind", "role", "parent", "subtree_end", "start_byte", "end_byte", "flags")
DTYPES = ("<u2", "<u2", "<i4", "<u4", "<u4", "<u4", "u1")
FLAGS = (
    N.Uint16Flags,
    N.Uint16Flags,
    N.Int32Flags,
    N.Uint32Flags,
    N.Uint32Flags,
    N.Uint32Flags,
    N.Uint8Flags,
)


class Dictionary:
    def __init__(self):
        self.words = [""]
        self.ids = {"": 0}

    def intern(self, value):
        ident = self.ids.get(value)
        if ident is None:
            if len(self.words) >= 65536:
                raise ValueError("syntax dictionary exceeded uint16")
            ident = len(self.words)
            self.ids[value] = ident
            self.words.append(value)
        return ident


def flatten(tree, dictionary, check=lambda: None):
    """Iterative cursor walk, with one live tree and bounded depth stack."""
    data = [array(code) for code in ("H", "H", "i", "I", "I", "I", "B")]
    # Bind append methods once. This loop visits every token in the repository;
    # constructing/zipping a seven-item row per node dominates cold acquisition.
    add_kind, add_role, add_parent, add_end, add_start, add_stop, add_flags = (
        column.append for column in data
    )
    intern = dictionary.intern
    cursor = tree.walk()
    stack = []
    while True:
        node = cursor.node
        ident = len(data[0])
        if ident % 1024 == 0:
            check()
        add_kind(intern(node.type))
        add_role(intern(cursor.field_name or ""))
        add_parent(stack[-1] if stack else -1)
        add_end(0)
        add_start(node.start_byte)
        add_stop(node.end_byte)
        add_flags(
            node.is_named
            | (node.has_error << 1)
            | (node.is_missing << 2)
            | (node.is_error << 3)
        )
        stack.append(ident)
        if cursor.goto_first_child():
            continue
        while True:
            data[3][stack.pop()] = len(data[0])
            if cursor.goto_next_sibling():
                break
            if not cursor.goto_parent():
                return tuple(
                    np.asarray(column, dtype=dtype)
                    for column, dtype in zip(data, DTYPES)
                )


def encode_flat(columns):
    builder = flatbuffers.Builder(sum(c.nbytes for c in columns) + 128)
    vectors = [builder.CreateNumpyVector(c) for c in columns]
    builder.StartObject(len(columns))
    for slot, vector in enumerate(vectors):
        builder.PrependUOffsetTRelativeSlot(slot, vector, 0)
    root = builder.EndObject()
    builder.Finish(root, file_identifier=b"KEX1")
    return bytes(builder.Output())


def decode_flat(buffer):
    if buffer[4:8] != b"KEX1":
        raise ValueError("invalid FlatBuffers AST identifier")
    table = Table(buffer, struct.unpack_from("<I", buffer)[0])
    result = []
    for slot, flags in enumerate(FLAGS):
        offset = table.Offset(4 + 2 * slot)
        if not offset:
            raise ValueError("missing AST column")
        result.append(table.GetVectorAsNumpy(flags, offset))
    if len({len(c) for c in result}) != 1:
        raise ValueError("inconsistent AST column lengths")
    return tuple(result)


def validate(buffer, source_size, dictionary_size):
    """Validate offsets before following them; reject corrupted cache records."""
    try:
        columns = decode_flat(buffer)
        count = len(columns[0])
        if count == 0 or count > len(buffer) // 21:
            raise ValueError("invalid AST node count")
        kind, role, parent, end, start_byte, end_byte, flags = columns
        ids = np.arange(count, dtype="<u4")
        if (
            np.any(kind >= dictionary_size)
            or np.any(role >= dictionary_size)
            or parent[0] != -1
            or np.any(parent[1:] < 0)
            or np.any(parent[1:] >= ids[1:])
            or np.any(end <= ids)
            or np.any(end > count)
            or end[0] != count
            or np.any(start_byte > end_byte)
            or np.any(end_byte > source_size)
            or np.any(flags > 15)
        ):
            raise ValueError("invalid AST columns")
        if count > 1:
            owners = parent[1:]
            if (
                np.any(end[1:] > end[owners])
                or np.any(ids[1:] >= end[owners])
                or np.any(start_byte[1:] < start_byte[owners])
                or np.any(end_byte[1:] > end_byte[owners])
            ):
                raise ValueError("invalid AST subtree boundaries")
        return columns
    except (IndexError, TypeError, OverflowError, struct.error) as exc:
        raise ValueError("corrupt FlatBuffers syntax cache") from exc
