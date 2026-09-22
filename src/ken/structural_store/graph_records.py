"""Lazy attribute records and the immutable collection contract of a graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, fields

from ken.structural.model import Entity, Fact, Operation


class StoredFact(Fact):
    __slots__ = ("_attributes", "_attrs", "_evidence", "_proof", "_reader")

    def __init__(self, reader, subject, relation, object, attributes, evidence):
        self.subject, self.relation, self.object = subject, relation, object
        self._reader, self._attributes, self._evidence = reader, attributes, evidence
        self._attrs = self._proof = None

    @property
    def attrs(self):
        if self._attrs is None:
            self._attrs = self._reader.get(self._attributes)
        return self._attrs

    def attribute(self, key):
        if self._attrs is not None:
            return self._attrs.get(key)
        return self._reader.member(self._attributes, key)

    def same_evidence(self, other: Fact) -> bool:
        # Value IDs identify immutable encoded documents within this reader.
        # Once decoded, the public lists are mutable and must compare by value.
        if (isinstance(other, StoredFact)
                and self._reader is other._reader
                and self._evidence == other._evidence
                and self._proof is None and other._proof is None):
            return True
        return self.evidence == other.evidence

    @property
    def evidence(self):
        if self._proof is None:
            self._proof = self._reader.get(self._evidence)
        return self._proof


class StoredEntity(Entity):
    __slots__ = ("_attributes", "_attrs", "_reader")

    def __init__(self, reader, local_id, kind, name, path, line, end_line, attributes):
        self.id, self.kind, self.name, self.path = local_id, kind, name, path
        self.line, self.end_line = line, end_line
        self._reader, self._attributes, self._attrs = reader, attributes, None

    @property
    def attrs(self):
        if self._attrs is None:
            self._attrs = self._reader.get(self._attributes)
        return self._attrs


class StoredOperation(Operation):
    __slots__ = ("_attributes", "_attrs", "_reader")

    def __init__(
        self,
        reader,
        local_id,
        kind,
        native_kind,
        parent,
        role,
        start,
        end,
        line,
        owner,
        attributes,
    ):
        self.id, self.kind, self.native_kind = local_id, kind, native_kind
        self.parent, self.role = parent, role
        self.start, self.end, self.line, self.owner = start, end, line, owner
        self._reader, self._attributes, self._attrs = reader, attributes, None

    @property
    def attrs(self):
        if self._attrs is None:
            self._attrs = self._reader.get(self._attributes)
        return self._attrs

    def __eq__(self, other):
        # Operation lookups previously returned plain dataclasses. Preserve
        # value equality in both directions, despite the storage-only subclass.
        if not isinstance(other, Operation):
            return NotImplemented
        return self is other or all(
            getattr(self, field.name) == getattr(other, field.name)
            for field in fields(Operation)
        )


@dataclass
class GraphView:
    """Read-only collection views; compatible with BODY's dataclass replacement."""

    path: str
    language: str
    version: str
    view: str
    entities: Mapping[str, Entity]
    operations: Sequence[Operation]
    facts: Sequence[Fact]
    capabilities: AbstractSet[str]
    diagnostics: list[str]
    relations: set[str]
