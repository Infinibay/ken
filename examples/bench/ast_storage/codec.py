"""Equivalent experimental AST layouts; not a production cache format.

The FlatBuffers adapter uses the official Builder/Table APIs corresponding to
ast.fbs, keeping the experiment runnable without a separately installed flatc.
All three stores retain anonymous tokens, field roles, error/missing flags,
source bytes and dictionary-coded types. Semantic facts are outside this test.
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
HEADER = struct.Struct("<4sI")


class Dictionary:
    def __init__(self):
        self.words = [""]
        self.ids = {"": 0}

    def intern(self, value):
        if value not in self.ids:
            if len(self.words) >= 65536:
                raise ValueError("benchmark dictionary exceeded uint16")
            self.ids[value] = len(self.words)
            self.words.append(value)
        return self.ids[value]


def flatten(tree, dictionary):
    """Iterative cursor walk, with one live tree and bounded depth stack."""
    data = [array(code) for code in ("H", "H", "i", "I", "I", "I", "B")]
    cursor = tree.walk()
    stack = []
    while True:
        node = cursor.node
        ident = len(data[0])
        values = (
            dictionary.intern(node.type),
            dictionary.intern(cursor.field_name or ""),
            stack[-1] if stack else -1,
            0,
            node.start_byte,
            node.end_byte,
            int(node.is_named)
            | (int(node.has_error) << 1)
            | (int(node.is_missing) << 2)
            | (int(node.is_error) << 3),
        )
        for column, value in zip(data, values):
            column.append(value)
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


def encode_packed(columns):
    return HEADER.pack(b"KAP1", len(columns[0])) + b"".join(
        c.tobytes() for c in columns
    )


def decode_packed(buffer):
    magic, count = HEADER.unpack_from(buffer)
    if magic != b"KAP1" or len(buffer) != HEADER.size + count * 21:
        raise ValueError("invalid packed AST")
    result, offset = [], HEADER.size
    for dtype in DTYPES:
        column = np.frombuffer(buffer, dtype=dtype, count=count, offset=offset)
        result.append(column)
        offset += column.nbytes
    return tuple(result)


def encode_flat(columns):
    builder = flatbuffers.Builder(sum(c.nbytes for c in columns) + 128)
    vectors = [builder.CreateNumpyVector(c) for c in columns]
    builder.StartObject(len(columns))
    for slot, vector in enumerate(vectors):
        builder.PrependUOffsetTRelativeSlot(slot, vector, 0)
    root = builder.EndObject()
    builder.Finish(root, file_identifier=b"KAST")
    return bytes(builder.Output())


def decode_flat(buffer):
    if buffer[4:8] != b"KAST":
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


class ScalarColumn:
    """Generated-accessor equivalent, to quantify per-element Python overhead."""

    def __init__(self, table, slot):
        self.table, self.slot = table, slot

    def __getitem__(self, ident):
        offset = self.table.Offset(4 + 2 * self.slot)
        flags = FLAGS[self.slot]
        return self.table.Get(
            flags, self.table.Vector(offset) + ident * flags.bytewidth
        )


def decode_flat_scalar(buffer):
    table = Table(buffer, struct.unpack_from("<I", buffer)[0])
    return tuple(ScalarColumn(table, slot) for slot in range(len(FIELDS)))
