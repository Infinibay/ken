//! Source type patterns have their own rules, separate from query scalar types.
use crate::{ParseError, Result, ast::Expr, capabilities::vocabulary};
pub(crate) fn validate_matcher(expr: &Expr) -> Result<()> {
    crate::with_stack(|| {
        if expr.kind == "wildcard" {
            return Ok(());
        }
        if expr.kind == "call" && expr.value == "oneof" && !expr.args.is_empty() {
            for arg in &expr.args {
                if !arg.value.is_empty() {
                    return Err(ParseError::new(
                        "oneof expects positional type matchers",
                        arg.span.clone(),
                    ));
                }
                let Some(value) = arg.args.first() else {
                    return Err(ParseError::new(
                        "unknown source type matcher",
                        arg.span.clone(),
                    ));
                };
                validate_matcher(value)?;
            }
            return Ok(());
        }
        if !(matches!(expr.kind.as_str(), "name" | "source_type")
            || expr.kind == "literal" && expr.value == "null")
            || !vocabulary().source_aliases.contains_key(&expr.value)
        {
            return Err(ParseError::new(
                "unknown source type matcher",
                expr.span.clone(),
            ));
        }
        let arity = match expr.value.as_str() {
            "array" | "slice" | "list" | "set" | "optional" | "reference" | "pointer" => Some(1),
            "map" => Some(2),
            _ => None,
        };
        if !expr.args.is_empty() {
            if let Some(n) = arity {
                if expr.args.len() != n {
                    return Err(ParseError::new(
                        "source type matcher arity mismatch",
                        expr.span.clone(),
                    ));
                }
            } else if !matches!(expr.value.as_str(), "tuple" | "union") {
                return Err(ParseError::new(
                    "primitive type does not take type arguments",
                    expr.span.clone(),
                ));
            }
        }
        for arg in &expr.args {
            validate_matcher(arg)?;
        }
        Ok(())
    })
}
