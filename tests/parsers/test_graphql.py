"""GraphQL parser: type-system + executable definitions, no imports."""

from __future__ import annotations


def test_object_type_and_fields(parse_graphql):
    src = '"""The root query."""\ntype Query {\n  user(id: ID!): User\n  posts: [Post!]!\n}\n'
    out = parse_graphql(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["Query"].kind == "type"
    assert by_qual["Query"].docstring == "The root query."
    assert by_qual["Query.user"].kind == "field"
    assert by_qual["Query.posts"].kind == "field"
    assert out.imports == []


def test_enum_input_interface_union_scalar(parse_graphql):
    src = (
        "interface Node { id: ID! }\n"
        "enum Role { ADMIN USER }\n"
        "input CreateUserInput { name: String! }\n"
        "union SearchResult = User | Post\n"
        "scalar DateTime\n"
    )
    out = parse_graphql(src)
    kinds = {(s.kind, s.name) for s in out.symbols}
    assert ("interface", "Node") in kinds
    assert ("enum", "Role") in kinds
    assert ("enum_value", "ADMIN") in kinds
    assert ("input", "CreateUserInput") in kinds
    assert ("union", "SearchResult") in kinds
    assert ("scalar", "DateTime") in kinds


def test_operations_and_fragments(parse_graphql):
    src = (
        "query GetUser($id: ID!) { user(id: $id) { name } }\n"
        "fragment UserFields on User { id name }\n"
    )
    out = parse_graphql(src)
    by_name = {s.name: s for s in out.symbols}
    assert by_name["GetUser"].kind == "query"
    assert by_name["UserFields"].kind == "fragment"
