//! Shared source scopes, comments and attributes from the existing syntax tree.
use crate::{
    ParseError, SyntaxNode,
    helpers::{lines, text, trim, trim_end},
    model::{ParsedFile, ParsedScope, ParsedSymbol},
};
use regex::Regex;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::OnceLock,
};

pub(crate) fn enrich(
    source: &[u8],
    root: SyntaxNode<'_>,
    parsed: &mut ParsedFile,
) -> Result<(), ParseError> {
    parsed.scopes.extend(
        indexed(source, root, &parsed.symbols)?
            .into_iter()
            .map(|(_, scope)| scope),
    );
    Ok(())
}

pub(crate) fn indexed(
    source: &[u8],
    root: SyntaxNode<'_>,
    symbols: &[ParsedSymbol],
) -> Result<Vec<(usize, ParsedScope)>, ParseError> {
    let mut result = Vec::new();
    let mut spans: BTreeMap<(usize, usize), Vec<SyntaxNode<'_>>> = BTreeMap::new();
    let mut pending = vec![root];
    while let Some(node) = pending.pop() {
        spans
            .entry((node.start_point()[0] + 1, node.end_point()[0] + 1))
            .or_default()
            .push(node);
        pending.extend(node.named_children());
    }
    for (index, symbol) in symbols.iter().enumerate() {
        let Some(nodes) = spans.get(&(symbol.line_start, symbol.line_end)) else {
            continue;
        };
        let definitions: Vec<_> = nodes
            .iter()
            .copied()
            .filter(|n| {
                ["declaration", "definition", "_item", "declarator"]
                    .iter()
                    .any(|tag| n.kind().contains(tag))
            })
            .collect();
        let candidates = if definitions.is_empty() {
            nodes.as_slice()
        } else {
            definitions.as_slice()
        };
        if let Some(node) = candidates
            .iter()
            .min_by_key(|n| n.end_byte() - n.start_byte())
        {
            result.push((index, scope(source, *node, symbol.clone(), None)?));
        }
    }
    Ok(result)
}

pub(crate) fn scope(
    source: &[u8],
    node: SyntaxNode<'_>,
    symbol: ParsedSymbol,
    body: Option<SyntaxNode<'_>>,
) -> Result<ParsedScope, ParseError> {
    let body = body.or_else(|| node.field("body")).or_else(|| {
        node.field("value")
            .or_else(|| node.field("right"))
            .and_then(|v| v.field("body"))
    });
    let end = body.map_or(node.end_byte(), |n| n.start_byte());
    let signature = String::from_utf8_lossy(&source[node.start_byte()..end]);
    let mut signature = trim_end(&signature).to_owned();
    let annotations = annotations(source, node)?;
    let prefix: Vec<_> = annotations
        .iter()
        .filter(|a| !signature.contains(a.as_str()))
        .cloned()
        .collect();
    if !prefix.is_empty() {
        signature = prefix.join("\n") + "\n" + &signature;
    }
    let mut comment_owner = node;
    while let Some(parent) = comment_owner.parent() {
        if !matches!(
            parent.kind(),
            "export_statement"
                | "lexical_declaration"
                | "variable_declaration"
                | "expression_statement"
        ) {
            break;
        }
        comment_owner = parent;
    }
    let mut previous = comment_owner.previous_named_sibling();
    let mut comments = Vec::new();
    while let Some(comment) = previous {
        if comment.kind().contains("comment") {
            let markers = comment.named_children();
            if markers
                .iter()
                .any(|n| n.kind() == "inner_doc_comment_marker")
            {
                break;
            }
            if let Some(prior) = comment.previous_named_sibling()
                && !prior.kind().contains("comment")
                && prior.kind() != "attribute_item"
                && !markers
                    .iter()
                    .any(|n| n.kind() == "outer_doc_comment_marker")
                && prior.end_point()[0] == comment.start_point()[0]
            {
                break;
            }
            comments.push(
                text(comment, source)
                    .trim_end_matches(['\r', '\n'])
                    .to_owned(),
            );
        } else if comment.kind() != "attribute_item" {
            break;
        }
        previous = comment.previous_named_sibling();
    }
    let mut documentation = symbol.docstring.clone();
    if !comments.is_empty() {
        static BLOCK: OnceLock<Regex> = OnceLock::new();
        static MARGIN: OnceLock<Regex> = OnceLock::new();
        comments.reverse();
        let raw = comments.join("\n");
        let text = BLOCK
            .get_or_init(|| Regex::new(r"/\*+|\*/").expect("static comment expression"))
            .replace_all(&raw, "");
        let margin = MARGIN.get_or_init(|| {
            Regex::new(r"^[\s\x1c-\x1f]*(?:///|//|\*)[\s\x1c-\x1f]?")
                .expect("static comment margin")
        });
        let cleaned = lines(&text)
            .map(|line| margin.replace(line, "").into_owned())
            .collect::<Vec<_>>()
            .join("\n");
        let cleaned = trim(&cleaned);
        if !cleaned.is_empty() {
            documentation = Some(cleaned.to_owned());
        }
    }
    let owner = symbol
        .qualname
        .rsplit_once('.')
        .map(|(owner, _)| owner.to_owned());
    let statements = body.map(|b| b.named_children()).unwrap_or_default();
    let implementation_start_line = Some(
        statements
            .iter()
            .find(|n| !n.kind().contains("comment"))
            .map_or(symbol.line_start, |n| n.start_point()[0] + 1),
    );
    Ok(ParsedScope {
        symbol,
        signature,
        documentation: documentation.map(Into::into),
        owner,
        statements: statements
            .iter()
            .map(|n| (n.start_point()[0] + 1, n.end_point()[0] + 1))
            .collect(),
        implementation_start_line,
        annotations,
    })
}

fn annotations(source: &[u8], node: SyntaxNode<'_>) -> Result<Vec<String>, ParseError> {
    let mut items = Vec::new();
    let mut current = Some(node);
    while let Some(node) = current {
        let mut previous = node.previous_named_sibling();
        while let Some(previous_node) = previous {
            if matches!(
                previous_node.kind(),
                "attribute_item" | "decorator" | "annotation"
            ) {
                items.push(
                    std::str::from_utf8(
                        &source[previous_node.start_byte()..previous_node.end_byte()],
                    )?
                    .to_owned(),
                );
            } else if !previous_node.kind().contains("comment") {
                break;
            }
            previous = previous_node.previous_named_sibling();
        }
        current = node.parent();
    }
    let mut seen = BTreeSet::new();
    Ok(items
        .into_iter()
        .rev()
        .filter(|item| seen.insert(item.clone()))
        .collect())
}
