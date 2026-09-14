"""Versioned structural IR: ordered operations plus an evidence-bearing fact graph."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

IR_VERSION = "1.75.0"


def _attribute_key(value: Any) -> str:
    """How an attribute value is keyed for lookup and compared for equality."""
    return str(value).lower() if isinstance(value, bool) else str(value)



@dataclass
class Entity:
    id: str
    kind: str
    name: str
    path: str
    line: int
    end_line: int
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Operation:
    id: str
    kind: str
    native_kind: str
    parent: str | None
    role: str
    start: int
    end: int
    line: int
    owner: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fact:
    subject: str
    relation: str
    object: str
    attrs: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)


@dataclass
class IR:
    path: str
    language: str
    entities: dict[str, Entity] = field(default_factory=dict)
    operations: list[Operation] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)
    diagnostics: list[str] = field(default_factory=list)
    version: str = IR_VERSION
    relations: set[str] = field(default_factory=set)
    view: str = "source"

    def add(self, subject: str, relation: str, object: str,
            evidence: str = "", **attrs: Any) -> None:
        self.relations.add(relation)
        self.facts.append(Fact(subject, relation, object, attrs, [evidence] if evidence else []))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["capabilities"] = sorted(self.capabilities)
        result["relations"] = sorted(self.relations)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IR:
        if data["version"] != IR_VERSION:
            raise ValueError("incompatible IR version")
        return cls(path=data["path"], language=data["language"],
                   entities={k: Entity(**v) for k, v in data["entities"].items()},
                   operations=[Operation(**v) for v in data["operations"]],
                   facts=[Fact(**v) for v in data["facts"]],
                   capabilities=set(data["capabilities"]), diagnostics=data["diagnostics"], relations=set(data.get("relations", [])), view=data.get("view", "source"))


class FactIndex:
    """Snapshot of fact membership with relation-local lazy endpoint indexes.

    Facts and public index mappings must not be mutated while querying. Adding
    facts to the source IR does not extend this snapshot. ``rows`` chooses a
    candidate bucket, not an intersection; callers still filter both endpoints.

    Three buckets exist because the catalogue asks three kinds of question:
    which facts name this subject (``rows`` with a subject), which name this
    object, and which carry this exact attribute value (``attr_rows``). The last
    one is what turns ``call(name: "computeIfAbsent")`` from a scan of every
    entity in the project into a dictionary lookup.
    """
    def __init__(self, ir: IR):
        self.ir = ir
        self._facts = tuple(ir.facts)
        self.by_relation: dict[str, list[Fact]] = {}
        self._by_subject: dict[tuple[str, str], list[Fact]] = {}
        self._by_object: dict[tuple[str, str], list[Fact]] = {}
        self._by_attr: dict[tuple[str, str], dict[str, list[Fact]]] = {}
        self._subject_relations: set[str] = set()
        self._object_relations: set[str] = set()
        self._subject_complete = False
        self._object_complete = False
        for fact in self._facts:
            self.by_relation.setdefault(fact.relation, []).append(fact)

    def _endpoint(self, relation: str, subject: bool) -> dict[tuple[str, str], list[Fact]]:
        index = self._by_subject if subject else self._by_object
        indexed = self._subject_relations if subject else self._object_relations
        complete = self._subject_complete if subject else self._object_complete
        if not complete and relation not in indexed:
            # Build privately before publishing, so concurrent readers cannot
            # append duplicate facts to the same partially populated buckets.
            buckets: dict[tuple[str, str], list[Fact]] = {}
            for fact in self.by_relation.get(relation, []):
                endpoint = fact.subject if subject else fact.object
                buckets.setdefault((relation, endpoint), []).append(fact)
            index.update(buckets)
            indexed.add(relation)
        return index

    def _all_endpoints(self, subject: bool) -> dict[tuple[str, str], list[Fact]]:
        complete = self._subject_complete if subject else self._object_complete
        index = self._by_subject if subject else self._by_object
        if complete:
            return index
        # Preserve eager dictionary insertion order across interleaved relations
        # and retain already returned bucket lists, without appending twice.
        full: dict[tuple[str, str], list[Fact]] = {}
        for fact in self._facts:
            key = (fact.relation, fact.subject if subject else fact.object)
            if key in index:
                full.setdefault(key, index[key])
            else:
                full.setdefault(key, []).append(fact)
        if subject:
            self._by_subject = full
            self._subject_complete = True
        else:
            self._by_object = full
            self._object_complete = True
        return full

    @property
    def by_subject(self) -> dict[tuple[str, str], list[Fact]]:
        """Complete compatibility view, materialized only when requested."""
        return self._all_endpoints(True)

    @property
    def by_object(self) -> dict[tuple[str, str], list[Fact]]:
        """Complete compatibility view, materialized only when requested."""
        return self._all_endpoints(False)

    def rows(self, relation: str, subject: str | None = None,
             object: str | None = None) -> list[Fact]:
        rows = self.by_relation.get(relation, [])
        if subject is not None:
            rows = self._endpoint(relation, True).get((relation, subject), [])
        if object is not None:
            other = self._endpoint(relation, False).get((relation, object), [])
            if subject is None or len(other) < len(rows):
                rows = other
        return rows

    def attr_rows(self, relation: str, key: str, value: str) -> list[Fact]:
        """Facts of ``relation`` whose attribute ``key`` equals ``value`` exactly.

        Built on first use, one attribute at a time, from the relation's posting
        list. Values are keyed the way ``_compare`` compares them, so a boolean
        attribute stored as ``False`` buckets as ``"false"``.
        """
        index = self._by_attr.get((relation, key))
        if index is None:
            index = {}
            for fact in self.by_relation.get(relation, []):
                if key not in fact.attrs:
                    continue
                index.setdefault(_attribute_key(fact.attrs[key]), []).append(fact)
            self._by_attr[(relation, key)] = index
        return index.get(value, [])

