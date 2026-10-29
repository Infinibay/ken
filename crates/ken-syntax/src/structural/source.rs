//! Byte-preserving syntax access and structural declaration shapes.
use super::vocabulary::vocabulary;
use crate::SyntaxNode;
pub(super) fn text(node: Option<SyntaxNode<'_>>, source: &[u8]) -> String {
    node.map(|n| String::from_utf8_lossy(&source[n.start_byte()..n.end_byte()]).into_owned())
        .unwrap_or_default()
}
pub(super) fn field<'a>(node: Option<SyntaxNode<'a>>, names: &[&str]) -> Option<SyntaxNode<'a>> {
    node.and_then(|node| names.iter().find_map(|name| node.field(name)))
}
pub(super) fn descendants_with_roles(node: SyntaxNode<'_>) -> Vec<(SyntaxNode<'_>, &str)> {
    let mut all = Vec::new();
    let mut pending = vec![(node, "")];
    while let Some((node, role)) = pending.pop() {
        all.push((node, role));
        pending.extend(
            node.children_with_fields()
                .into_iter()
                .rev()
                .filter(|(child, _)| child.is_named())
                .map(|(child, field)| (child, field.unwrap_or(""))),
        );
    }
    all
}
pub(super) fn parameters(node: SyntaxNode<'_>) -> Option<SyntaxNode<'_>> {
    let mut current = Some(node);
    for _ in 0..32 {
        let node = current?;
        if let Some(parameters) = node.field("parameters") {
            return Some(parameters);
        }
        current = declarator(Some(node));
    }
    None
}
pub(super) fn parameter_name(node: SyntaxNode<'_>, source: &[u8]) -> String {
    let name = field(Some(node), &["name", "pattern", "declarator"])
        .or_else(|| {
            descendants_with_roles(node)
                .into_iter()
                .map(|(node, _)| node)
                .find(|node| matches!(node.kind(), "identifier" | "self"))
        })
        .unwrap_or(node);
    text(Some(name), source)
        .trim_start_matches(['*', '&', '.'])
        .into()
}
pub(super) fn declarator(node: Option<SyntaxNode<'_>>) -> Option<SyntaxNode<'_>> {
    field(node, &["declarator"]).or_else(|| {
        node.filter(|n| n.kind() == "reference_declarator")
            .and_then(|n| n.named_children().first().copied())
    })
}
pub(super) fn name(node: SyntaxNode<'_>, source: &[u8]) -> String {
    let named = node.field("name").or_else(|| {
        let mut current = declarator(Some(node));
        while let Some(next) = declarator(current) {
            current = Some(next);
        }
        current
    });
    let spelling = text(named, source);
    if spelling.is_empty() {
        format!("anonymous@{}", node.start_byte())
    } else {
        spelling
    }
}
pub(super) fn declared_names(node: SyntaxNode<'_>) -> Vec<SyntaxNode<'_>> {
    node.children()
        .into_iter()
        .enumerate()
        .filter(|(i, _)| node.field_name_for_child(*i) == Some("name"))
        .map(|(_, n)| n)
        .collect()
}
pub(super) fn declaration_parts(
    node: SyntaxNode<'_>,
) -> (Option<SyntaxNode<'_>>, Option<SyntaxNode<'_>>) {
    let v = vocabulary();
    let source = if let Some(spec) = v.spec_declarations.get(node.kind()) {
        let specs = node
            .named_children()
            .into_iter()
            .filter(|c| c.kind() == spec)
            .collect::<Vec<_>>();
        if specs.len() != 1 {
            return (None, None);
        }
        specs[0]
    } else {
        node
    };
    let names = declared_names(source);
    if names.len() > 1 {
        return (None, None);
    }
    (
        names
            .first()
            .copied()
            .or_else(|| field(Some(source), &["left", "pattern", "declarator", "property"])),
        field(Some(source), &["right", "value"]),
    )
}
// These follow only the structural declaration chain. The indexing parser's
// qualified-name helper has a different admission contract and cannot replace it.
fn nested(node: SyntaxNode<'_>) -> Option<SyntaxNode<'_>> {
    node.field("declarator").or_else(|| {
        matches!(
            node.kind(),
            "reference_declarator" | "abstract_reference_declarator" | "parenthesized_declarator"
        )
        .then(|| {
            node.named_children()
                .into_iter()
                .find(|c| !c.kind().contains("comment"))
        })
        .flatten()
    })
}
pub(super) fn function_parts(node: SyntaxNode<'_>) -> Option<(SyntaxNode<'_>, SyntaxNode<'_>)> {
    let mut current = Some(node);
    for _ in 0..32 {
        let n = current?;
        if n.kind() == "function_declarator" {
            let mut name = nested(n);
            while name.is_some_and(|n| n.kind() == "parenthesized_declarator") {
                name = name.and_then(nested);
            }
            return name
                .filter(|n| {
                    matches!(
                        n.kind(),
                        "identifier" | "field_identifier" | "operator_name" | "destructor_name"
                    )
                })
                .map(|name| (n, name));
        }
        if !matches!(
            n.kind(),
            "function_definition" | "pointer_declarator" | "reference_declarator"
        ) {
            return None;
        }
        current = nested(n);
    }
    None
}
pub(super) fn prototype_origin(node: SyntaxNode<'_>) -> Option<SyntaxNode<'_>> {
    if node.kind() != "function_declarator" || function_parts(node).is_none() {
        return None;
    }
    let mut current = node;
    for _ in 0..32 {
        let parent = current.parent()?;
        if matches!(parent.kind(), "field_declaration" | "declaration") {
            let mut container = parent.parent();
            if container.is_some_and(|n| n.kind() == "template_declaration") {
                container = container.and_then(|n| n.parent());
            }
            return container
                .filter(|n| n.kind() == "field_declaration_list")
                .map(|_| parent);
        }
        if !matches!(parent.kind(), "pointer_declarator" | "reference_declarator") {
            return None;
        }
        current = parent;
    }
    None
}
pub(super) fn operation_id(path: &str, node: SyntaxNode<'_>) -> String {
    format!(
        "{path}::op:{}:{}:{}",
        node.start_byte(),
        node.end_byte(),
        node.kind()
    )
}
