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
    validate(pending, &tree.span)
}
pub(crate) fn clause(c: &Clause) -> Result<()> {
    validate(vec![(Node::Clause(c), 1)], &c.span)
}
fn validate(mut pending: Vec<(Node<'_>, usize)>, span: &Span) -> Result<()> {
    while let Some((node, depth)) = pending.pop() {
        if depth > MAX_AST_DEPTH {
            return Err(ParseError::resource(
                "prepared AST depth limit exceeded",
                span.clone(),
            ));
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
