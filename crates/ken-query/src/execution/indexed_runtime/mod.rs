//! Indexed query execution over one immutable source snapshot.
//! Planning, expression semantics and source access remain distinct responsibilities.
mod expressions;
mod finalization;
mod pipeline;
mod planning;
mod predicates;
mod relations;
mod source;
use super::source::SourceCache;
use super::values::{Bindings, Value};
use super::{Cancellation, ExecutionError, GraphRead, Interruption, Result};
use crate::{Program, Step, ast::Expr};
use serde::{Deserialize, Serialize};
use serde_json::{Value as Json, json};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    sync::Arc,
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct IndexedOptions {
    pub timeout_ms: Option<f64>,
    pub max_states: Option<u64>,
    pub max_rows: Option<u64>,
    pub reference: bool,
    pub profile: bool,
    #[serde(skip)]
    pub cancellation: Cancellation,
}
#[derive(Clone, Debug, Serialize)]
pub struct IndexedOutcome {
    pub rows: Vec<Vec<Value>>,
    pub complete: bool,
    pub results_truncated: bool,
    pub unknown_candidates: u64,
    pub reason: Option<String>,
    pub scanned_nodes: u64,
    pub states: u64,
    pub elapsed_ms: f64,
    pub plan: Vec<Json>,
    pub optional_evidence: Vec<Json>,
    pub order_keys: Vec<Vec<Value>>,
    pub profile: Vec<Json>,
}
impl Default for IndexedOutcome {
    fn default() -> Self {
        Self {
            rows: vec![],
            complete: true,
            results_truncated: false,
            unknown_candidates: 0,
            reason: None,
            scanned_nodes: 0,
            states: 0,
            elapsed_ms: 0.0,
            plan: vec![],
            optional_evidence: vec![],
            order_keys: vec![],
            profile: vec![],
        }
    }
}
pub struct IndexedExecution {
    options: IndexedOptions,
    started: Instant,
    interruption: Interruption,
}
impl IndexedExecution {
    pub fn new(options: IndexedOptions) -> Result<Self> {
        if options
            .timeout_ms
            .is_some_and(|ms| !ms.is_finite() || ms < 0.0)
            || options.max_states == Some(0)
            || options.max_rows == Some(0)
        {
            return Err(invalid("invalid execution budget"));
        }
        let started = Instant::now();
        let deadline = options
            .timeout_ms
            .map(|ms| {
                let duration = Duration::try_from_secs_f64(ms / 1000.0)
                    .map_err(|_| invalid("query timeout is out of range"))?;
                started
                    .checked_add(duration)
                    .ok_or_else(|| invalid("query timeout is out of range"))
            })
            .transpose()?;
        let interruption = Interruption {
            deadline,
            cancellation: options.cancellation.clone(),
        };
        Ok(Self {
            options,
            started,
            interruption,
        })
    }
    pub fn interruption(&self) -> Interruption {
        self.interruption.clone()
    }
    pub fn execute(self, graph: &dyn GraphRead, program: &Program) -> Result<IndexedOutcome> {
        let mut run = Run {
            execution: self,
            out: IndexedOutcome::default(),
            materialized: vec![],
            seen: BTreeSet::new(),
            initial_checked: true,
            initial_steps: None,
        };
        run.prime(program)?;
        let result = run
            .check(graph)
            .and_then(|()| validate(program, &run.execution.interruption))
            .and_then(|()| run.branch(graph, program, None));
        if let Err(error) = result {
            match error {
                ExecutionError::Exhausted(reason) => run.stopped(reason),
                other => return Err(other),
            }
        }
        if let Err(error) = run.finish(program) {
            match error {
                ExecutionError::Exhausted(reason) => run.stopped(reason),
                other => return Err(other),
            }
        }
        run.out.elapsed_ms = run.execution.started.elapsed().as_secs_f64() * 1000.0;
        Ok(run.out)
    }
}
pub fn execute_indexed(
    graph: &dyn GraphRead,
    program: &Program,
    options: IndexedOptions,
) -> Result<IndexedOutcome> {
    IndexedExecution::new(options)?.execute(graph, program)
}
fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}
pub(crate) fn validate(program: &Program, interruption: &Interruption) -> Result<()> {
    let mut programs = vec![(program, 0usize)];
    let mut work = 0usize;
    while let Some((p, depth)) = programs.pop() {
        interruption.check()?;
        work += 1;
        if depth > 128 || work > 65536 {
            return Err(invalid("indexed program nesting limit exceeded"));
        }
        if !p.graph.is_empty() {
            return Err(ExecutionError::Unsupported(
                "indexed execution cannot execute a relational program".into(),
            ));
        }
        if p.steps.len() > 4096 || p.scans.len() > 4096 {
            return Err(invalid("indexed pipeline length limit exceeded"));
        }
        crate::predicate_components(&p.predicates).map_err(|e| invalid(e.to_string()))?;
        let mut expressions: Vec<&Expr> = p
            .filters
            .iter()
            .chain(&p.optional)
            .chain(&p.projection)
            .chain(&p.ordering)
            .chain(p.actions.iter().map(|(_, e)| e))
            .chain(p.predicates.iter().map(|p| &p.formula))
            .collect();
        for scan in &p.scans {
            if !scan.selector.starts_with("enum:")
                && !crate::capabilities::vocabulary()
                    .kinds
                    .contains_key(&scan.selector)
            {
                return Err(invalid("unknown indexed scan selector"));
            }
            expressions.extend(scan.properties.iter().map(|(_, e)| e));
        }
        for step in &p.steps {
            match step {
                Step::Action(a) => expressions.push(&a.expression),
                Step::Scan(s) => {
                    if !s.selector.starts_with("enum:")
                        && !crate::capabilities::vocabulary()
                            .kinds
                            .contains_key(&s.selector)
                    {
                        return Err(invalid("unknown indexed scan selector"));
                    }
                    expressions.extend(s.properties.iter().map(|(_, e)| e))
                }
                Step::Body(b) => super::body_runtime::validate(b, &mut || interruption.check())?,
            }
        }
        let mut pending: Vec<_> = expressions.into_iter().map(|e| (e, 0usize)).collect();
        while let Some((e, d)) = pending.pop() {
            interruption.check()?;
            work += 1;
            if d > 512 || work > 1_000_000 {
                return Err(invalid("indexed expression complexity limit exceeded"));
            }
            pending.extend(e.args.iter().map(|e| (e, d + 1)));
        }
        programs.extend(p.branches.iter().map(|p| (p, depth + 1)));
    }
    Ok(())
}
struct Run {
    execution: IndexedExecution,
    out: IndexedOutcome,
    materialized: Vec<(Vec<Value>, Vec<Value>)>,
    seen: BTreeSet<String>,
    initial_checked: bool,
    initial_steps: Option<Vec<Step>>,
}
impl Run {
    fn prime(&mut self, program: &Program) -> Result<()> {
        let mut leaf = program;
        let mut branch = None;
        let mut depth = 0;
        loop {
            if !leaf.graph.is_empty() {
                return Err(ExecutionError::Unsupported(
                    "indexed execution cannot execute a relational program".into(),
                ));
            }
            if leaf.steps.len() > 4096 || leaf.scans.len() > 4096 {
                return Err(invalid("indexed pipeline length limit exceeded"));
            }
            let Some(first) = leaf.branches.first() else {
                break;
            };
            depth += 1;
            if depth > 128 {
                return Err(invalid("indexed program nesting limit exceeded"));
            }
            branch = Some((first.name.as_str(), 0));
            leaf = first;
        }
        let steps = planning::prepare(leaf, self.execution.options.reference)?;
        self.describe_plan(&steps, branch);
        self.initial_steps = Some(steps);
        Ok(())
    }
    fn describe_plan(&mut self, steps: &[Step], branch: Option<(&str, usize)>) -> usize {
        let offset = self.out.plan.len();
        for (index, step) in steps.iter().enumerate() {
            let description = planning::describe(step, self.execution.options.reference);
            self.out.plan.push(description.clone());
            if self.execution.options.profile {
                let mut metric = description;
                let object = metric.as_object_mut().expect("operator description");
                object.insert("index".into(), json!(index));
                object.insert("input_rows".into(), json!(0));
                object.insert("output_rows".into(), json!(0));
                object.insert("elapsed_ms".into(), json!(0.0));
                if let Some((name, index)) = branch {
                    object.insert("branch".into(), json!(name));
                    object.insert("branch_index".into(), json!(index));
                }
                self.out.profile.push(metric);
            }
        }
        offset
    }
    fn check(&mut self, graph: &dyn GraphRead) -> Result<()> {
        graph.check_snapshot()?;
        self.out.states = self.out.states.saturating_add(1);
        self.execution.interruption.check()?;
        if self
            .execution
            .options
            .max_states
            .is_some_and(|max| self.out.states > max)
        {
            return Err(ExecutionError::Exhausted("max_states"));
        }
        Ok(())
    }
    fn branch(
        &mut self,
        graph: &dyn GraphRead,
        program: &Program,
        branch: Option<(&str, usize)>,
    ) -> Result<()> {
        if !program.branches.is_empty() {
            for (index, child) in program.branches.iter().enumerate() {
                if self.execution.options.max_states.is_some_and(|m| {
                    self.out
                        .states
                        .saturating_sub(u64::from(self.initial_checked))
                        >= m
                }) {
                    return Err(ExecutionError::Exhausted("max_states"));
                }
                self.branch(graph, child, Some((&child.name, index)))?;
            }
            return Ok(());
        }
        let (steps, offset) = if let Some(steps) = self.initial_steps.take() {
            (steps, 0)
        } else {
            let steps = planning::prepare(program, self.execution.options.reference)?;
            let offset = self.describe_plan(&steps, branch);
            (steps, offset)
        };
        let groups = crate::predicate_components(&program.predicates)
            .map_err(|e| invalid(e.to_string()))?
            .into_iter()
            .enumerate()
            .flat_map(|(i, names)| names.into_iter().map(move |name| (name, i)))
            .collect();
        let mut runtime = Runtime {
            graph,
            program,
            run: self,
            steps,
            profile_offset: offset,
            properties: BTreeMap::new(),
            property_order: VecDeque::new(),
            source: SourceCache::default(),
            regex_patterns: super::regex_runtime::Cache::default(),
            domain_closed: BTreeMap::new(),
            ast_programs: BTreeMap::new(),
            predicates: predicates::Tables::new(groups),
            depth: 0,
        };
        runtime.walk(
            0,
            Frame {
                bindings: Bindings::new(),
                uncertain: false,
            },
        )
    }
    fn stopped(&mut self, reason: &'static str) {
        self.out.complete = false;
        if self.out.reason.is_none() {
            self.out.reason = Some(
                if reason == "timeout_ms" {
                    "timeout"
                } else {
                    reason
                }
                .into(),
            );
        }
    }
    fn finish(&mut self, program: &Program) -> Result<()> {
        let interruption = self.execution.interruption.clone();
        interruption.check()?;
        let mut indices = Vec::with_capacity(self.materialized.len());
        for index in 0..self.materialized.len() {
            if index % 256 == 0 {
                interruption.check()?;
            }
            indices.push(index);
        }
        for position in (0..program.ordering.len()).rev() {
            finalization::stable_sort(
                &mut indices,
                &mut |a, b| {
                    let order = source::order_value(
                        &self.materialized[a].1[position],
                        &self.materialized[b].1[position],
                    );
                    if program.ordering[position].value == "desc" {
                        order.reverse()
                    } else {
                        order
                    }
                },
                &mut || interruption.check(),
            )?;
        }
        let limit = program
            .limit
            .as_ref()
            .and_then(|limit| limit.digits().parse::<usize>().ok())
            .unwrap_or(indices.len());
        if program.limit.is_some() {
            self.out.results_truncated = indices.len() > limit;
        }
        let mut source = Vec::with_capacity(self.materialized.len());
        for (index, row) in std::mem::take(&mut self.materialized)
            .into_iter()
            .enumerate()
        {
            if index % 256 == 0 {
                interruption.check()?;
            }
            source.push(Some(row));
        }
        for (index, at) in indices.into_iter().take(limit).enumerate() {
            if index % 256 == 0 {
                interruption.check()?;
            }
            let (row, key) = source[at].take().expect("unique finalization permutation");
            self.out.rows.push(row);
            self.out.order_keys.push(key);
        }
        interruption.check()
    }
}
#[derive(Clone)]
struct Frame {
    bindings: Bindings,
    uncertain: bool,
}
struct Runtime<'a, 'r> {
    graph: &'a dyn GraphRead,
    program: &'a Program,
    run: &'r mut Run,
    steps: Vec<Step>,
    profile_offset: usize,
    properties: BTreeMap<String, BTreeMap<String, ken_program::value::GraphValue>>,
    property_order: VecDeque<String>,
    source: SourceCache,
    regex_patterns: super::regex_runtime::Cache,
    domain_closed: BTreeMap<String, bool>,
    ast_programs: BTreeMap<i64, Arc<ken_program::Program>>,
    predicates: predicates::Tables,
    depth: usize,
}
impl Runtime<'_, '_> {
    fn check(&mut self) -> Result<()> {
        self.run.check(self.graph)
    }
    fn with_source<T>(
        &mut self,
        f: impl FnOnce(&mut super::source::SourceRuntime<'_>) -> Result<T>,
    ) -> Result<T> {
        let mut cache = std::mem::take(&mut self.source);
        let graph = self.graph;
        let result = f(&mut super::source::SourceRuntime {
            graph,
            cache: &mut cache,
            tick: &mut || self.check(),
        });
        self.source = cache;
        result
    }
    fn metric(&mut self, index: usize, key: &str, amount: u64) {
        if self.run.execution.options.profile {
            let metric = &mut self.run.out.profile[self.profile_offset + index];
            let n = metric[key].as_u64().unwrap_or(0);
            metric[key] = json!(n.saturating_add(amount));
        }
    }
    fn elapsed(&mut self, index: usize, start: Instant) {
        if self.run.execution.options.profile {
            let metric = &mut self.run.out.profile[self.profile_offset + index];
            metric["elapsed_ms"] = json!(
                metric["elapsed_ms"].as_f64().unwrap_or(0.0)
                    + start.elapsed().as_secs_f64() * 1000.0
            );
        }
    }
}
impl super::body_runtime::BodyServices for Runtime<'_, '_> {
    fn check(&mut self) -> Result<()> {
        Runtime::check(self)
    }
    fn evaluate(&mut self, expression: &Expr, bindings: &Bindings) -> Result<Value> {
        self.evaluate(expression, bindings)
    }
    fn regex(&mut self, text: &str, expression: &Expr) -> Result<bool> {
        self.regex(text, expression)
    }
}
