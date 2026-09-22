"""FlatBuffers record vectors with lazily built in-memory endpoint indexes."""

import struct
from collections.abc import Sequence

import flatbuffers
import numpy as np
from flatbuffers import number_types as N
from flatbuffers.table import Table


def encode(rows, width, text_columns, check):
    words, ids, values = [""], {None: 0}, []
    for i, row in enumerate(rows):
        if i % 256 == 0:
            check()
        for column, value in enumerate(row):
            if column in text_columns:
                if value not in ids:
                    ids[value] = len(words)
                    words.append(value)
                value = ids[value]
            values.append(value)
    builder = flatbuffers.Builder(len(values) * 8 + 256)
    cells = builder.CreateNumpyVector(np.asarray(values, dtype="<i8"))
    strings = [builder.CreateString(word) for word in words]
    builder.StartVector(4, len(strings), 4)
    for offset in reversed(strings):
        builder.PrependUOffsetTRelative(offset)
    strings = builder.EndVector()
    builder.StartObject(3)
    builder.PrependUint32Slot(0, width, 0)
    builder.PrependUOffsetTRelativeSlot(1, strings, 0)
    builder.PrependUOffsetTRelativeSlot(2, cells, 0)
    builder.Finish(builder.EndObject(), file_identifier=b"KCR1")
    check()
    return bytes(builder.Output())


class Records:
    def __init__(self, blob, width, text_columns):
        if blob[4:8] != b"KCR1":
            raise ValueError("invalid catalog record identifier")
        table = Table(blob, struct.unpack_from("<I", blob)[0])
        if table.Get(N.Uint32Flags, table.Pos + table.Offset(4)) != width:
            raise ValueError("invalid catalog record width")
        offset = table.Offset(6)
        self.words = [
            table.String(table.Vector(offset) + i * 4).decode("utf-8")
            for i in range(table.VectorLen(offset))
        ]
        if not self.words:
            raise ValueError("missing record dictionary")
        self.words[0] = None
        self.ids = {word: i for i, word in enumerate(self.words)}
        self.cells = table.GetVectorAsNumpy(N.Int64Flags, table.Offset(8)).reshape(
            -1, width
        )
        for column in text_columns:
            if np.any(self.cells[:, column] < 0) or np.any(
                self.cells[:, column] >= len(self.words)
            ):
                raise ValueError("invalid catalog word index")
        self.text_columns = text_columns
        self.indexes = {}
        self.size = len(blob)

    def __len__(self):
        return len(self.cells)

    def row(self, i):
        return tuple(
            self.words[int(v)] if c in self.text_columns else int(v)
            for c, v in enumerate(self.cells[i])
        )

    def select(self, constraints):
        """Probe the smallest posting, then verify the remaining columns there.

        Intersecting a one-row subject with a project-wide kind posting copies
        and sorts that kind for every lookup. Cardinalities come directly from
        the sorted indexes; only the smallest posting needs materialization.
        """
        probes = []
        smallest = None
        size = len(self) + 1
        for column, value in constraints.items():
            values = value if isinstance(value, tuple) else (value,)
            if column in self.text_columns:
                values = tuple(self.ids[v] for v in values if v in self.ids)
            values = tuple(dict.fromkeys(values))
            if not values:
                return np.empty(0, dtype=np.intp)
            if column not in self.indexes:
                order = np.argsort(self.cells[:, column], kind="stable")
                self.indexes[column] = order, self.cells[order, column]
            order, keys = self.indexes[column]
            ranges = [
                (np.searchsorted(keys, v, side="left"),
                 np.searchsorted(keys, v, side="right"))
                for v in values
            ]
            count = sum(end - start for start, end in ranges)
            if not count:
                return np.empty(0, dtype=np.intp)
            probes.append((column, values))
            if count < size:
                smallest, size = (column, order, ranges), count
        if smallest is None:
            return range(len(self))
        column, order, ranges = smallest
        # Stable postings preserve source order. Distinct alternatives cannot
        # share positions, so sorting their union keeps duplicate source rows.
        selected = (
            order[ranges[0][0]:ranges[0][1]] if len(ranges) == 1 else
            np.sort(np.concatenate([order[start:end] for start, end in ranges]))
        )
        for other, values in probes:
            if other == column:
                continue
            cells = self.cells[selected, other]
            allowed = cells == values[0] if len(values) == 1 else np.isin(cells, values)
            selected = selected[allowed]
            if not len(selected):
                break
        return selected


class RecordRows(Sequence):
    def __init__(self, records, factory, positions=None):
        self.records, self.factory = records, factory
        self.positions = range(len(records)) if positions is None else positions

    def __len__(self):
        return len(self.positions)

    def __getitem__(self, position):
        if isinstance(position, slice):
            return RecordRows(self.records, self.factory, self.positions[position])
        return self.factory(self.records.row(self.positions[position]))

    def __iter__(self):
        for position in self.positions:
            yield self.factory(self.records.row(position))
