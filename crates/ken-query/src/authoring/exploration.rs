//! Syntax-only backend admission remains distinct from declaration/BODY execution.
use super::{Result, SYNTAX_PROPERTIES, SYNTAX_RELATIONS, unsupported};
use crate::{Program, Step, ast::Expr};
fn expression(expr: &Expr) -> Result<()> {
    match expr.kind.as_str() {
        "literal" | "role" => return Ok(()),
        "member" => {
            if !SYNTAX_PROPERTIES.contains(&expr.value.as_str()) {
                return Err(unsupported(
                    format!(
                        "property {}. {}",
                        expr.value,
                        crate::capabilities::property_hint(&expr.value)
                    ),
                    Some(&expr.span),
                ));
            }
        }
        "call" => {
            if !SYNTAX_RELATIONS.contains(&expr.value.as_str()) {
                return Err(unsupported(
                    format!("relation {}", expr.value),
                    Some(&expr.span),
                ));
            }
            for argument in &expr.args {
                if let Some(value) = argument.args.first() {
                    expression(value)?;
                }
            }
            return Ok(());
        }
        "quantifier" | "aggregate" => {
            if !matches!(expr.value.as_str(), "exists" | "forall" | "count") {
                return Err(unsupported(
                    format!("aggregate {}", expr.value),
                    Some(&expr.span),
                ));
            }
            for parameter in &expr.parameters {
                if !matches!(
                    parameter.r#type.name.as_str(),
                    "CodeNode" | "Expression" | "Statement"
                ) {
                    return Err(unsupported(
                        format!("domain {}", parameter.r#type.name),
                        Some(&expr.span),
                    ));
                }
            }
        }
        "binary" if expr.value == "matches" => {
            if let Some(left) = expr.args.first() {
                expression(left)?;
            }
            return Ok(());
        }
        "list" | "unary" | "binary" => {}
        _ => {
            return Err(unsupported(
                format!("expression {}", expr.kind),
                Some(&expr.span),
            ));
        }
    }
    for child in &expr.args {
        expression(child)?;
    }
    Ok(())
}
pub(super) fn validate(program: &Program) -> Result<()> {
    if !program.graph.is_empty() {
        return Err(unsupported(
            "relational graph queries; use the indexed backend until their semantics are ported",
            None,
        ));
    }
    if !program.predicates.is_empty() || !program.enums.is_empty() || !program.optional.is_empty() {
        return Err(unsupported(
            "recursive predicates, enum domains or optional evidence",
            None,
        ));
    }
    if !program.branches.is_empty() {
        for branch in &program.branches {
            validate(branch)?;
        }
        return Ok(());
    }
    for step in crate::exploration::effective_steps(program) {
        match step {
            Step::Scan(scan) => {
                if !matches!(scan.selector.as_str(), "node" | "expression" | "statement") {
                    return Err(unsupported(
                        format!(
                            "selector {}; use --backend indexed for declarations or BODY value flow, or node kind constraints for syntax-only queries",
                            scan.selector
                        ),
                        None,
                    ));
                }
                for (key, expr) in &scan.properties {
                    if !SYNTAX_PROPERTIES.contains(&key.as_str()) {
                        return Err(unsupported(
                            format!(
                                "property {key}. {}",
                                crate::capabilities::property_hint(key)
                            ),
                            Some(&expr.span),
                        ));
                    }
                    if expr.kind == "wildcard" {
                        continue;
                    }
                    if !matches!(expr.kind.as_str(), "literal" | "regex") {
                        return Err(unsupported("nonliteral scan constraint", Some(&expr.span)));
                    }
                }
            }
            Step::Action(action) => expression(&action.expression)?,
            Step::Body(_) => {
                return Err(unsupported(
                    "CFG BODY clauses; use --backend indexed for BODY value flow, or nested node selectors for immediate syntax children",
                    None,
                ));
            }
        }
    }
    for expr in program.projection.iter().chain(&program.ordering) {
        if let Some(value) = expr.args.first() {
            expression(value)?;
        }
    }
    Ok(())
}
