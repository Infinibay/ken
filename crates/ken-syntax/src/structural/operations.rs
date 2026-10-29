//! Lossless named-node projection; semantic claims do not come from kind guessing.
use super::{
    attributes,
    ownership::Ownership,
    source::{self, field, operation_id, text},
    vocabulary::{comparison, fallback, short_circuit, vocabulary},
};
use crate::{Language, SyntaxNode};
use ken_program::{Fact, Operation, StructuralIr};
use serde_json::{Value, json};

fn add(
    ir: &mut StructuralIr,
    subject: &str,
    relation: &str,
    object: &str,
    node: SyntaxNode<'_>,
    attrs: Value,
) {
    ir.relations.insert(relation.into());
    ir.facts.push(Fact {
        subject: subject.into(),
        relation: relation.into(),
        object: object.into(),
        evidence: vec![format!("{}:{}", ir.path, node.start_point()[0] + 1)],
        attrs: attributes(attrs),
    });
}
pub(super) fn project(
    ir: &mut StructuralIr,
    node: SyntaxNode<'_>,
    role: &str,
    owners: &Ownership,
    source: &[u8],
    language: Language,
) {
    let v = vocabulary();
    let native = node.kind();
    let owner = &owners.nodes[&node.id()];
    let children = node.children();
    let named = node.named_children();
    let prototype = owners.prototypes.contains(&node.id());
    let mut kind = if v.types.contains(native) {
        "TYPE"
    } else if native == "field_initializer" && language == Language::Cpp {
        "INITIALIZE"
    } else if v.functions.contains(native) || owners.functions.contains(&node.id()) {
        "FUNCTION"
    } else if v.calls.contains(native) {
        "CALL"
    } else if v.assignments.contains(native) {
        let mut kind = if prototype { "DECLARATION" } else { "ASSIGN" };
        if native == "let_declaration"
            && language == Language::Rust
            && text(node.field("pattern"), source) == "_"
        {
            kind = "DISCARD";
        }
        let bare = (native == "variable_declarator"
            && matches!(
                language,
                Language::JavaScript | Language::TypeScript | Language::Java | Language::CSharp
            ))
            || (native == "let_declaration" && language == Language::Rust)
            || v.file_declarations.contains(native)
            || matches!(
                native,
                "field_declaration" | "public_field_definition" | "field_definition"
            )
            || (native == "assignment"
                && language == Language::Python
                && node.field("type").is_some());
        if bare
            && source::declaration_parts(node).1.is_none()
            && !children.iter().any(|c| c.kind() == "=")
        {
            kind = "DECLARATION";
        }
        kind
    } else if v.members.contains(native) {
        "MEMBER"
    } else if v.loops.contains(native) {
        "LOOP"
    } else if v.branches.contains(native) {
        "BRANCH"
    } else {
        fallback(native)
    };
    let mut attrs = serde_json::Map::new();
    if named.is_empty()
        || matches!(
            native,
            "string"
                | "string_literal"
                | "raw_string_literal"
                | "interpreted_string_literal"
                | "char_literal"
                | "character_literal"
                | "rune_literal"
        )
    {
        attrs.insert("text".into(), text(Some(node), source).into());
    }
    let tokens = children
        .iter()
        .filter(|c| !c.is_named())
        .map(|&c| text(Some(c), source))
        .collect::<Vec<_>>();
    if v.loops.contains(native) && tokens.iter().any(|t| t == "async" || t == "await") {
        attrs.insert("async".into(), true.into());
    }
    let operators = tokens
        .iter()
        .filter(|t| v.operators.contains(*t))
        .collect::<Vec<_>>();
    let operator =
        (v.operator_nodes.contains(native) || v.assignments.contains(native)) && !prototype;
    if operator && !operators.is_empty() {
        if v.assignments.contains(native)
            || matches!(
                native,
                "augmented_assignment"
                    | "augmented_assignment_expression"
                    | "compound_assignment_expr"
            )
        {
            if kind != "DISCARD" {
                kind = "ASSIGN";
            }
        } else if operators
            .iter()
            .any(|t| t.as_str() == "++" || t.as_str() == "--")
        {
            kind = "UPDATE";
        } else if operators.iter().any(|t| comparison(t)) {
            kind = "COMPARE";
        } else if matches!(
            native,
            "unary"
                | "unary_expression"
                | "unary_operator"
                | "not_operator"
                | "prefix_unary_expression"
                | "postfix_unary_expression"
        ) {
            kind = "UNARY";
        } else {
            kind = "BINARY";
        }
    }
    if kind == "YIELD" {
        attrs.insert(
            "delegated".into(),
            tokens.iter().any(|t| t == "from" || t == "*").into(),
        );
    }
    attrs.insert("tokens".into(), json!(tokens));
    let id = operation_id(&ir.path, node);
    let parent = node.parent();
    let mut role = role.to_owned();
    if language == Language::Ruby
        && parent.is_some_and(|p| p.kind() == "if_modifier")
        && role == "body"
    {
        role = "consequence".into();
    }
    ir.operations.push(Operation {
        id: id.clone(),
        kind: kind.into(),
        native_kind: native.into(),
        parent: parent.map(|p| operation_id(&ir.path, p)),
        role,
        start: node.start_byte() as i64,
        end: node.end_byte() as i64,
        line: (node.start_point()[0] + 1) as i64,
        owner: owner.clone(),
        attrs: attributes(Value::Object(attrs)),
    });
    if operator && !operators.is_empty() {
        for (position, token) in operators.iter().enumerate() {
            add(
                ir,
                &id,
                "OPERATOR",
                token,
                node,
                json!({"position":position,"short_circuit":short_circuit(token)}),
            );
        }
        let operands = if v.assignments.contains(native) {
            let left = field(Some(node), &["left", "name", "pattern", "declarator"]);
            let mut right = field(Some(node), &["right", "value"]);
            if right.is_none()
                && language == Language::CSharp
                && let Some(equal) = children.iter().position(|c| c.kind() == "=")
            {
                right = children[equal + 1..]
                    .iter()
                    .find(|c| c.is_named() && c.kind() != "comment")
                    .copied();
            }
            vec![left, right]
        } else {
            let operator = node.field("operator");
            named
                .iter()
                .filter(|n| {
                    !matches!(n.kind(), "comment" | "line_comment" | "block_comment")
                        && operator.is_none_or(|o| o.id() != n.id())
                })
                .copied()
                .map(Some)
                .collect()
        };
        for (position, operand) in operands.into_iter().enumerate() {
            if let Some(operand) = operand {
                add(
                    ir,
                    &id,
                    "OPERAND",
                    &operation_id(&ir.path, operand),
                    node,
                    json!({"position":position}),
                );
            }
        }
    }
    if matches!(
        kind,
        "YIELD" | "AWAIT" | "IMPORT" | "EXPORT" | "MATCH" | "RESOURCE_SCOPE" | "TYPE_PARAMETER"
    ) {
        add(
            ir,
            owner,
            &format!("HAS_{kind}"),
            &id,
            node,
            json!({"native_kind":native}),
        );
    }
    if node.is_error() || node.is_missing() {
        ir.diagnostics.push(format!(
            "{}:{}: {native}",
            ir.path,
            node.start_point()[0] + 1
        ));
    }
}
