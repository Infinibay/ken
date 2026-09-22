"""Public syntax vocabulary shared by validation, exploration and help."""

SYNTAX_SELECTORS = ("node", "expression", "statement")
SYNTAX_PROPERTIES = {
    "kind": "String",
    "category": "String",
    "native_kind": "String",
    "role": "String",
    "name": "String",
    "text": "String",
    "operator": "String",
    "path": "String",
    "language": "String",
    "start_byte": "Int",
    "end_byte": "Int",
    "line": "Int",
    "normalized": "Bool",
    "type_kind": "String",
}
SYNTAX_RELATIONS = frozenset(
    {
        "contains",
        "contains_direct",
        "owns",
        "in_directory",
        "stable_id",
        "kind_is",
    }
)


def property_hint(name: str) -> str:
    if name == "parent":
        return "Use where contains_direct($parent, $child) for an immediate child, or contains($parent, $child) for a descendant."
    if name == "value":
        return 'For syntax literals use kind: "literal"; text: "True"; (or text: "None"; in Python). For value flow use BODY with --backend indexed.'
    return "Inspect supported properties with ken kql2 --capabilities."


def syntax_kinds() -> set[str]:
    from ken.common_ast.kinds import NATIVE

    return {kind for kind, _ in NATIVE.values()} | {
        "type_declaration",
        "callable",
        "call",
        "assignment",
        "member",
        "binary",
        "unary",
        "compare",
        "opaque",
    }
