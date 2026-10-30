//! Resumable statement-CFG BODY witnesses. A cursor owns its route state and
//! borrows expression/budget services only for the duration of each next call.
mod calls;
mod collections;
mod constructors;
mod context;
mod expressions;
mod flow;
mod gaps;
mod regions;
mod statements;
mod validation;
use super::{
    ExecutionError, GraphRead, Result,
    values::{Bindings, OperationValue, SourceNode, Value},
};
use crate::{
    BodyPattern,
    ast::{Clause, Expr, Expression},
    operands::Operand as O,
};
use context::{Context, Op, attr, block, flag, text, unknown};
use flow::{Flow, Snapshot};
use gaps::restrictions;
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    sync::Arc,
};
pub use validation::validate;
fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}
#[derive(Clone, Debug, serde::Serialize)]
pub struct BodyMatch {
    pub bindings: Bindings,
    pub unknown: bool,
}
pub trait BodyServices {
    fn check(&mut self) -> Result<()>;
    fn evaluate(&mut self, expression: &Expr, bindings: &Bindings) -> Result<Value>;
    fn regex(&mut self, text: &str, pattern: &Expr) -> Result<bool>;
    /// Call-name inventories use Python stdlib re and honor only ignore-case.
    /// Other BODY regular expressions keep the caller's Regex-module semantics.
    fn name_regex(&mut self, text: &str, expression: &Expr) -> Result<bool> {
        self.check()?;
        let (pattern, flags) = expression
            .value
            .strip_prefix('/')
            .and_then(|raw| raw.rsplit_once('/'))
            .ok_or_else(|| invalid("invalid name regex literal"))?;
        let pattern = super::regex_runtime::Pattern::compile(
            pattern,
            if flags.contains('i') { "i" } else { "" },
            super::regex_runtime::Dialect::Stdlib,
            &mut || self.check(),
        )?;
        pattern.is_match_with_timeout(&text.into(), None, &mut || self.check())
    }
}
#[derive(Clone)]
struct Witness {
    bindings: Bindings,
    unknown: bool,
    operation: String,
}
#[derive(Clone, Default)]
struct State {
    group: String,
    index: usize,
    bindings: Bindings,
    unknown: bool,
    used: BTreeSet<String>,
    last: Option<String>,
    adjacent: bool,
    protected: Vec<String>,
    forbidden: Vec<String>,
    cursor: Option<String>,
    values: Option<Snapshot>,
    flow: Flow,
}
#[derive(PartialEq, Eq, PartialOrd, Ord)]
struct StateKey {
    group: String,
    index: usize,
    bindings: Vec<(String, String)>,
    unknown: bool,
    last: Option<String>,
    adjacent: bool,
    used: BTreeSet<String>,
    protected: Vec<String>,
    forbidden: Vec<String>,
    cursor: Option<String>,
    values: Option<Snapshot>,
    flow: Flow,
}
impl State {
    fn key(&self) -> Result<StateKey> {
        Ok(StateKey {
            group: self.group.clone(),
            index: self.index,
            bindings: self
                .bindings
                .iter()
                .map(|(k, v)| Ok((k.clone(), v.identity()?)))
                .collect::<Result<_>>()?,
            unknown: self.unknown,
            last: self.last.clone(),
            adjacent: self.adjacent,
            used: self.used.clone(),
            protected: self.protected.clone(),
            forbidden: self.forbidden.clone(),
            cursor: self.cursor.clone(),
            values: self.values.clone(),
            flow: self.flow.clone(),
        })
    }
}
struct Frame<'a> {
    state: State,
    candidates: Vec<Op>,
    at: usize,
    nested: Option<regions::Nesting<'a>>,
    extra: VecDeque<Witness>,
    selector: Option<(Op, usize)>,
    snapshot: Option<Snapshot>,
    gap: bool,
    closing_yield: bool,
}
impl<'a> Frame<'a> {
    fn next(
        &mut self,
        context: &mut Context<'a>,
        pattern: &BodyPattern,
        s: &mut dyn BodyServices,
    ) -> Result<Option<Witness>> {
        let item = &pattern.clauses[self.state.index];
        loop {
            s.check()?;
            if let Some(nested) = &mut self.nested {
                if let Some(w) = nested.next(s)? {
                    return Ok(Some(w));
                }
                self.nested = None;
            }
            if let Some(w) = self.extra.pop_front() {
                return Ok(Some(w));
            }
            if let Some((operation, mut at)) = self.selector.take()
                && let Some(w) =
                    context.selector_from(item, &operation, &self.state.bindings, &mut at, s)?
            {
                self.selector = Some((operation, at));
                return Ok(Some(w));
            }
            let Some(operation) = self.candidates.get(self.at).cloned() else {
                return Ok(None);
            };
            self.at += 1;
            if let Some(cursor) = &self.state.cursor {
                let mut ancestor = context.operations.get(cursor).cloned();
                let mut ancestors = BTreeSet::new();
                while let Some(child) = ancestor {
                    let Some(parent) = &child.parent else { break };
                    if !ancestors.insert(parent.clone()) {
                        break;
                    }
                    ancestor = context.operations.get(parent).cloned();
                }
                let implicit = context
                    .implied
                    .as_ref()
                    .is_some_and(|o| o.id == operation.id)
                    && context
                        .operations
                        .get(cursor)
                        .is_some_and(|c| c.start >= operation.start && c.end <= operation.end);
                if !ancestors.contains(&operation.id) && !implicit {
                    let alongside = flag(item, "alongside")
                        && operation
                            .parent
                            .as_ref()
                            .is_some_and(|p| context.operations.contains_key(p))
                        && context
                            .operations
                            .get(cursor)
                            .is_some_and(|c| c.parent == operation.parent);
                    if !alongside {
                        let semantic = item.kind == "call"
                            && item
                                .expressions
                                .first()
                                .is_some_and(|e| e.kind() == "index")
                            && context.foreign.contains(&operation.id);
                        let mut parent = operation
                            .parent
                            .as_ref()
                            .and_then(|p| context.operations.get(p))
                            .cloned();
                        let mut seen = BTreeSet::from([operation.id.clone()]);
                        let mut inside = false;
                        if semantic {
                            while let Some(p) = parent {
                                if !seen.insert(p.id.clone()) {
                                    break;
                                }
                                if &p.id == cursor {
                                    inside = true;
                                    break;
                                }
                                parent = p
                                    .parent
                                    .as_ref()
                                    .and_then(|p| context.operations.get(p))
                                    .cloned();
                            }
                        }
                        if !inside {
                            continue;
                        }
                    }
                }
            }
            if item.kind == "selector" && operation.id == self.state.group {
                self.selector = Some((operation, 0));
                continue;
            }
            if matches!(item.kind.as_str(), "if" | "iterate") {
                self.nested =
                    context.region_matches(item, &operation, &self.state.bindings, pattern, s)?;
            } else {
                self.extra = context
                    .simple_match(
                        item,
                        &operation,
                        &self.state.group,
                        &self.state.bindings,
                        self.snapshot.as_ref(),
                        s,
                    )?
                    .into();
            }
        }
    }
}
/// Iterator state is local to one pattern invocation. No graph, query services,
/// mutable bindings or snapshots are retained globally or shared between runs.
pub struct BodyCursor<'a> {
    graph: &'a dyn GraphRead,
    pattern: Arc<BodyPattern>,
    input: Option<Bindings>,
    region: Option<Op>,
    linear_arm: bool,
    iteration: BTreeMap<String, (Op, String)>,
    keyed: BTreeSet<String>,
    context: Option<Context<'a>>,
    pending: Vec<State>,
    active: Option<Frame<'a>>,
    visited: BTreeSet<StateKey>,
    initial: VecDeque<BodyMatch>,
    initialized: bool,
    finished: bool,
    prefix_unknown: bool,
}
impl<'a> BodyCursor<'a> {
    pub fn new(graph: &'a dyn GraphRead, pattern: Arc<BodyPattern>, bindings: Bindings) -> Self {
        Self::nested(
            graph,
            pattern,
            bindings,
            None,
            false,
            BTreeMap::new(),
            BTreeSet::new(),
        )
    }
    fn nested(
        graph: &'a dyn GraphRead,
        pattern: Arc<BodyPattern>,
        bindings: Bindings,
        region: Option<Op>,
        linear_arm: bool,
        iteration: BTreeMap<String, (Op, String)>,
        keyed: BTreeSet<String>,
    ) -> Self {
        Self {
            graph,
            pattern,
            input: Some(bindings),
            region,
            linear_arm,
            iteration,
            keyed,
            context: None,
            pending: vec![],
            active: None,
            visited: BTreeSet::new(),
            initial: VecDeque::new(),
            initialized: false,
            finished: false,
            prefix_unknown: false,
        }
    }
    fn initialize(&mut self, s: &mut dyn BodyServices) -> Result<()> {
        validate(&self.pattern, &mut || s.check())?;
        self.initialized = true;
        let mut input = self.input.take().unwrap_or_default();
        if self
            .pattern
            .clauses
            .first()
            .is_some_and(|c| c.kind == "initializer")
        {
            let initial = if let Some(owner) = context::node(&input, &self.pattern.owner) {
                let mut bare = Context::bare(
                    self.graph,
                    owner,
                    None,
                    self.iteration.clone(),
                    self.keyed.clone(),
                );
                bare.initializer_prefix(block(&self.pattern.clauses[0]), &input, s)?
            } else {
                unknown("initializer_owner_unknown")
            };
            if initial.is_false() {
                self.finished = true;
                return Ok(());
            }
            self.prefix_unknown = initial.is_unknown();
            let mut remainder = (*self.pattern).clone();
            remainder.clauses.remove(0);
            self.pattern = Arc::new(remainder);
        }
        if self.pattern.clauses.is_empty() {
            self.initial.push_back(BodyMatch {
                bindings: input,
                unknown: self.prefix_unknown,
            });
            self.finished = true;
            return Ok(());
        }
        let Some(owner) = context::node(&input, &self.pattern.owner) else {
            for role in &self.pattern.outputs {
                input.insert(role.clone(), unknown("body_owner_unknown"));
            }
            self.initial.push_back(BodyMatch {
                bindings: input,
                unknown: true,
            });
            self.finished = true;
            return Ok(());
        };
        if self.pattern.clauses.len() == 1
            && self.pattern.clauses[0].kind == "return"
            && self.pattern.clauses[0].alias.is_empty()
            && let Some(expected) = self.pattern.clauses[0]
                .expressions
                .first()
                .map(O::from)
                .filter(|e| e.kind() == "role")
            && let Some(value) =
                context::node(&input, expected.value()).filter(|n| n.kind == "CALLABLE")
        {
            let mut bare = Context::bare(
                self.graph,
                owner.clone(),
                None,
                self.iteration.clone(),
                self.keyed.clone(),
            );
            if bare.has("BODY_VALUE", &owner.local_id, &value.local_id, s)? {
                self.initial.push_back(BodyMatch {
                    bindings: input,
                    unknown: self.prefix_unknown,
                });
                self.finished = true;
                return Ok(());
            }
        }
        let context = Context::new(
            self.graph,
            owner,
            self.region.clone(),
            &self.pattern,
            self.iteration.clone(),
            self.keyed.clone(),
            s,
        )?;
        let Some(context) = context else {
            for role in &self.pattern.outputs {
                input.insert(role.clone(), unknown("control_flow_incomplete"));
            }
            self.initial.push_back(BodyMatch {
                bindings: input,
                unknown: true,
            });
            self.finished = true;
            return Ok(());
        };
        if context.entries.is_empty() {
            if context.region_entry_incomplete {
                for role in &self.pattern.outputs {
                    input.insert(role.clone(), unknown("iteration_entry_incomplete"));
                }
                self.initial.push_back(BodyMatch {
                    bindings: input,
                    unknown: true,
                });
            }
            self.finished = true;
            return Ok(());
        }
        self.pending.push(State {
            group: context.entries[0].clone(),
            bindings: input,
            values: context.initial.clone(),
            ..Default::default()
        });
        self.context = Some(context);
        Ok(())
    }
    pub fn next(&mut self, services: &mut dyn BodyServices) -> Result<Option<BodyMatch>> {
        services.check()?;
        if !self.initialized {
            self.initialize(services)?;
        }
        if let Some(result) = self.initial.pop_front() {
            return Ok(Some(result));
        }
        if self.finished {
            return Ok(None);
        }
        let Some(mut context) = self.context.take() else {
            self.finished = true;
            return Ok(None);
        };
        let result = self.advance(&mut context, services);
        self.context = Some(context);
        if matches!(result, Ok(None)) {
            self.finished = true;
        }
        result
    }
    fn advance(
        &mut self,
        c: &mut Context<'a>,
        s: &mut dyn BodyServices,
    ) -> Result<Option<BodyMatch>> {
        loop {
            s.check()?;
            if let Some(mut frame) = self.active.take() {
                let pattern = self.pattern.clone();
                let item = &pattern.clauses[frame.state.index];
                if let Some(mut witness) = frame.next(c, &pattern, s)? {
                    if !item.alias.is_empty() {
                        let operation =
                            c.operations.get(&witness.operation).cloned().or_else(|| {
                                c.implied.clone().filter(|o| o.id == witness.operation)
                            });
                        if let Some(operation) = operation {
                            let value = if pattern.call_aliases.contains(&item.alias) {
                                c.call(&operation)
                                    .map(|call| c.value_node(&call.id, "CALL"))
                                    .unwrap_or_else(|| unknown("call_evidence_missing"))
                            } else {
                                c.reference(&operation)
                            };
                            witness.bindings.insert(item.alias.clone(), value);
                        }
                    }
                    if frame.gap {
                        for role in &pattern.outputs {
                            witness
                                .bindings
                                .entry(role.clone())
                                .or_insert_with(|| unknown("control_flow_gap"));
                        }
                        self.active = Some(frame);
                        return Ok(Some(BodyMatch {
                            bindings: witness.bindings,
                            unknown: true,
                        }));
                    }
                    if frame.state.used.contains(&witness.operation) {
                        self.active = Some(frame);
                        continue;
                    }
                    let constraint = c.interval_ok(&frame.state, &pattern, s)?;
                    if constraint.is_false() {
                        self.active = Some(frame);
                        continue;
                    }
                    let uncertain =
                        frame.state.unknown || witness.unknown || constraint.is_unknown();
                    if frame.state.index + 1 == pattern.clauses.len() {
                        let accepted =
                            c.completed_linear_arm(&frame.state.group, item, self.linear_arm, s)?;
                        self.active = Some(frame);
                        if accepted {
                            return Ok(Some(BodyMatch {
                                bindings: witness.bindings,
                                unknown: uncertain || self.prefix_unknown,
                            }));
                        }
                        continue;
                    }
                    let mut used = frame.state.used.clone();
                    used.insert(witness.operation.clone());
                    let mut after = if frame.closing_yield {
                        vec![]
                    } else {
                        c.path_successors(
                            &frame.state.group,
                            frame.state.values.as_ref(),
                            &frame.state.flow,
                            s,
                        )?
                    };
                    if matches!(item.kind.as_str(), "if" | "iterate") {
                        let region = c
                            .operations
                            .get(&witness.operation)
                            .cloned()
                            .ok_or_else(|| invalid("matched region operation missing"))?;
                        let mut frontier = c.successors(&witness.operation, s)?;
                        let mut seen = BTreeSet::new();
                        let mut exits = BTreeSet::new();
                        while let Some(point) = frontier.pop() {
                            s.check()?;
                            if !seen.insert(point.clone()) {
                                continue;
                            }
                            if c.operations
                                .get(&point)
                                .is_some_and(|o| region.start <= o.start && o.end <= region.end)
                            {
                                frontier.extend(c.successors(&point, s)?);
                            } else {
                                exits.insert(point);
                            }
                        }
                        after = exits.into_iter().collect();
                    } else {
                        self.pending.push(State {
                            group: frame.state.group.clone(),
                            index: frame.state.index + 1,
                            bindings: witness.bindings.clone(),
                            unknown: uncertain,
                            used: used.clone(),
                            last: Some(frame.state.group.clone()),
                            cursor: Some(witness.operation.clone()),
                            values: frame.state.values.clone(),
                            flow: frame.state.flow.clone(),
                            ..Default::default()
                        });
                    }
                    for target in after {
                        let advanced = if matches!(item.kind.as_str(), "if" | "iterate") {
                            vec![(None, frame.state.flow.clone())]
                        } else {
                            c.advanced(
                                &frame.state.group,
                                frame.state.values.as_ref(),
                                &frame.state.flow,
                                &target,
                                s,
                            )?
                        };
                        for (values, flow) in advanced {
                            self.pending.push(State {
                                group: target.clone(),
                                index: frame.state.index + 1,
                                bindings: witness.bindings.clone(),
                                unknown: uncertain,
                                used: used.clone(),
                                last: Some(frame.state.group.clone()),
                                values,
                                flow,
                                ..Default::default()
                            });
                        }
                    }
                    self.active = Some(frame);
                    continue;
                }
                if frame.gap {
                    let normal = if pattern
                        .clauses
                        .iter()
                        .all(|cl| matches!(cl.kind.as_str(), "call" | "let" | "return"))
                    {
                        c.rows("CFG_NEXT", Some(&frame.state.group), None, s)?
                            .into_iter()
                            .filter(|f| text(&f.attrs, "kind").ok().as_deref() == Some("normal"))
                            .map(|f| f.object.clone())
                            .collect::<BTreeSet<_>>()
                    } else {
                        BTreeSet::new()
                    };
                    for target in c.path_successors(
                        &frame.state.group,
                        frame.state.values.as_ref(),
                        &frame.state.flow,
                        s,
                    )? {
                        for (values, flow) in c.advanced(
                            &frame.state.group,
                            frame.state.values.as_ref(),
                            &frame.state.flow,
                            &target,
                            s,
                        )? {
                            let mut next = frame.state.clone();
                            next.group = target.clone();
                            next.cursor = None;
                            next.values = values;
                            next.flow = flow;
                            next.unknown = if normal.contains(&target) {
                                frame.state.unknown
                            } else {
                                true
                            };
                            self.pending.push(next);
                        }
                    }
                }
                continue;
            }
            let Some(mut state) = self.pending.pop() else {
                return Ok(None);
            };
            let event = c.events.get(&state.group).cloned().unwrap_or_default();
            if state.flow.exception == "GeneratorExit"
                && (text(&event, "close")? == "unknown"
                    || attr(&event, "close_uncertain")?.truthy())
            {
                state.unknown = true;
            }
            if state.index == self.pattern.clauses.len() {
                return Ok(Some(BodyMatch {
                    bindings: state.bindings,
                    unknown: state.unknown || self.prefix_unknown,
                }));
            }
            if !self.visited.insert(state.key()?) {
                continue;
            }
            let pattern = self.pattern.clone();
            let item = &pattern.clauses[state.index];
            match item.kind.as_str() {
                "resume" => {
                    let Some(cursor) = state
                        .cursor
                        .as_ref()
                        .and_then(|id| c.operations.get(id))
                        .cloned()
                        .filter(|o| o.kind == "YIELD")
                    else {
                        continue;
                    };
                    if attr(&cursor.attrs, "delegated")?.truthy() {
                        let mut bindings = state.bindings;
                        for role in &pattern.outputs {
                            bindings.insert(role.clone(), unknown("delegated_resumption_unknown"));
                        }
                        return Ok(Some(BodyMatch {
                            bindings,
                            unknown: true,
                        }));
                    }
                    if item.name == "next" {
                        state.index += 1;
                        self.pending.push(state);
                    } else {
                        let wanted = format!("inject-{}", item.name);
                        let targets = c
                            .rows("CFG_NEXT", Some(&state.group), None, s)?
                            .into_iter()
                            .filter(|f| text(&f.attrs, "kind").ok().as_deref() == Some(&wanted))
                            .map(|f| f.object.clone())
                            .collect::<BTreeSet<_>>();
                        for target in targets {
                            let mut next = state.clone();
                            next.group = target;
                            next.index += 1;
                            next.cursor = None;
                            next.flow.closing = item.name == "close";
                            next.flow.exception = if next.flow.closing {
                                "GeneratorExit".into()
                            } else {
                                String::new()
                            };
                            self.pending.push(next);
                        }
                    }
                    continue;
                }
                "where" => {
                    let expression = match item.expressions.first() {
                        Some(Expression::Query(e)) => e,
                        _ => return Err(invalid("BODY where requires a query expression")),
                    };
                    let result = s.evaluate(expression, &state.bindings)?;
                    if !result.is_false() {
                        state.index += 1;
                        state.unknown |= result.is_unknown();
                        self.pending.push(state);
                    }
                    continue;
                }
                "gap" => {
                    if flag(item, "exit") {
                        let truth = c.terminal_ok(&state, item, &pattern, s)?;
                        if !truth.is_false() {
                            return Ok(Some(BodyMatch {
                                bindings: state.bindings,
                                unknown: state.unknown || truth.is_unknown() || self.prefix_unknown,
                            }));
                        }
                    } else {
                        let (protected, forbidden) = restrictions(item, false)?;
                        state.index += 1;
                        state.protected = protected;
                        state.forbidden = forbidden;
                        self.pending.push(state);
                    }
                    continue;
                }
                "adjacent" => {
                    state.index += 1;
                    state.adjacent = true;
                    self.pending.push(state);
                    continue;
                }
                _ => (),
            }
            let parts = c.parts(&state.group, s)?;
            let closing_yield = state.flow.closing && parts.iter().any(|o| o.kind == "YIELD");
            if closing_yield && item.kind == "yield" {
                continue;
            }
            let snapshot = if text(&event, "action")? == "return-complete" {
                state
                    .flow
                    .returned
                    .as_ref()
                    .and_then(|(_, snapshot)| snapshot.clone())
                    .or_else(|| state.values.clone())
            } else {
                state.values.clone()
            };
            let gap = c.gaps.contains(&state.group);
            let decisions = pattern.linear
                && parts
                    .iter()
                    .any(|o| matches!(o.kind.as_str(), "BRANCH" | "LOOP" | "TRY" | "SWITCH"));
            if !(gap
                || closing_yield
                || decisions
                || state.adjacent
                || pattern.adjacent && state.last.is_some())
            {
                for target in
                    c.path_successors(&state.group, state.values.as_ref(), &state.flow, s)?
                {
                    for (values, flow) in
                        c.advanced(&state.group, state.values.as_ref(), &state.flow, &target, s)?
                    {
                        let mut next = state.clone();
                        next.group = target.clone();
                        next.cursor = None;
                        next.values = values;
                        next.flow = flow;
                        self.pending.push(next);
                    }
                }
            }
            if !gap && decisions && !matches!(item.kind.as_str(), "if" | "iterate") {
                continue;
            }
            let kinds = operation_kinds(item);
            let mut candidates = parts
                .iter()
                .filter(|o| kinds.is_none_or(|kinds| kinds.contains(&o.kind.as_str())))
                .cloned()
                .collect::<Vec<_>>();
            if item.kind == "return"
                && c.entries.contains(&state.group)
                && let Some(implied) = &c.implied
            {
                candidates.push(implied.clone());
            }
            if item.kind == "call"
                && item
                    .expressions
                    .first()
                    .is_some_and(|e| e.kind() == "index")
            {
                candidates.extend(parts.into_iter().filter(|o| c.foreign.contains(&o.id)));
            }
            self.active = Some(Frame {
                state,
                candidates,
                at: 0,
                nested: None,
                extra: VecDeque::new(),
                selector: None,
                snapshot,
                gap,
                closing_yield,
            });
        }
    }
}
fn operation_kinds(item: &Clause) -> Option<&'static [&'static str]> {
    if matches!(item.kind.as_str(), "let" | "call")
        && item
            .expressions
            .first()
            .is_some_and(|e| e.kind() == "index")
    {
        return Some(if item.kind == "let" {
            &["ASSIGN", "UPDATE"]
        } else {
            &["CALL"]
        });
    }
    match item.kind.as_str() {
        "call" | "let" => Some(&["CALL"]),
        "assign" => Some(&["ASSIGN", "UPDATE"]),
        "return" => Some(&["RETURN"]),
        "yield" => Some(&["YIELD"]),
        "if" => Some(&["BRANCH"]),
        "iterate" => Some(&["LOOP"]),
        "insert" | "clear" => Some(&["CALL", "ASSIGN", "UPDATE"]),
        _ => None,
    }
}
