"""Shared relational plans and rows, independent of execution and storage.

KQL1 and KQL2 lower to these records. Keep their fields and mutability stable:
compilers assemble plans incrementally and plan caches retain node-list identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


RELATIONS = frozenset(
    (
        "HAS_INITIALIZER FIELD_NAME INITIALIZES_FIELD ITERATED_CALL OPTIONAL_VALUE "
        "OPTIONAL_OR OPTIONAL_PRESENT OPTIONAL_FALLBACK BODY_VALUE NULL_TEST BRANCH_TRUE "
        "BRANCH_FALSE SYNTAX_NODE SYNTAX_PARENT HANDLER_OF ENCLOSING_LOOP IN_HANDLER "
        "IN_TRY_BODY CONTINUE_TARGET DERIVE_NAME INVOKES_RESULT_OF CONTAINER CALLEE_VALUE "
        "INDEX ITERATES_KEYS_CALLS KEY_TYPE VALUE_TYPE ADVANCES_ITERATOR MEMBER_OF "
        "INSERTS_INTO INSERTED_VALUE LOADED_FROM ACQUIRES ACQUIRES_LOCK ALLOCATES_TYPE "
        "ARGUMENT ASSIGN ASSIGNED_FROM AWAIT BASE_NAME BINDS_TO BINDS_TYPE_PARAMETER BRANCH "
        "CALL CALLABLE CALLEE_NAME CALLS CAPTURES CFG_NEXT CLASS COLLECTION "
        "CONDITIONAL_DELEGATION CONFORMS_TO MATCHES_SIGNATURE CONTEXT_ENTRY CREATES "
        "CREATES_CONTEXT CREATES_LOCK DECLARES DECORATED_BY DECORATOR DELEGATES_TO "
        "DELEGATES_TYPE ELEMENT_TYPE EMBEDS ENTITY EXPORT EXPORT_SYNTAX EXTENDS FLOWS_TO "
        "FORWARDS_SLOT FUNCTION GUARDS_WRITE POSSIBLE_CALL HAS_ HAS_ASYNC_SCOPE HAS_CALL "
        "HAS_FIELD HAS_HAZARD HAS_METHOD HAS_OPERATION HAS_PARAMETER HAZARD IMPLEMENTS "
        "IMPORT IMPORT_SYNTAX INITIALIZED_AS INSTANCE_OF INTERFACE IN_TYPE IS "
        "ITERATES_CALLS JOINS LOOKS_UP LOOP MATCH MAY_ MAY_BIND_TO MAY_CALLS MAY_TARGET "
        "MAY_TYPE MEMBER MODULE NATIVE NULL OPERATION OVERRIDES OWNED_BY OWNER PARAMETER "
        "PASSES_SELF_TO READS RECEIVER RELEASES RELEASES_LOCK RESOURCE_SCOPE RESULT RETURN "
        "RETURNS RETURNS_CALL RETURNS_LOOKUP RETURNS_NEW RETURNS_NEW_SELF RETURNS_SELF "
        "RETURNS_STORAGE RETURNS_VALUE RETURN_TYPE_ARGUMENT SATISFIES SPAWNS_CONTEXT SPREAD "
        "STARTS_CONTEXT STORAGE STORES_VALUE SUBTYPE_OF TARGET THROW TRY TYPE TYPE_NAME "
        "TYPE_PARAMETER VALUE VALUE_FLOW VARIADIC WAITS_FOR WRITES WRITES_ELEMENT YIELD "
        "_PARSER _PARSER_TS _PARSER_TSX"
    ).split()
)

RELATIONS |= frozenset(
    {
        "ASSIGNMENT_TARGET",
        "ASSIGNMENT_VALUE",
        "RETURN_OPERAND",
        "RETURN_ORIGIN",
        "RETURN_REACHES",
        "RETURN_FLOW_STATUS",
    }
)
RELATIONS |= frozenset(
    {
        "TYPE_HEAD",
        "FINAL_MEMBER_INPUT",
        "MEMBER_FLOW_STATUS",
        "FINAL_BINDING_INPUT",
        "BINDING_FLOW_STATUS",
    }
)
RELATIONS |= frozenset({"TRUTH_TEST", "INSTANCE_RECEIVER", "PARAMETER_TEST"})
RELATIONS |= frozenset({"CONSTRUCTOR_INVENTORY", "RESOLVED_ALLOCATION_COUNT"})
RELATIONS |= frozenset(
    {
        "FIELD_DECLARATION",
        "FIELD_INITIAL_STATUS",
        "FIELD_INITIAL_VALUE",
        "NORMAL_COMPLETION",
        "LOOP_BODY_TAIL",
        "HANDLER_FALLTHROUGH",
    }
)
RELATIONS |= frozenset({"CLASS_EXPRESSION", "BASE_VALUE", "TYPE_ASSERTION_VALUE"})
RELATIONS |= frozenset(
    {
        "BINDING_WRITE_STATUS",
        "UNREASSIGNED_BINDING",
        "UNIQUE_BINDING_WRITE",
        "ARGUMENT_ORIGIN",
        "ARGUMENT_REACHES",
    }
)
RELATIONS |= frozenset(
    {
        "BINDING_WRITE_COUNT",
        "NOMINAL_ROOT",
        "NOMINAL_ROOT_STATUS",
        "CPP_FIELD_DECL_STATUS",
        "TYPE_QUALIFIER",
        "TYPE_HEAD_STATUS",
    }
)
RELATIONS |= frozenset(
    {
        "METHOD_SIGNATURE_STATUS",
        "VIRTUAL_METHOD",
        "INITIALIZER_FORM",
        "INITIALIZER_ARGUMENT",
        "CONSTRUCTOR_INITIALIZER_STATUS",
        "CONSTRUCTOR_INITIALIZER_INPUT",
    }
)
RELATIONS |= frozenset(
    {
        "TYPE_REF",
        "RETURN_TYPE_REF",
        "TYPE_KIND",
        "TYPE_NATIVE",
        "TYPE_BITS",
        "TYPE_SIGNED",
        "TYPE_EXTENT",
        "TYPE_ARGUMENT",
    }
)
RELATIONS |= frozenset({"OPERATOR", "OPERAND"})
RELATIONS |= frozenset(
    {
        "STORAGE_WRITE_COUNT",
        "STORAGE_WRITE_STATUS",
        "MEMBERSHIP_CONTAINER",
        "MEMBERSHIP_KEY",
        "TYPE_PARAMETER_RECEIVER",
        "TYPE_PARAMETER_OWNER",
        "CAST_VALUE",
        "INDEXED_WRITE_COUNT",
        "ITERATION_ENTRY_SOURCE",
        "TRY_EXIT_STATUS",
        "UNDEFINED_TEST",
        "CALL_RESULT_KIND",
        "BASE_INPUT",
        "CALL_ENTRY_BINDING",
    }
)
RELATIONS |= frozenset({"TYPE_RANK"})
RELATIONS |= frozenset({"RECEIVER_BINDING_VERSION", "RECEIVER_UNREPLACED"})
RELATIONS |= frozenset(
    {"EXPRESSION_OPERAND", "VALUE_DEPENDS_ON", "ARGUMENT_VALUE_ORIGIN"}
)
RELATIONS |= frozenset(
    {"ASSIGNMENT_ORIGIN", "BINDING_REFERENCE", "SHALLOW_COPY_SOURCE", "READ_ORIGIN"}
)
RELATIONS |= frozenset(
    {
        "CFG_ENTRY",
        "CFG_EXIT",
        "CFG_STATUS",
        "CONTROL_CONDITION",
        "CONTROL_BODY",
        "CONTROL_ITERABLE",
    }
)
RELATIONS |= frozenset({"CFG_FALLTHROUGH"})
RELATIONS |= frozenset({"EMPTY_COLLECTION", "CLEARS_COLLECTION", "AFTER_ITERATION"})
RELATIONS |= frozenset({"ITERATION_SOURCE", "ITERATION_BODY", "ITERATION_BINDING"})
RELATIONS |= frozenset(
    {"COLLECTION_SNAPSHOT_OF", "ITERATION_SNAPSHOT", "ITERATION_INVOKES_VALUE"}
)
RELATIONS |= frozenset({"EFFECTIVE_METHOD", "INSTANCE_SLOT", "ACCESS_INPUT"})
RELATIONS |= frozenset({"INSERTED_INPUT", "ITERATION_ORIGIN", "ITERATION_PASSES_VALUE"})
RELATIONS |= frozenset(
    {
        "DISCARDS_RESULT",
        "INSTANCE_RECEIVER",
        "PARAMETER_INITIALIZES_FIELD",
        "CONSTRUCTOR_FIELD_INPUT",
        "DECLARED_TARGET",
    }
)
RELATIONS |= frozenset(
    {"RETURN_FIELD_STATE", "FIELD_STATE_ORIGIN", "FIELD_STATE_WRITE"}
)
RELATIONS |= frozenset(
    {
        "MEMBER_DECLARATION",
        "DECLARES_EVENT",
        "ADDS_HANDLER",
        "REMOVES_HANDLER",
        "RAISES_EVENT",
    }
)
# Derived by the KQL 2 semantic layer from HAS_CALL + RAISES_EVENT, so a query can
# require "this method raises that event" without naming the intermediate call.
RELATIONS |= frozenset({"METHOD_RAISES_EVENT"})
RELATIONS |= frozenset(
    {
        "CONSTRUCTOR_TARGET",
        "CONSTRUCTOR_STATUS",
        "CALL_BINDING",
        "BINDING_STATUS",
        "BINDING_PARAMETER",
        "BINDING_VALUE",
        "BINDING_TARGET",
        "RETURNS_FIELD",
        "FINAL_FIELD_INPUT",
        "FINAL_FIELD_VALUE",
        "FIELD_FLOW_STATUS",
        "CALL_RECEIVER_INPUT",
    }
)

@dataclass
class Node:
    kind: str
    value: Any = None
    children: list[list[Node]] = field(default_factory=list)


@dataclass
class Query:
    name: str
    nodes: list[Node]
    exports: dict[str, str]
    definitions: dict[str, Query] = field(default_factory=dict, repr=False)

    def dependencies(self) -> list[tuple[str, dict[str, str]]]:
        def walk(nodes):
            for n in nodes:
                if n.kind == "match":
                    yield n.value[0], n.value[1]
                for child in n.children:
                    yield from walk(child)

        return list(walk(self.nodes))


@dataclass
class Row:
    bindings: dict[str, str] = field(default_factory=dict)
    evidence: list[Any] = field(default_factory=list)
    unknown: set[str] = field(default_factory=set)


class ScanConstraint(Protocol):
    """Necessary filters for a scan; never sufficient proof of a match.

    None means an unrestricted domain. An empty set proves no candidate can
    match. Unknown coverage must remain eligible for ordinary evaluation.
    """

    def domain(
        self, bindings: dict[str, str], role: str
    ) -> set[str] | frozenset[str] | None: ...

    def allows(self, bindings: dict[str, str]) -> bool: ...
