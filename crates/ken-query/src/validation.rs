//! Bound caller-supplied ASTs before any recursive clone or rewrite.
use crate::{ParseError, Result, ast::*};
enum Node<'a> {
    Declaration(&'a Declaration),
    Clause(&'a Clause),
    Expr(&'a Expr),
    Source(&'a SourceExpr),
    Type(&'a TypeName),
}
pub(crate) fn tree(tree: &File) -> Result<()> {
    let pending: Vec<_> = tree
        .declarations
        .iter()
        .map(|d| (Node::Declaration(d), 1usize))
        .collect();
    validate(
        pending,
        &tree.span,
        MAX_AST_DEPTH,
        "prepared AST depth limit exceeded",
    )
}
pub(crate) fn clause(c: &Clause) -> Result<()> {
    validate(
        vec![(Node::Clause(c), 1)],
        &c.span,
        MAX_AST_DEPTH,
        "prepared AST depth limit exceeded",
    )
}
pub(crate) fn compiled_tree(tree: &File) -> Result<()> {
    // Python visits each dataclass field at depth+1, including scalar/empty
    // tuple fields; every AST record has such a field, so a record at96 fails.
    let pending = tree
        .declarations
        .iter()
        .map(|d| (Node::Declaration(d), 1))
        .collect();
    validate(pending, &tree.span, 95, "compiled AST depth limit exceeded")
}
fn validate(
    mut pending: Vec<(Node<'_>, usize)>,
    span: &Span,
    maximum: usize,
    message: &str,
) -> Result<()> {
    while let Some((node, depth)) = pending.pop() {
        if depth > maximum {
            return Err(ParseError::resource(message, span.clone()));
        }
        let next = depth + 1;
        match node {
            Node::Declaration(d) => {
                pending.extend(d.members.iter().map(|d| (Node::Declaration(d), next)));
                pending.extend(d.clauses.iter().map(|c| (Node::Clause(c), next)));
                pending.extend(d.formula.iter().map(|e| (Node::Expr(e), next)));
                pending.extend(
                    d.parameters
                        .iter()
                        .map(|p| (Node::Type(&p.r#type), next + 1)),
                );
            }
            Node::Clause(c) => {
                pending.extend(c.blocks.iter().flatten().map(|c| (Node::Clause(c), next)));
                pending.extend(c.expressions.iter().map(|e| (expression(e), next)));
                pending.extend(
                    c.parameters
                        .iter()
                        .map(|p| (Node::Type(&p.r#type), next + 1)),
                );
            }
            Node::Expr(e) => {
                pending.extend(e.args.iter().map(|e| (Node::Expr(e), next)));
                pending.extend(
                    e.parameters
                        .iter()
                        .map(|p| (Node::Type(&p.r#type), next + 1)),
                );
            }
            Node::Source(e) => pending.extend(e.args.iter().map(|e| (expression(e), next))),
            Node::Type(t) => pending.extend(t.arguments.iter().map(|t| (Node::Type(t), next))),
        }
    }
    Ok(())
}
fn expression(e: &Expression) -> Node<'_> {
    match e {
        Expression::Query(e) => Node::Expr(e),
        Expression::Source(e) => Node::Source(e),
    }
}
