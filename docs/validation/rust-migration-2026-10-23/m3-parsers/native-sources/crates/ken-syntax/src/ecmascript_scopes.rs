//! Lexical callable bindings preserve symbol identity through owned model values.
use crate::{
    ParseError, SyntaxNode,
    helpers::{qualified, symbol},
    model::{ParsedFile, ParsedScope},
    scopes,
};
use std::collections::BTreeMap;

fn text(node: Option<SyntaxNode<'_>>, source: &[u8]) -> Result<String, ParseError> {
    let Some(node) = node else {
        return Ok(String::new());
    };
    std::str::from_utf8(&source[node.start_byte()..node.end_byte()])
        .map(str::to_owned)
        .map_err(|e| ParseError::Parse {
            language: "ecmascript".into(),
            reason: e.to_string(),
        })
}
fn target(node: Option<SyntaxNode<'_>>, source: &[u8]) -> Result<Option<String>, ParseError> {
    let Some(node) = node else { return Ok(None) };
    match node.kind() {
        "identifier" | "property_identifier" | "private_property_identifier" | "this" => {
            Ok(Some(text(Some(node), source)?))
        }
        "member_expression" => {
            let receiver = target(node.field("object"), source)?;
            let property = target(node.field("property"), source)?;
            Ok(receiver
                .zip(property)
                .filter(|(a, b)| !a.is_empty() && !b.is_empty())
                .map(|(a, b)| a + "." + &b))
        }
        _ => Ok(None),
    }
}

pub(crate) fn enrich(
    source: &[u8],
    root: SyntaxNode<'_>,
    out: &mut ParsedFile,
) -> Result<(), ParseError> {
    let existing = out
        .symbols
        .iter()
        .enumerate()
        .map(|(i, s)| ((s.name.clone(), s.line_start, s.line_end), i))
        .collect();
    let scope_map = scopes::indexed(source, root, &out.symbols)
        .into_iter()
        .collect();
    let mut bindings = Bindings {
        source,
        out,
        existing,
        scopes: scope_map,
        next: 0,
    };
    bindings.next = bindings.out.symbols.len();
    bindings.walk(root, "", None)?;
    let mut scopes: Vec<_> = bindings.scopes.into_values().collect();
    scopes.sort_by(|a, b| {
        a.symbol
            .line_start
            .cmp(&b.symbol.line_start)
            .then_with(|| b.symbol.line_end.cmp(&a.symbol.line_end))
            .then_with(|| a.symbol.qualname.cmp(&b.symbol.qualname))
    });
    bindings.out.scopes = scopes;
    Ok(())
}
struct Bindings<'a> {
    source: &'a [u8],
    out: &'a mut ParsedFile,
    existing: BTreeMap<(String, usize, usize), usize>,
    scopes: BTreeMap<usize, ParsedScope>,
    next: usize,
}
impl Bindings<'_> {
    fn walk(
        &mut self,
        node: SyntaxNode<'_>,
        owner: &str,
        parent_kind: Option<&str>,
    ) -> Result<(), ParseError> {
        let mut carrier = node;
        let mut body = None;
        let mut name = None;
        let mut kind = None;
        if matches!(
            node.kind(),
            "function_declaration"
                | "generator_function_declaration"
                | "class_declaration"
                | "method_definition"
        ) {
            name = Some(text(node.field("name"), self.source)?);
            kind = Some(if node.kind() == "class_declaration" {
                "class"
            } else if node.kind() == "method_definition" || parent_kind == Some("class") {
                "method"
            } else {
                "function"
            });
            body = node.field("body");
        } else if matches!(node.kind(), "variable_declarator" | "assignment_expression")
            && let Some(value) = node.field("value").or_else(|| node.field("right"))
            && matches!(
                value.kind(),
                "arrow_function" | "function_expression" | "generator_function"
            )
        {
            name = target(
                node.field("name").or_else(|| node.field("left")),
                self.source,
            )?;
            kind = Some("function");
            body = value.field("body");
            if let Some(name) = &name
                && node.kind() == "variable_declarator"
                && let Some(parent) = node.parent()
                && self.existing.contains_key(&(
                    name.clone(),
                    parent.start_point()[0] + 1,
                    parent.end_point()[0] + 1,
                ))
            {
                carrier = parent;
            }
        }
        if let Some(name) = name.filter(|s| !s.is_empty())
            && let Some(kind) = kind
        {
            let qualified = qualified(owner, &name);
            let bare = name.rsplit('.').next().unwrap_or(&name);
            let key = (
                bare.to_owned(),
                carrier.start_point()[0] + 1,
                carrier.end_point()[0] + 1,
            );
            let (index, item) = if let Some(&index) = self.existing.get(&key) {
                let symbol = &mut self.out.symbols[index];
                symbol.qualname = qualified.clone();
                symbol.kind = kind.into();
                (index, symbol.clone())
            } else {
                let index = self.next;
                self.next += 1;
                let mut item = symbol(carrier, kind, bare.into(), "", None);
                item.qualname = qualified.clone();
                (index, item)
            };
            self.scopes
                .insert(index, scopes::scope(self.source, carrier, item, body));
            if let Some(body) = body {
                for child in body.named_children() {
                    self.walk(child, &qualified, Some(kind))?;
                }
            }
            return Ok(());
        }
        for child in node.named_children() {
            self.walk(child, owner, parent_kind)?;
        }
        Ok(())
    }
}
