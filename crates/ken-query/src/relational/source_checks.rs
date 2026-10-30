//! Closed source inventories and occurrence-use filters become operator specs.
use super::{
    ir::*,
    terms::{json_string, matcher},
};
use crate::{Result, ast::*, expression_check::unsupported, operands::Operand};
use std::collections::BTreeSet;
pub(crate) fn requirement(c: &Clause) -> Result<PlanValue> {
    let mut properties = vec![];
    for p in c.blocks.first().map_or(&[][..], Vec::as_slice) {
        if p.kind != "property" || p.name != "visibility" || p.expressions.len() != 1 {
            return Err(unsupported(
                "quantified constructor constraints currently support visibility",
                &p.span,
            ));
        }
        let e = &p.expressions[0];
        let text = e.value().trim_matches('"');
        if !matches!(e.kind(), "name" | "literal")
            || !matches!(
                text,
                "private" | "public" | "protected" | "internal" | "package"
            )
        {
            return Err(unsupported(
                "quantified visibility requires a visibility name",
                &p.span,
            ));
        }
        if !properties.is_empty() {
            return Err(unsupported(
                "duplicate quantified visibility property",
                &p.span,
            ));
        }
        properties.push(PlanValue::tuple(vec![
            PlanValue::text("visibility"),
            PlanValue::text(text),
        ]));
    }
    let quantifier = c
        .flags
        .first()
        .ok_or_else(|| unsupported("missing source quantifier", &c.span))?;
    if quantifier == "one" {
        if !matches!(c.name.as_str(), "allocation" | "dispatch") || !properties.is_empty() {
            return Err(unsupported(
                "one quantifies the resolved allocation or dispatch count only",
                &c.span,
            ));
        }
        properties.push(PlanValue::tuple(vec![
            PlanValue::text("count"),
            PlanValue::text("1"),
        ]));
        if let Some(witness) = c.flags.get(1).filter(|w| !w.is_empty()) {
            properties.push(PlanValue::tuple(vec![
                PlanValue::text("named"),
                PlanValue::text(format!("${witness}")),
            ]));
        }
    }
    if quantifier == "every" && properties.is_empty() {
        return Err(unsupported(
            "every constructor requires a declaration constraint",
            &c.span,
        ));
    }
    Ok(PlanValue::tuple(vec![
        PlanValue::text(quantifier),
        PlanValue::text(&c.name),
        PlanValue::text(format!("${}", c.role)),
        PlanValue::tuple(properties),
    ]))
}
pub(crate) fn usage(c: &Clause, bound: &BTreeSet<String>) -> Result<PlanValue> {
    let mut filters = vec![];
    let mut seen = BTreeSet::new();
    for p in c.blocks.first().map_or(&[][..], Vec::as_slice) {
        if p.kind != "property"
            || !matches!(
                p.name.as_str(),
                "kind" | "position" | "owner" | "consumer" | "path" | "line"
            )
        {
            return Err(unsupported(
                "usages accepts kind, position, owner, consumer, path and line",
                &p.span,
            ));
        }
        if !seen.insert(&p.name) {
            return Err(unsupported("duplicate usage property", &p.span));
        }
        let mut v = crate::indexed::query_expr(p, 0)?.clone();
        if p.name == "kind" {
            if v.kind == "name" {
                v.kind = "literal".into();
                v.value = json_string(&v.value);
            }
            let values: Vec<_> = if v.kind == "list" {
                v.args.iter().collect()
            } else {
                vec![&v]
            };
            if values.is_empty()
                || values.iter().any(|v| {
                    v.kind != "literal"
                        || !serde_json::from_str::<String>(&v.value).is_ok_and(|s| {
                            matches!(
                                s.as_str(),
                                "argument"
                                    | "return"
                                    | "assignment"
                                    | "condition"
                                    | "operand"
                                    | "receiver"
                            )
                        })
                })
            {
                return Err(unsupported("unknown usage kind", &p.span));
            }
        }
        if matches!(p.name.as_str(), "position" | "line")
            && (v.kind != "literal"
                || v.value.is_empty()
                || !v.value.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err(unsupported(
                "usage position/line requires a nonnegative integer",
                &p.span,
            ));
        }
        let (op, text) = if v.kind == "role" {
            if !matches!(p.name.as_str(), "owner" | "consumer") || !bound.contains(&v.value) {
                return Err(unsupported(
                    "usage owner/consumer requires a selected role",
                    &p.span,
                ));
            }
            ("role".into(), format!("${}", v.value))
        } else {
            matcher(Operand::Query(&v))?
        };
        filters.push(PlanValue::tuple(vec![
            PlanValue::text(&p.name),
            PlanValue::text(op),
            PlanValue::text(text),
        ]));
    }
    Ok(PlanValue::tuple(vec![
        PlanValue::text(format!("${}", c.name)),
        PlanValue::text(format!("${}", c.role)),
        PlanValue::tuple(filters),
    ]))
}
