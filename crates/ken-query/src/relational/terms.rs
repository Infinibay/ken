//! Canonical endpoint tokens and graph-context matchers.
use super::ir::*;
use crate::{Result, ast::*, expression_check::unsupported, operands::Operand};
pub(crate) fn json_string(value: &str) -> String {
    let json = serde_json::to_string(value).expect("UTF-8 text");
    let mut out = String::new();
    for c in json.chars() {
        let n = c as u32;
        if n < 0x7f {
            out.push(c);
        } else if n <= 0xffff {
            use std::fmt::Write;
            write!(out, "\\u{n:04x}").unwrap();
        } else {
            use std::fmt::Write;
            let n = n - 0x10000;
            write!(
                out,
                "\\u{:04x}\\u{:04x}",
                0xd800 + (n >> 10),
                0xdc00 + (n & 1023)
            )
            .unwrap();
        }
    }
    out
}
pub(crate) fn quoted(token: String, span: &Span) -> Result<Term> {
    let literal = serde_json::from_str::<String>(&token)
        .map_err(|_| unsupported("invalid graph literal token", span))?;
    Ok(Term::Literal(QuotedTerm { token, literal }))
}
pub(crate) fn text_literal(value: &str, span: &Span) -> Result<Term> {
    quoted(json_string(value), span)
}
pub(crate) fn term(e: Operand<'_>) -> Result<Term> {
    crate::with_stack(|| {
        if e.kind() == "role" {
            return Ok(Term::Text(format!("${}", e.value())));
        }
        if e.kind() == "wildcard" {
            return Ok(Term::Text("_".into()));
        }
        if e.kind() == "literal" {
            if e.value().starts_with('"') {
                return quoted(e.value().into(), e.span());
            }
            let digits = e.value().strip_prefix('-').unwrap_or(e.value());
            if !digits.is_empty() && digits.bytes().all(|c| c.is_ascii_digit())
                || matches!(e.value(), "true" | "false" | "null")
            {
                return text_literal(e.value(), e.span());
            }
        }
        if e.kind() == "list" && e.len() > 0 {
            let mut values = vec![];
            for a in e.args() {
                let value = term(a)?;
                let Some(literal) = value.literal().filter(|s| !s.contains('|')) else {
                    return Err(unsupported(
                        "graph endpoint requires a role, literal, wildcard or nonempty literal list",
                        e.span(),
                    ));
                };
                values.push(literal.to_owned());
            }
            return Ok(Term::Text(values.join("|")));
        }
        Err(unsupported(
            "graph endpoint requires a role, literal, wildcard or nonempty literal list",
            e.span(),
        ))
    })
}
pub(crate) fn matcher(e: Operand<'_>) -> Result<(String, String)> {
    if e.kind() == "regex" {
        let Some((pattern, flags)) = e.value().strip_prefix('/').and_then(|v| v.rsplit_once('/'))
        else {
            return Err(unsupported("invalid graph regex record", e.span()));
        };
        let mut seen = std::collections::BTreeSet::new();
        if flags
            .chars()
            .any(|c| !matches!(c, 'i' | 'm' | 's') || !seen.insert(c))
        {
            return Err(unsupported("invalid graph regex record", e.span()));
        }
        if pattern.chars().count() > 512
            || pattern.contains("(?")
            || pattern
                .as_bytes()
                .windows(2)
                .any(|v| v[0] == b'\\' && matches!(v[1], b'1'..=b'9'))
        {
            return Err(unsupported(
                "graph regex must be regular (no backreferences or lookaround)",
                e.span(),
            ));
        }
        crate::regex_syntax::validate(pattern)
            .map_err(|v| unsupported(format!("invalid regular expression: {v}"), e.span()))?;
        return Ok((
            "regex".into(),
            format!(
                "{}{pattern}",
                if flags.is_empty() {
                    String::new()
                } else {
                    format!("(?{flags})")
                }
            ),
        ));
    }
    let value = term(e)?;
    if let Some(v) = value.literal() {
        return Ok(("literal".into(), v.into()));
    }
    if e.kind() == "list" {
        return Ok(("=".into(), value.token().into()));
    }
    Err(unsupported(
        "graph context matcher requires a literal, literal list or regex",
        e.span(),
    ))
}
pub(crate) fn operand(e: &Expr) -> Result<String> {
    if e.kind == "role" {
        return Ok(format!("${}", e.value));
    }
    if e.kind == "member" && e.args.len() == 2 && e.args[1].kind == "role" {
        return Ok(format!("${}.${}", e.args[0].value, e.args[1].value));
    }
    if e.kind == "member" && e.args.first().is_some_and(|a| a.kind == "role") {
        return Ok(format!("${}.{}", e.args[0].value, e.value));
    }
    if e.kind == "literal" {
        return Ok(e.value.clone());
    }
    Err(unsupported(
        "graph comparison requires a role, entity attribute or literal",
        &e.span,
    ))
}
pub(crate) fn attrs_value(attrs: Vec<(String, String, String)>) -> PlanValue {
    PlanValue::Tuple(
        attrs
            .into_iter()
            .map(|(a, b, c)| {
                PlanValue::tuple(vec![
                    PlanValue::text(a),
                    PlanValue::text(b),
                    PlanValue::text(c),
                ])
            })
            .collect(),
    )
}
