//! Bounded local snapshots retain origin/write correlation before return summaries.
mod emit;
mod iteration;
mod regions;
mod walk;
use super::{append, fact, index::Context};
use crate::{Entity, Fact, ProgramError, StructuralIr, attributes};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, ProgramError>;
pub type ReturnOrigins = BTreeMap<(String, String), BTreeSet<String>>;
type Case = (Option<String>, Option<String>);
type Cases = BTreeSet<Case>;
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
enum Slot {
    Binding(String),
    Field(String, String),
}
type Environment = BTreeMap<Slot, Cases>;
const CONTAINERS: &[&str] = &[
    "expression_statement",
    "lexical_declaration",
    "variable_declaration",
    "local_variable_declaration",
    "local_declaration_statement",
    "declaration",
    "return_statement",
    "statement_list",
];
const BLOCKED: &[&str] = &[
    "global_statement",
    "nonlocal_statement",
    "delete_statement",
    "update_expression",
    "augmented_assignment",
    "augmented_assignment_expression",
    "goto_statement",
    "labeled_statement",
    "lock_statement",
    "unsafe_statement",
    "synchronized_statement",
    "named_expression",
    "ERROR",
];
fn unknown() -> Cases {
    [(None, None)].into_iter().collect()
}
fn pairs(graph: &StructuralIr, relation: &str) -> BTreeMap<String, String> {
    graph
        .facts
        .iter()
        .filter(|f| f.relation == relation)
        .map(|f| (f.subject.clone(), f.object.clone()))
        .collect()
}
struct Inputs<'a> {
    ctx: Context<'a>,
    targets: BTreeMap<String, String>,
    values: BTreeMap<String, String>,
    returns: BTreeMap<String, String>,
    references: BTreeMap<String, String>,
    members: BTreeMap<String, String>,
    allocations: BTreeSet<String>,
    arguments: BTreeMap<String, Vec<(i64, String)>>,
    receiver_reads: BTreeMap<String, Vec<(String, String)>>,
    op_entities: BTreeMap<String, String>,
    assigned: BTreeMap<String, BTreeSet<String>>,
    expressions: BTreeMap<String, BTreeSet<(i64, String)>>,
    locals: BTreeMap<String, BTreeSet<String>>,
    parameters: BTreeMap<String, BTreeSet<String>>,
    nested: BTreeSet<String>,
    dynamic: BTreeSet<String>,
}
impl<'a> Inputs<'a> {
    fn new(graph: &'a StructuralIr) -> Result<Self> {
        let ctx = Context::new(graph);
        let mut input = Self {
            ctx,
            targets: pairs(graph, "ASSIGNMENT_TARGET"),
            values: pairs(graph, "ASSIGNMENT_VALUE"),
            returns: pairs(graph, "RETURN_OPERAND"),
            references: pairs(graph, "BINDING_REFERENCE"),
            members: pairs(graph, "MEMBER_OF"),
            allocations: graph
                .facts
                .iter()
                .filter(|f| f.relation == "ALLOCATES_TYPE")
                .map(|f| f.subject.clone())
                .collect(),
            arguments: BTreeMap::new(),
            receiver_reads: BTreeMap::new(),
            op_entities: BTreeMap::new(),
            assigned: BTreeMap::new(),
            expressions: BTreeMap::new(),
            locals: BTreeMap::new(),
            parameters: BTreeMap::new(),
            nested: BTreeSet::new(),
            dynamic: BTreeSet::new(),
        };
        let call_ops = graph
            .operations
            .iter()
            .enumerate()
            .filter(|(_, o)| o.kind == "CALL")
            .map(|(i, o)| ((o.owner.clone(), o.start, o.end), i))
            .collect::<BTreeMap<_, _>>();
        let mut entity_ops = BTreeMap::new();
        for (_, entity) in &graph.entities {
            if entity.kind != "CALL" {
                continue;
            }
            let owner = attributes::get(&entity.attrs, "owner")?;
            let (Some(owner), Some(start), Some(end)) = (
                owner.as_ref().and_then(Value::as_str),
                super::contexts::coordinate(&entity.attrs, "start_byte")?,
                super::contexts::coordinate(&entity.attrs, "end_byte")?,
            ) else {
                continue;
            };
            if let Some(&i) = call_ops.get(&(owner.into(), start, end)) {
                entity_ops.insert(entity.id.clone(), i);
                input
                    .op_entities
                    .insert(input.ctx.op(i).id.clone(), entity.id.clone());
            }
        }
        for (read, binding) in &input.references {
            let Some(&i) = input.ctx.ids.get(read.as_str()) else {
                continue;
            };
            let Some(parent) = input.ctx.parent(i) else {
                continue;
            };
            let op = input.ctx.op(i);
            let parent = input.ctx.op(parent);
            if op.role == "object"
                && parent.kind == "MEMBER"
                && parent.role == "function"
                && parent
                    .parent
                    .as_ref()
                    .is_some_and(|p| input.op_entities.contains_key(p))
            {
                input
                    .receiver_reads
                    .entry(parent.parent.clone().unwrap())
                    .or_default()
                    .push((read.clone(), binding.clone()));
            }
        }
        for f in &graph.facts {
            match f.relation.as_str() {
                "ARGUMENT" => {
                    if let Some(&i) = entity_ops.get(&f.subject) {
                        input
                            .arguments
                            .entry(input.ctx.op(i).id.clone())
                            .or_default()
                            .push((
                                attributes::integer(&f.attrs, "position", 0)?,
                                f.object.clone(),
                            ));
                    }
                }
                "ASSIGNED_FROM" => {
                    input
                        .assigned
                        .entry(f.subject.clone())
                        .or_default()
                        .insert(f.object.clone());
                }
                "EXPRESSION_OPERAND" => {
                    input
                        .expressions
                        .entry(f.subject.clone())
                        .or_default()
                        .insert((
                            attributes::integer(&f.attrs, "position", 0)?,
                            f.object.clone(),
                        ));
                }
                "DECLARES" if input.ctx.entity(&f.object)?.kind == "STORAGE" => {
                    input
                        .locals
                        .entry(f.subject.clone())
                        .or_default()
                        .insert(f.object.clone());
                }
                "HAS_PARAMETER" if !attributes::truth(&f.attrs, "receiver")? => {
                    input
                        .parameters
                        .entry(f.subject.clone())
                        .or_default()
                        .insert(f.object.clone());
                    input
                        .locals
                        .entry(f.subject.clone())
                        .or_default()
                        .insert(f.object.clone());
                }
                "OWNED_BY" if input.ctx.entity(&f.subject)?.kind == "CALLABLE" => {
                    input.nested.insert(f.object.clone());
                }
                "CALLEE_NAME" => {
                    if matches!(
                        f.object.as_str(),
                        "eval" | "exec" | "locals" | "globals" | "_getframe" | "currentframe"
                    ) && let Some(Value::String(owner)) =
                        attributes::get(&input.ctx.entity(&f.subject)?.attrs, "owner")?
                    {
                        input.dynamic.insert(owner);
                    }
                }
                _ => {}
            }
        }
        Ok(input)
    }
}
struct Owner<'a, 'b> {
    input: &'a Inputs<'b>,
    id: String,
    ops: Vec<usize>,
    locals: BTreeSet<String>,
    parameters: BTreeSet<String>,
    member_writes: BTreeMap<String, String>,
    return_ops: Vec<usize>,
    body: String,
    arms: BTreeMap<String, BTreeMap<String, String>>,
    conditions: BTreeMap<String, Vec<(String, String)>>,
    regions: BTreeSet<String>,
    reason: String,
    diagnostics: bool,
    events: BTreeMap<String, Vec<usize>>,
    escaped: BTreeSet<String>,
    work: usize,
    pending: BTreeMap<String, Cases>,
    arg_pending: BTreeMap<String, BTreeMap<(i64, String), Cases>>,
    expression_pending: BTreeMap<String, BTreeMap<i64, Cases>>,
    assignment_pending: BTreeMap<String, Cases>,
    read_pending: BTreeMap<String, Cases>,
    field_returns: BTreeMap<(String, String, String, String), usize>,
    return_states: BTreeMap<String, usize>,
    arg_order: Vec<String>,
    expression_order: Vec<String>,
    assignment_order: Vec<String>,
    read_order: Vec<String>,
}
impl<'a, 'b> Owner<'a, 'b> {
    fn entity(&self) -> Result<&'b Entity> {
        self.input.ctx.entity(&self.id)
    }
    fn emit_status(&self, reason: &str) -> Fact {
        fact(
            &self.id,
            "RETURN_FLOW_STATUS",
            if reason.is_empty() {
                "supported"
            } else {
                "unsupported"
            },
            None,
            if reason.is_empty() {
                json!({"analysis":"structured-locals/3","scope":"explicit-returns-local-binding-origins"})
            } else {
                json!({"analysis":"structured-locals/3","reason":reason})
            },
        )
    }
    fn set_reason(&mut self, reason: &str) {
        if self.reason.is_empty() {
            self.reason = reason.into();
        }
    }
}
/// Snapshot evaluated local origins, preserving explicit refusal and bounded work.
/// Results override allocation summaries for (callable, returned operand), not all
/// runtime values. Facts are appended only after each admitted owner succeeds.
pub fn sequential_returns(
    graph: &mut StructuralIr,
    diagnostic_paths: Option<&BTreeSet<String>>,
) -> Result<ReturnOrigins> {
    let inputs = Inputs::new(graph)?;
    let mut output = Vec::new();
    let mut result = ReturnOrigins::new();
    let mut seen = BTreeSet::new();
    for op in &graph.operations {
        if !seen.insert(op.owner.clone()) {
            continue;
        }
        let Some(mut owner) = Owner::prepare(&inputs, &op.owner, diagnostic_paths)? else {
            continue;
        };
        owner.iteration_origins(&mut output)?;
        if !owner.reason.is_empty() {
            output.push(owner.emit_status(&owner.reason));
            continue;
        }
        owner.prepare_events()?;
        let environment = owner
            .parameters
            .iter()
            .map(|p| {
                (
                    Slot::Binding(p.clone()),
                    [(Some(p.clone()), None)].into_iter().collect(),
                )
            })
            .collect();
        let body = owner.body.clone();
        if let Err(reason) = owner.walk(&body, environment, 0) {
            owner.reason = reason.into();
        }
        if owner
            .pending
            .values()
            .flatten()
            .any(|(value, _)| value.is_none())
        {
            owner.set_reason("unknown-binding");
        }
        if !owner.reason.is_empty() {
            output.push(owner.emit_status(&owner.reason));
            continue;
        }
        owner.emit(&mut output, &mut result)?;
        output.push(owner.emit_status(""));
    }
    append(graph, output);
    Ok(result)
}
