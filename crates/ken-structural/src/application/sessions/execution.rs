//! Adapt each compiled backend to the same detached, lossless public outcome.
use super::*;
use ken_program::value::GraphValue;
use ken_query::{
    execution::{
        Execution, ExecutionOptions, Planning, QueryBudget,
        indexed_runtime::{IndexedExecution, IndexedOptions, IndexedOutcome},
        values::Value,
    },
    relational::PlanValue,
};
pub(super) fn local_hazards(compiled: &CompiledQuery) -> bool {
    !compiled.program.graph.is_empty()&&compiled.relational.as_ref().is_some_and(|query|!query.nodes.is_empty()&&query.definitions.items().is_empty()&&query.nodes.iter().all(|n|n.kind=="fact"&&matches!(&n.value,PlanValue::Edge(edge)if edge.mode=="require"&&edge.relation=="HAS_HAZARD")))
}
fn stopped(reason: &str) -> IndexedOutcome {
    IndexedOutcome {
        complete: false,
        reason: Some(reason.into()),
        ..Default::default()
    }
}
fn elapsed_ms(started: Instant, outcome: &mut IndexedOutcome) {
    outcome.elapsed_ms = started.elapsed().as_secs_f64() * 1000.;
}
pub(super) fn snapshot_expired(error: &SessionError) -> bool {
    matches!(
        error,
        SessionError::Store(StructuralError::Expired)
            | SessionError::Build(BuildError::Store(StructuralError::Expired))
            | SessionError::Execution(ExecutionError::Exhausted("snapshot_expired"))
    )
}
pub(super) fn run(
    revision: &Revision,
    compiled: &CompiledQuery,
    options: &QueryOptions,
    deadline: Option<Instant>,
) -> Result<IndexedOutcome> {
    let started = Instant::now();
    match run_retained(revision, compiled, options, deadline) {
        Err(error) if snapshot_expired(&error) => {
            let mut outcome = stopped("snapshot_expired");
            elapsed_ms(started, &mut outcome);
            Ok(outcome)
        }
        outcome => outcome,
    }
}
fn run_retained(
    revision: &Revision,
    compiled: &CompiledQuery,
    options: &QueryOptions,
    deadline: Option<Instant>,
) -> Result<IndexedOutcome> {
    let started = Instant::now();
    match revision
        .project
        .source_store()
        .check_pinned_snapshot(revision.snapshot)
    {
        Ok(()) => (),
        Err(StructuralError::Expired) => return Ok(stopped("snapshot_expired")),
        Err(error) => return Err(error.into()),
    }
    let remaining =
        deadline.map(|d| d.saturating_duration_since(Instant::now()).as_secs_f64() * 1000.);
    if let Some(query) = &compiled.relational {
        if options.cancellation.is_cancelled() {
            return Ok(stopped("cancelled"));
        }
        if remaining.is_some_and(|m| m <= 0.) {
            return Ok(stopped("timeout_ms"));
        }
        let execution = Execution::new(ExecutionOptions {
            budget: QueryBudget {
                max_rows: options.max_rows,
                max_states: options.max_states,
                max_matches: options.max_rows,
                timeout_ms: remaining.map(|ms| ms.ceil().max(1.).min(u64::MAX as f64) as u64),
            },
            planning: if options.reference {
                Planning::AuthorOrder
            } else {
                Planning::Selective
            },
            cancellation: options.cancellation.clone(),
            ..Default::default()
        })?;
        let interruption = execution.interruption();
        let poll = interruption.clone();
        let mut initial = true;
        let mut index = revision.project.retained_index()?;
        let scope = index.execution(move || {
            if std::mem::take(&mut initial) {
                false
            } else {
                poll.interrupted()
            }
        })?;
        let snapshot =
            crate::GraphSnapshot::new(&scope, interruption).with_coverage(revision.coverage);
        let graph = execution.execute(&snapshot, query)?;
        let mut rows = vec![];
        for matched in &graph.matches {
            let mut row = vec![];
            for (name, _) in query.exports.items() {
                let id = matched.bindings.get(&format!("${name}")).ok_or_else(|| {
                    SessionError::Invalid(format!("graph export is unbound: {name}"))
                })?;
                row.push(if let Some(metadata) = graph.usage_metadata.get(id) {
                    let mut values = vec![("id".into(), GraphValue::String(id.as_str().into()))];
                    values.extend(
                        metadata
                            .iter()
                            .map(|(name, value)| (name.as_str().into(), value.clone())),
                    );
                    Value::Scalar(GraphValue::Dict(values))
                } else {
                    Value::string(id.as_str())
                });
            }
            rows.push(row);
        }
        let mut outcome = IndexedOutcome {
            rows,
            complete: graph.complete,
            unknown_candidates: graph
                .unknown
                .iter()
                .filter(|r| !r.starts_with("budget:"))
                .count() as u64,
            reason: graph.unknown.first().cloned(),
            states: graph.stats.states,
            scanned_nodes: graph.stats.rows_examined,
            plan: vec![
                json!({"operator":"relational_graph","acquisition":"linked_graph","optimized":!options.reference,"graph_disk_hit":true,"patterns":query.definitions.items().len(),"branches":"preserved"}),
            ],
            optional_evidence: graph
                .matches
                .iter()
                .enumerate()
                .map(|(i, m)| json!({"row":i,"evidence":m.evidence}))
                .collect(),
            ..Default::default()
        };
        if options.profile {
            outcome.profile.push(json!({"operator":"relational_graph","states":outcome.states,"rows_examined":outcome.scanned_nodes,"output_rows":outcome.rows.len()}));
        }
        elapsed_ms(started, &mut outcome);
        Ok(outcome)
    } else {
        let execution = IndexedExecution::new(IndexedOptions {
            timeout_ms: remaining,
            max_states: options.max_states,
            max_rows: options.max_rows,
            reference: options.reference,
            profile: options.profile,
            cancellation: options.cancellation.clone(),
        })?;
        let interruption = execution.interruption();
        let poll = interruption.clone();
        let mut initial = true;
        let mut index = revision.project.retained_index()?;
        let scope = index.execution(move || {
            if std::mem::take(&mut initial) {
                false
            } else {
                poll.interrupted()
            }
        })?;
        let snapshot =
            crate::GraphSnapshot::indexed(&scope, interruption).with_coverage(revision.coverage);
        Ok(execution.execute(&snapshot, &compiled.program)?)
    }
}
