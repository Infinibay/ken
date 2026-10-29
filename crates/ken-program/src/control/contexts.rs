use super::{append, fact, index::Context};
use crate::{ProgramError, StructuralIr, attributes};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
// Locations compare Python dictionary keys, not integer coercions. A null/text
// offset cannot match a syntax span; equal integral floats and booleans can.
pub(super) fn coordinate(
    graph: &crate::Attributes,
    key: &str,
) -> Result<Option<i64>, ProgramError> {
    Ok(match attributes::get(graph, key)? {
        None => Some(-1),
        Some(Value::Bool(value)) => Some(i64::from(value)),
        Some(Value::Number(number)) => number.as_i64().or_else(|| {
            number
                .as_f64()
                .filter(|&value| {
                    value.fract() == 0.0 && value >= i64::MIN as f64 && value < -(i64::MIN as f64)
                })
                .map(|value| value as i64)
        }),
        Some(Value::Null | Value::String(_)) => None,
        _ => {
            return Err(ProgramError::Invalid(
                "unhashable syntax location attribute",
            ));
        }
    })
}
/// Append call/result and lexical ancestry facts; preserve every syntax operation.
/// Run once per newly produced IR, after the control routes have been generated.
pub fn syntax_contexts(graph: &mut StructuralIr) -> Result<(), ProgramError> {
    let ctx = Context::new(graph);
    let mut output = Vec::new();
    let mut call_kinds = BTreeSet::new();
    for (_, entity) in &graph.entities {
        if entity.kind == "CALL" {
            call_kinds.insert(attributes::text(&entity.attrs, "native_kind", "")?);
        }
    }
    let mut locations = BTreeMap::new();
    for (i, op) in graph.operations.iter().enumerate() {
        if call_kinds.contains(&op.native_kind) {
            locations.insert(
                (
                    ctx.entity(&op.owner)?.path.clone(),
                    op.start,
                    op.end,
                    op.native_kind.clone(),
                ),
                i,
            );
        }
    }
    for (_, entity) in &graph.entities {
        if entity.kind != "CALL" {
            continue;
        }
        let (Some(start), Some(end)) = (
            coordinate(&entity.attrs, "start_byte")?,
            coordinate(&entity.attrs, "end_byte")?,
        ) else {
            continue;
        };
        let key = (
            entity.path.clone(),
            start,
            end,
            attributes::text(&entity.attrs, "native_kind", "")?,
        );
        if let Some(&i) = locations.get(&key) {
            let evidence = Some(format!("{}:{}", entity.path, entity.line));
            output.push(fact(
                &entity.id,
                "SYNTAX_NODE",
                &ctx.op(i).id,
                evidence.clone(),
                json!({}),
            ));
            let mut current = i;
            let mut awaited = false;
            for _ in 0..32 {
                let Some(parent) = ctx.parent(current) else {
                    break;
                };
                let p = ctx.op(parent);
                if p.owner != ctx.op(current).owner {
                    break;
                }
                if p.native_kind == "expression_statement" {
                    if attributes::text(&entity.attrs, "language", "")? != "rust"
                        || attributes::tokens(&p.attrs)?.iter().any(|t| t == ";")
                    {
                        output.push(fact(
                            &p.id,
                            "DISCARDS_RESULT",
                            &entity.id,
                            evidence,
                            json!({"awaited":awaited,"basis":"syntax"}),
                        ));
                    }
                    break;
                }
                if !["parenthesized_expression", "await", "await_expression"]
                    .contains(&p.native_kind.as_str())
                {
                    break;
                }
                awaited |= ["await", "await_expression"].contains(&p.native_kind.as_str());
                current = parent;
            }
        }
    }
    // Call locations are not needed while expanding the larger ancestry graph.
    drop(locations);
    let parents = graph
        .operations
        .iter()
        .filter_map(|o| o.parent.as_deref())
        .collect::<BTreeSet<_>>();
    let mut contexts = BTreeMap::<String, (String, String, String)>::new();
    for operation in 0..graph.operations.len() {
        let mut pending = Vec::new();
        let mut current = operation;
        let mut seen = BTreeSet::new();
        while !contexts.contains_key(&ctx.op(current).id) && seen.insert(ctx.op(current).id.clone())
        {
            pending.push(current);
            let Some(parent) = ctx.parent(current) else {
                break;
            };
            if ctx.op(parent).owner != ctx.op(current).owner {
                break;
            }
            current = parent;
        }
        for i in pending.into_iter().rev() {
            let op = ctx.op(i);
            let (mut looping, mut handler, mut protected) =
                (String::new(), String::new(), String::new());
            if let Some(parent) = ctx.parent(i)
                && ctx.op(parent).owner == op.owner
            {
                let p = ctx.op(parent);
                (looping, handler, protected) = contexts.get(&p.id).cloned().unwrap_or_default();
                output.push(fact(&op.id, "SYNTAX_PARENT", &p.id, None, json!({})));
                if p.kind == "LOOP" {
                    looping = p.id.clone();
                }
                if ["except_clause", "catch_clause"].contains(&p.native_kind.as_str()) {
                    handler = p.id.clone();
                }
                if ["try_statement", "try_with_resources_statement"]
                    .contains(&p.native_kind.as_str())
                {
                    protected = if op.role == "body" {
                        p.id.clone()
                    } else {
                        String::new()
                    };
                }
                if ["except_clause", "catch_clause"].contains(&op.native_kind.as_str())
                    && ["try_statement", "try_with_resources_statement"]
                        .contains(&p.native_kind.as_str())
                {
                    output.push(fact(&op.id, "HANDLER_OF", &p.id, None, json!({})));
                }
            }
            contexts.insert(
                op.id.clone(),
                (looping.clone(), handler.clone(), protected.clone()),
            );
            for (relation, target) in [
                ("ENCLOSING_LOOP", &looping),
                ("IN_HANDLER", &handler),
                ("IN_TRY_BODY", &protected),
            ] {
                if !target.is_empty() {
                    output.push(fact(&op.id, relation, target, None, json!({})));
                }
            }
            if op.native_kind == "continue_statement"
                && !parents.contains(op.id.as_str())
                && !looping.is_empty()
            {
                output.push(fact(&op.id, "CONTINUE_TARGET", &looping, None, json!({})));
            }
        }
    }
    append(graph, output);
    Ok(())
}
