"""Owner-scoped BODY views read through the persistent graph indexes."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from .store import Node


class Lookup(Mapping):
    """A bounded lazy mapping; iteration must be supplied explicitly."""

    def __init__(self, lookup, keys=(), capacity=128):
        self.lookup = lru_cache(maxsize=capacity)(lookup)
        self.keys_source = keys

    def __getitem__(self, key):
        value = self.lookup(key)
        if value is None:
            raise KeyError(key)
        return value

    def __iter__(self):
        return iter(self.keys_source)

    def __len__(self):
        return len(self.keys_source)


class GraphSourceView:
    def __init__(self, index):
        self.index = index
        self.nodes = Lookup(self.node, index.ir.entities, capacity=2048)
        self.owned = Lookup(self.owner_nodes)
        self.entities = Lookup(self.owner_entities)
        self.operations = Lookup(lambda owner: list(index.operations(owner=owner)))

    def operation(self, local_id):
        return next(self.index.operations(local_id=local_id), None)

    def region_operations(self, owner, region):
        return self.index.operations(owner=owner, region=region)

    def node(self, local_id):
        term = self.index.term(local_id)
        if term is None:
            return None
        row = self.index.db.execute(
            """SELECT e.ordinal,e.kind,e.name,p.text,e.line,e.end_line,e.path,e.attributes
            FROM k2_graph_entities e LEFT JOIN k2_graph_terms p
            ON p.graph_id=e.graph_id AND p.term_id=e.source_owner
            WHERE e.graph_id=? AND e.local_id=?""",
            (self.index.graph, term),
        ).fetchone()
        if row is not None:
            ordinal, kind, name, owner, line, end_line, path, attributes = row
            kind, path = self.index.words(kind), self.index.words(path)
            language = self.index.values.get(attributes).get(
                "language", self.index.ir.language
            )
            return Node(
                ordinal, 0, local_id, kind, name, owner, line, end_line, path, language
            )
        operation = next(self.index.operations(local_id=local_id), None)
        if operation is not None:
            owner = self.nodes.get(operation.owner)
            if owner is not None:
                return Node(
                    0,
                    owner.unit,
                    local_id,
                    "OPERATION",
                    "",
                    owner.local_id,
                    operation.line,
                    operation.line,
                    owner.path,
                    owner.language,
                )
        for fact in self.index.rows("INSTANCE_RECEIVER", object=local_id):
            owner = self.nodes.get(fact.subject)
            if owner is not None:
                return Node(
                    0,
                    owner.unit,
                    local_id,
                    "RECEIVER",
                    "this",
                    owner.local_id,
                    owner.line,
                    owner.end_line,
                    owner.path,
                    owner.language,
                )
        return None

    def owner_nodes(self, owner):
        return [self.nodes[e.id] for e in self.index.entities(source_owner=owner)]

    def owner_entities(self, owner):
        entities = {e.id: e for e in self.index.entities(source_owner=owner)}
        subjects = dict(entities)
        subjects.update((e.id, e) for e in self.index.entities(owner=owner))
        for subject in subjects.values():
            # dict.get evaluates its fallback eagerly. Most occurrences already
            # publish an owner, so do not fetch/decode a second node for them.
            actual_owner = (subject.attrs["owner"] if "owner" in subject.attrs
                            else self.nodes[subject.id].owner)
            if actual_owner != owner:
                continue
            for relation in (
                "ARGUMENT",
                "ASSIGNMENT_VALUE",
                "RETURN_OPERAND",
                "OPERAND",
            ):
                for fact in self.index.rows(relation, subject.id):
                    for value in self.index.rows("VALUE", fact.object):
                        entity = self.index.ir.entities.get(value.object)
                        if entity is not None:
                            entities[entity.id] = entity
        return entities

    def scan(self, snapshot, *, owner):
        return iter(self.owned[owner.local_id])

    def properties(self, node):
        entity = self.index.ir.entities.get(node.local_id)
        return {
            **(entity.attrs if entity else {}),
            "name": node.name,
            "path": node.path,
            "language": node.language,
        }
