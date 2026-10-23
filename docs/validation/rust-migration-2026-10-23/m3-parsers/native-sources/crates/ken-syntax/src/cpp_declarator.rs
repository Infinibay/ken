//! A C++ callable declarator owns its simple name, qualifier and destructor form.
use crate::{SyntaxNode, helpers::text};
pub(crate) struct CallableName {
    pub name: String,
    pub qualifier: String,
    pub destructor: bool,
}
pub(crate) fn callable(mut node: Option<SyntaxNode<'_>>, source: &[u8]) -> Option<CallableName> {
    while node.is_some_and(|n| {
        matches!(
            n.kind(),
            "pointer_declarator" | "reference_declarator" | "parenthesized_declarator"
        )
    }) {
        node = node.and_then(|n| n.field("declarator"));
    }
    let node = node
        .filter(|n| n.kind() == "function_declarator")?
        .field("declarator")?;
    match node.kind() {
        "identifier" | "field_identifier" | "operator_name" | "destructor_name" => {
            Some(CallableName {
                name: text(node, source),
                qualifier: String::new(),
                destructor: node.kind() == "destructor_name",
            })
        }
        "qualified_identifier" => {
            let value = text(node, source);
            let mut parts: Vec<_> = value.split("::").filter(|p| !p.is_empty()).collect();
            let name = parts.pop()?;
            Some(CallableName {
                name: name.into(),
                qualifier: parts.join("."),
                destructor: name.starts_with('~'),
            })
        }
        _ => None,
    }
}
