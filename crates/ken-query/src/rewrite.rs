//! One AST topology visitor for name rewrites; immutable inputs are copied once.
use crate::ast::*;
pub(crate) fn query(
    e: &Expr,
    name: &impl Fn(&str, &str) -> String,
    parameter: &impl Fn(&Parameter) -> Parameter,
) -> Expr {
    crate::with_stack(|| Expr {
        kind: e.kind.clone(),
        span: e.span.clone(),
        value: name(&e.kind, &e.value),
        args: e.args.iter().map(|a| query(a, name, parameter)).collect(),
        parameters: e.parameters.iter().map(parameter).collect(),
        depth: e.depth,
    })
}
pub(crate) fn expression(
    e: &Expression,
    name: &impl Fn(&str, &str) -> String,
    parameter: &impl Fn(&Parameter) -> Parameter,
) -> Expression {
    crate::with_stack(|| match e {
        Expression::Query(e) => Expression::Query(query(e, name, parameter)),
        Expression::Source(e) => Expression::Source(SourceExpr {
            kind: e.kind.clone(),
            span: e.span.clone(),
            value: name(&e.kind, &e.value),
            args: e
                .args
                .iter()
                .map(|a| expression(a, name, parameter))
                .collect(),
            depth: e.depth,
        }),
    })
}
pub(crate) fn clause_shell(c: &Clause) -> Clause {
    Clause {
        kind: c.kind.clone(),
        span: c.span.clone(),
        name: c.name.clone(),
        role: c.role.clone(),
        expressions: vec![],
        parameters: c.parameters.clone(),
        blocks: vec![],
        alias: c.alias.clone(),
        flags: c.flags.clone(),
    }
}
pub(crate) fn declaration_shell(d: &Declaration) -> Declaration {
    Declaration {
        kind: d.kind.clone(),
        name: d.name.clone(),
        span: d.span.clone(),
        parameters: d.parameters.clone(),
        generics: d.generics.clone(),
        clauses: vec![],
        formula: None,
        members: vec![],
        values: d.values.clone(),
        implements: d.implements.clone(),
    }
}
pub(crate) fn file(tree: &File, declarations: Vec<Declaration>, imports: Vec<String>) -> File {
    File {
        language: tree.language.clone(),
        module: tree.module.clone(),
        imports,
        declarations,
        span: tree.span.clone(),
    }
}
