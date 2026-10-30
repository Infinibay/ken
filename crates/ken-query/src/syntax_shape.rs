//! Reject broken persisted/built records before indexing mandatory grammar slots.
//! Semantic capability errors still belong to the compiler, not this shape gate.
use crate::{ParseError, Result, ast::*, operands::Operand};
pub(crate) fn tree(tree: &File) -> Result<()> {
    let mut pending: Vec<_> = tree.declarations.iter().collect();
    while let Some(d) = pending.pop() {
        pending.extend(&d.members);
        for c in &d.clauses {
            clause(c)?;
        }
        if let Some(e) = &d.formula {
            expression(Operand::Query(e))?;
        }
    }
    Ok(())
}
pub(crate) fn clause(c: &Clause) -> Result<()> {
    let mut pending = vec![c];
    while let Some(c) = pending.pop() {
        let invalid = || ParseError::new("malformed syntax record", c.span.clone());
        if matches!(
            c.kind.as_str(),
            "selector"
                | "not"
                | "optional"
                | "body"
                | "initializer"
                | "construct"
                | "call"
                | "fields"
                | "parameters"
                | "iterate"
                | "gap"
        ) && c.blocks.is_empty()
        {
            return Err(invalid());
        }
        let minimum = match c.kind.as_str() {
            "property" | "where" | "bind" | "if" | "while" | "insert" => 1,
            "assign" => 2,
            _ => 0,
        };
        if c.expressions.len() < minimum {
            return Err(invalid());
        }
        if c.kind == "limit" && (c.name.is_empty() || !c.name.bytes().all(|b| b.is_ascii_digit())) {
            return Err(invalid());
        }
        for e in &c.expressions {
            expression(e.into())?;
        }
        pending.extend(c.blocks.iter().flatten());
    }
    Ok(())
}
fn expression(root: Operand<'_>) -> Result<()> {
    let mut pending = vec![root];
    while let Some(e) = pending.pop() {
        let len = e.len();
        let valid = match e.kind() {
            "unary" | "postfix" | "argument" => len == 1,
            "binary" | "index" | "type_test" => len == 2,
            "member" => len >= 1,
            "quantifier" if e.value() == "exists" => len >= 1,
            "quantifier" | "aggregate" => len >= 2,
            _ => true,
        };
        if !valid {
            return Err(ParseError::new(
                "malformed expression record",
                e.span().clone(),
            ));
        }
        pending.extend(e.args());
    }
    Ok(())
}
