use super::index::Context;
use crate::{ProgramError, StructuralIr, attributes};
use std::collections::BTreeMap;
const BLOCKS: &[&str] = &[
    "block",
    "statement_block",
    "compound_statement",
    "statement_list",
];
const ABRUPT: &[&str] = &[
    "return_statement",
    "return_expression",
    "throw_statement",
    "throw_expression",
    "raise_statement",
    "break_statement",
    "continue_statement",
    "break_expression",
    "continue_expression",
];
/// Annotate operations with conservative lexical execution and return statuses by ID.
/// Invalid parser output is entirely unknown, including duplicate IDs and cycles.
pub fn lexical_execution(
    graph: &mut StructuralIr,
    invalid: bool,
) -> Result<BTreeMap<String, String>, ProgramError> {
    let mut status = BTreeMap::new();
    let mut states = vec![None; graph.operations.len()];
    if invalid {
        for (i, op) in graph.operations.iter().enumerate() {
            states[i] = Some("unknown");
            status.insert(op.id.clone(), "unknown".into());
        }
    } else {
        let ctx = Context::new(graph);
        let mut pending = (0..graph.operations.len())
            .filter(|&i| ctx.parent(i).is_none())
            .map(|i| (i, false))
            .collect::<Vec<_>>();
        while let Some((i, dead)) = pending.pop() {
            let op = ctx.op(i);
            if status.contains_key(&op.id) {
                continue;
            }
            let state = if dead { "unreachable" } else { "possible" };
            status.insert(op.id.clone(), state.into());
            states[i] = Some(state);
            let mut suffix_dead = dead;
            for &child in ctx.all_kids(i) {
                let c = ctx.op(child);
                let hoisted = op.native_kind == "function_declaration"
                    && ["body", "parameters"].contains(&c.role.as_str())
                    && attributes::get(&ctx.entity(&op.owner)?.attrs, "language")?
                        .is_some_and(|v| v == "javascript" || v == "typescript");
                pending.push((child, if hoisted { false } else { suffix_dead }));
                if BLOCKS.contains(&op.native_kind.as_str()) {
                    let mut abrupt = ABRUPT.contains(&c.native_kind.as_str());
                    if c.native_kind == "expression_statement" {
                        let parts = ctx
                            .all_kids(child)
                            .iter()
                            .filter(|&&p| !ctx.op(p).native_kind.contains("comment"))
                            .copied()
                            .collect::<Vec<_>>();
                        abrupt = parts.len() == 1
                            && ABRUPT.contains(&ctx.op(parts[0]).native_kind.as_str());
                    }
                    suffix_dead |= abrupt;
                }
            }
        }
        for (i, op) in graph.operations.iter().enumerate() {
            if !status.contains_key(&op.id) {
                status.insert(op.id.clone(), "unknown".into());
                states[i] = Some("unknown");
            }
        }
    }
    for (op, state) in graph.operations.iter_mut().zip(states) {
        if let Some(state) = state {
            op.attrs
                .insert("execution".into(), serde_json::value::to_raw_value(state)?);
        }
    }
    Ok(status)
}
