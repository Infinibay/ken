//! Statement routes with explicit opacity, cleanup continuations and coverage.
use super::{append, completions::CompletionRoutes, exceptions, index::Context};
use crate::{Fact, ProgramError, StructuralIr, attributes};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
const BLOCKS: &[&str] = &[
    "do",
    "block",
    "statement_block",
    "compound_statement",
    "else_clause",
    "statement_list",
    "body_statement",
    "finally_clause",
];
const LOOPS: &[&str] = &[
    "for",
    "while_statement",
    "while_expression",
    "for_statement",
    "for_in_statement",
    "enhanced_for_statement",
    "for_each_statement",
    "foreach_statement",
    "for_expression",
    "loop_expression",
    "do_statement",
    "for_range_loop",
];
const UNSUPPORTED: &[&str] = &[
    "try_statement",
    "try_with_resources_statement",
    "with_statement",
    "using_statement",
    "switch_statement",
    "switch_expression",
    "match_expression",
    "match_statement",
    "rescue",
    "ensure",
    "rescue_modifier",
    "goto_statement",
    "labeled_statement",
    "lock_statement",
    "synchronized_statement",
];
type Result<T> = std::result::Result<T, ProgramError>;
struct Builder<'a, 'b> {
    ctx: &'a Context<'b>,
    owner: String,
    language: Value,
    exit: String,
    routes: CompletionRoutes<'a, 'b>,
    syntax: Vec<(String, String, String)>,
    missing: BTreeSet<String>,
    gaps: BTreeSet<String>,
    handlers: Vec<Vec<String>>,
    modeled_yields: BTreeSet<String>,
    bound: &'a BTreeSet<String>,
    shadowed: BTreeSet<String>,
    bindings: &'a BTreeMap<String, String>,
}
impl<'a, 'b> Builder<'a, 'b> {
    fn new(
        ctx: &'a Context<'b>,
        owner: &str,
        bound: &'a BTreeSet<String>,
        shadowed: BTreeSet<String>,
        bindings: &'a BTreeMap<String, String>,
    ) -> Result<Self> {
        let entity = ctx.entity(owner)?;
        let language = attributes::get(&entity.attrs, "language")?.unwrap_or(Value::Null);
        Ok(Self {
            ctx,
            owner: owner.into(),
            language,
            exit: format!("{owner}::cfg-exit"),
            routes: CompletionRoutes::new(ctx, owner),
            syntax: Vec::new(),
            missing: BTreeSet::new(),
            gaps: BTreeSet::new(),
            handlers: Vec::new(),
            modeled_yields: BTreeSet::new(),
            bound,
            shadowed,
            bindings,
        })
    }
    fn python(&self) -> bool {
        self.language == "python"
    }
    fn targets(&self) -> Vec<String> {
        self.handlers
            .last()
            .filter(|h| !h.is_empty())
            .cloned()
            .unwrap_or_else(|| vec![self.exit.clone()])
    }
    fn may_raise(&self, i: usize, depth: usize) -> Result<bool> {
        if depth > 64 {
            return Ok(true);
        }
        let op = self.ctx.op(i);
        let kids = self.ctx.kids(i);
        if op.native_kind == "string"
            && kids
                .iter()
                .any(|&c| self.ctx.op(c).native_kind == "interpolation")
        {
            return Ok(true);
        }
        if [
            "none",
            "true",
            "false",
            "integer",
            "float",
            "string",
            "pass_statement",
            "break_statement",
            "continue_statement",
        ]
        .contains(&op.native_kind.as_str())
        {
            return Ok(false);
        }
        if [
            "expression_statement",
            "parenthesized_expression",
            "return_statement",
        ]
        .contains(&op.native_kind.as_str())
            || (op.kind == "YIELD" && !attributes::truth(&op.attrs, "delegated")?)
        {
            for &c in kids {
                if self.may_raise(c, depth + 1)? {
                    return Ok(true);
                }
            }
            return Ok(false);
        }
        if op.native_kind == "assignment" {
            let fields = self.fields(kids);
            let Some(&left) = fields.get("left") else {
                return Ok(true);
            };
            let Some(&right) = fields.get("right") else {
                return Ok(true);
            };
            return Ok(self.ctx.op(left).native_kind != "identifier"
                || self.may_raise(right, depth + 1)?);
        }
        if ["BRANCH", "LOOP"].contains(&op.kind.as_str()) {
            let conditions = kids
                .iter()
                .filter(|&&c| self.ctx.op(c).role == "condition")
                .copied()
                .collect::<Vec<_>>();
            if conditions.is_empty() {
                return Ok(true);
            }
            for c in conditions {
                if self.may_raise(c, depth + 1)? {
                    return Ok(true);
                }
            }
            return Ok(false);
        }
        Ok(true)
    }
    fn fields(&self, kids: &[usize]) -> BTreeMap<String, usize> {
        kids.iter()
            .filter(|&&i| !self.ctx.op(i).role.is_empty())
            .map(|&i| (self.ctx.op(i).role.clone(), i))
            .collect()
    }
    fn build(
        &mut self,
        i: usize,
        after: &str,
        break_to: Option<&str>,
        continue_to: Option<&str>,
        depth: usize,
        false_after: Option<&str>,
    ) -> Result<String> {
        let entry = self.statement(i, after, break_to, continue_to, depth, false_after)?;
        let op = self.ctx.op(i);
        if entry == op.id
            && self.python()
            && ["expression_statement", "return_statement"].contains(&op.native_kind.as_str())
        {
            let mut todo = self.ctx.kids(i).to_vec();
            let mut suspensions = Vec::new();
            let mut visited = BTreeSet::new();
            while let Some(c) = todo.pop() {
                if !visited.insert(c) {
                    continue;
                }
                if self.ctx.op(c).kind == "YIELD" {
                    suspensions.push(c);
                } else {
                    todo.extend(self.ctx.kids(c));
                }
            }
            if suspensions.len() == 1 {
                let suspension = self.ctx.op(suspensions[0]);
                self.modeled_yields.insert(suspension.id.clone());
                self.missing.insert("generator-resumption".into());
                self.routes.dispatch(&op.id,json!({"operation":op.id,"action":"suspend","suspension":suspension.id,"delegated":attributes::truth(&suspension.attrs,"delegated")?}));
                for target in self.targets() {
                    let thrown = self.routes.depart(i, &target);
                    self.routes.edge(&op.id, &thrown, "inject-throw");
                    let closed = self.routes.depart(i, &target);
                    self.routes.edge(&op.id, &closed, "inject-close");
                }
            }
        }
        if self.handlers.last().is_some_and(|h| !h.is_empty())
            && entry == op.id
            && self.python()
            && op.kind != "TRY"
            && self.may_raise(i, 0)?
        {
            let dispatch = format!("{}::exception-dispatch", op.id);
            if op.kind == "LOOP" {
                for (_, to, _) in &mut self.routes.edges {
                    if *to == op.id {
                        *to = dispatch.clone();
                    }
                }
            }
            self.routes.dispatch(&dispatch, json!({"operation":op.id}));
            self.routes.edge(&dispatch, &entry, "normal");
            for target in self.handlers.last().unwrap().clone() {
                let target = self.routes.depart(i, &target);
                self.routes.edge(&dispatch, &target, "exception");
            }
            return Ok(dispatch);
        }
        Ok(entry)
    }
    fn statement(
        &mut self,
        i: usize,
        after: &str,
        break_to: Option<&str>,
        continue_to: Option<&str>,
        depth: usize,
        false_after: Option<&str>,
    ) -> Result<String> {
        if depth > 64 {
            self.missing.insert("nesting-limit".into());
            return Ok(after.into());
        }
        let op = self.ctx.op(i);
        let kids = self.ctx.kids(i).to_vec();
        let mut fields = self.fields(&kids);
        if op.native_kind == "expression_statement"
            && kids.len() == 1
            && (LOOPS.contains(&self.ctx.op(kids[0]).native_kind.as_str())
                || [
                    "if_expression",
                    "return_expression",
                    "break_expression",
                    "continue_expression",
                ]
                .contains(&self.ctx.op(kids[0]).native_kind.as_str()))
        {
            return self.build(kids[0], after, break_to, continue_to, depth + 1, None);
        }
        if BLOCKS.contains(&op.native_kind.as_str()) {
            let mut entry = after.to_owned();
            for &child in kids.iter().rev() {
                if !self.ctx.op(child).native_kind.contains("comment") {
                    entry = self.build(child, &entry, break_to, continue_to, depth + 1, None)?;
                }
            }
            return Ok(entry);
        }
        if [
            "if_modifier",
            "if_statement",
            "if_expression",
            "elif_clause",
        ]
        .contains(&op.native_kind.as_str())
        {
            if let Some(&condition) = fields
                .get("condition")
                .filter(|&&c| self.ctx.op(c).native_kind != "empty_statement")
            {
                self.syntax.push((
                    op.id.clone(),
                    "CONTROL_CONDITION".into(),
                    self.ctx.op(condition).id.clone(),
                ));
            }
            let mut alternate = false_after.unwrap_or(after).to_owned();
            for &arm in kids
                .iter()
                .rev()
                .filter(|&&c| self.ctx.op(c).role == "alternative")
            {
                alternate = self.build(
                    arm,
                    after,
                    break_to,
                    continue_to,
                    depth + 1,
                    if self.ctx.op(arm).native_kind == "elif_clause" {
                        Some(&alternate)
                    } else {
                        None
                    },
                )?;
            }
            let Some(&consequence) = fields.get("consequence") else {
                self.missing.insert("branch-grammar".into());
                return Ok(after.into());
            };
            let yes = self.build(consequence, after, break_to, continue_to, depth + 1, None)?;
            self.routes.edge(&op.id, &yes, "true");
            self.routes.edge(&op.id, &alternate, "false");
            return Ok(op.id.clone());
        }
        if LOOPS.contains(&op.native_kind.as_str()) {
            let Some(&body) = fields.get("body") else {
                self.missing.insert("loop-grammar".into());
                return Ok(after.into());
            };
            let clause = kids
                .iter()
                .find(|&&c| {
                    ["for_clause", "range_clause"].contains(&self.ctx.op(c).native_kind.as_str())
                })
                .copied();
            if let Some(clause) = clause {
                fields.extend(self.fields(self.ctx.kids(clause)));
            }
            let iterable = ["right", "value", "iterable"]
                .iter()
                .find_map(|k| fields.get(*k))
                .copied();
            let foreach = [
                "for",
                "for_in_statement",
                "enhanced_for_statement",
                "for_each_statement",
                "foreach_statement",
                "for_expression",
                "for_range_loop",
            ]
            .contains(&op.native_kind.as_str())
                || (op.native_kind == "for_statement" && self.python())
                || clause.is_some_and(|c| self.ctx.op(c).native_kind == "range_clause");
            let condition = fields
                .get("condition")
                .filter(|&&c| self.ctx.op(c).native_kind != "empty_statement")
                .copied();
            if let Some(condition) = condition {
                self.syntax.push((
                    op.id.clone(),
                    "CONTROL_CONDITION".into(),
                    self.ctx.op(condition).id.clone(),
                ));
            }
            if let Some(iterable) = iterable.filter(|_| foreach) {
                self.syntax.push((
                    op.id.clone(),
                    "CONTROL_ITERABLE".into(),
                    self.ctx.op(iterable).id.clone(),
                ));
            }
            let mut normal_exit = after.to_owned();
            for &arm in kids
                .iter()
                .rev()
                .filter(|&&c| self.ctx.op(c).role == "alternative")
            {
                normal_exit =
                    self.build(arm, &normal_exit, break_to, continue_to, depth + 1, None)?;
            }
            let update = fields
                .get("update")
                .or_else(|| fields.get("increment"))
                .copied();
            let back = if let Some(update) = update {
                self.build(update, &op.id, Some(after), Some(&op.id), depth + 1, None)?
            } else {
                op.id.clone()
            };
            let entry = self.build(body, &back, Some(after), Some(&back), depth + 1, None)?;
            self.syntax.push((
                op.id.clone(),
                "CONTROL_BODY".into(),
                self.ctx.op(body).id.clone(),
            ));
            self.routes
                .edge(&op.id, &entry, if foreach { "iterate" } else { "true" });
            if foreach || condition.is_some() {
                self.routes.edge(
                    &op.id,
                    &normal_exit,
                    if foreach { "exhausted" } else { "false" },
                );
            } else if !["for_statement", "loop_expression"].contains(&op.native_kind.as_str()) {
                self.missing.insert("loop-condition".into());
            }
            let start = if op.native_kind == "do_statement" {
                entry
            } else {
                op.id.clone()
            };
            return if let Some(&initializer) = fields.get("initializer") {
                self.build(initializer, &start, break_to, continue_to, depth + 1, None)
            } else {
                Ok(start)
            };
        }
        if [
            "break",
            "break_statement",
            "continue_statement",
            "break_expression",
            "continue_expression",
        ]
        .contains(&op.native_kind.as_str())
        {
            let is_break = op.native_kind.starts_with("break");
            let target = if is_break { break_to } else { continue_to };
            if let Some(target) = target
                && !kids
                    .iter()
                    .any(|&c| !self.ctx.op(c).native_kind.contains("comment"))
            {
                let target = self.routes.depart(i, target);
                self.routes
                    .edge(&op.id, &target, if is_break { "break" } else { "continue" });
            } else {
                self.missing.insert("label-or-control-target".into());
            }
            return Ok(op.id.clone());
        }
        if self.python()
            && op.native_kind == "with_statement"
            && let Some(&body) = fields.get("body")
        {
            let entry = self.build(body, after, break_to, continue_to, depth + 1, None)?;
            self.routes.edge(&op.id, &entry, "enter");
            return Ok(op.id.clone());
        }
        if self.python() && op.native_kind == "try_statement" {
            return self.try_statement(i, after, break_to, continue_to, depth, &kids);
        }
        if ["raise_statement", "throw_statement"].contains(&op.native_kind.as_str()) {
            let targets = if self.python() {
                self.targets()
            } else {
                vec![self.exit.clone()]
            };
            for target in targets {
                let target = self.routes.depart(i, &target);
                self.routes.edge(&op.id, &target, "raise");
            }
            return Ok(op.id.clone());
        }
        if op.kind == "RETURN"
            || (op.kind == "YIELD" && attributes::tokens(&op.attrs)?.iter().any(|t| t == "break"))
        {
            let target = if self.python() && !self.routes.finalizers.is_empty() {
                self.routes.returned(i)
            } else {
                self.exit.clone()
            };
            self.routes.edge(&op.id, &target, "return");
            return Ok(op.id.clone());
        }
        if UNSUPPORTED.contains(&op.native_kind.as_str())
            || ["TRY", "THROW", "YIELD", "AWAIT", "RESOURCE_SCOPE", "MATCH"]
                .contains(&op.kind.as_str())
        {
            self.missing.insert(op.native_kind.clone());
        }
        self.routes.edge(&op.id, after, "next");
        Ok(op.id.clone())
    }
    fn cleanup(
        &mut self,
        arm: usize,
        invalidated: &[String],
        target: Option<&str>,
    ) -> Option<String> {
        let target = target?;
        if invalidated.is_empty() {
            return Some(target.into());
        }
        let boundary = self.routes.point(arm, "", json!({}));
        self.routes.edge(&boundary, target, "next");
        for binding in invalidated {
            self.routes
                .add(&boundary, "PATH_INVALIDATES", binding, json!({}));
        }
        Some(boundary)
    }
    fn try_statement(
        &mut self,
        i: usize,
        after: &str,
        break_to: Option<&str>,
        continue_to: Option<&str>,
        depth: usize,
        kids: &[usize],
    ) -> Result<String> {
        let op = self.ctx.op(i);
        let protected = self.fields(kids).get("body").copied();
        let finalizer = kids
            .iter()
            .find(|&&c| self.ctx.op(c).native_kind == "finally_clause")
            .copied();
        let mut arms = kids
            .iter()
            .filter(|&&c| self.ctx.op(c).native_kind == "except_clause")
            .copied()
            .collect::<Vec<_>>();
        let mut starred = !arms.is_empty();
        let mut opaque = false;
        for &arm in &arms {
            starred &= attributes::tokens(&self.ctx.op(arm).attrs)?
                .iter()
                .any(|t| t == "*");
            let mut todo = self
                .ctx
                .kids(arm)
                .iter()
                .filter(|&&c| self.ctx.op(c).native_kind != "block")
                .copied()
                .collect::<Vec<_>>();
            let mut visited = BTreeSet::new();
            while let Some(header) = todo.pop() {
                if !visited.insert(header) {
                    opaque = true;
                    continue;
                }
                opaque |= self.ctx.op(header).kind == "CALL";
                todo.extend(self.ctx.kids(header));
            }
        }
        if protected.is_none() || opaque {
            self.missing.insert(op.native_kind.clone());
            self.gaps.insert(op.id.clone());
            self.routes.edge(&op.id, after, "uncovered");
            return Ok(op.id.clone());
        }
        self.missing.insert("exception-dispatch".into());
        let outer_handlers = self.targets();
        let mut normal_after = after.to_owned();
        let mut routed_handlers = outer_handlers.clone();
        let mut routed_break = break_to.map(str::to_owned);
        let mut routed_continue = continue_to.map(str::to_owned);
        if let Some(finalizer) = finalizer {
            self.missing.insert("completion-dispatch".into());
            let leave = self.routes.point(
                finalizer,
                "finally-leave",
                json!({"scope":self.ctx.op(finalizer).id}),
            );
            let entry = self.build(finalizer, &leave, break_to, continue_to, depth + 1, None)?;
            let frame = self.routes.register(i, finalizer, entry, leave);
            normal_after = self.routes.finalize(frame, after);
            routed_handlers = outer_handlers
                .iter()
                .map(|target| self.routes.finalize(frame, target))
                .collect();
            routed_break = break_to.map(|target| self.routes.finalize(frame, target));
            routed_continue = continue_to.map(|target| self.routes.finalize(frame, target));
            self.routes.enter(frame);
        }
        let mut handler_after = normal_after.clone();
        if starred {
            self.missing.insert("exception-group".into());
            let merge =
                self.routes
                    .point(i, "star-exit", json!({"scope":op.id,"normal":normal_after}));
            self.routes.edge(&merge, &normal_after, "handled");
            for target in &routed_handlers {
                self.routes.edge(&merge, target, "unhandled");
            }
            handler_after = merge;
            arms.reverse();
        }
        let mut entries = Vec::new();
        let mut close_order = Vec::new();
        let mut catches_all = false;
        for arm in arms {
            let Some(body) = self
                .ctx
                .kids(arm)
                .iter()
                .find(|&&c| self.ctx.op(c).native_kind == "block")
                .copied()
            else {
                continue;
            };
            let types = exceptions::handler_types(self.ctx, arm, self.bound, &self.shadowed)?;
            let mut invalidated = Vec::new();
            for &alias in self
                .ctx
                .kids(arm)
                .iter()
                .filter(|&&c| self.ctx.op(c).native_kind == "as_pattern")
            {
                for &target in self
                    .ctx
                    .kids(alias)
                    .iter()
                    .filter(|&&c| self.ctx.op(c).role == "alias")
                {
                    for &name in self.ctx.kids(target) {
                        if let Some(Value::String(name)) =
                            attributes::get(&self.ctx.op(name).attrs, "text")?
                            && let Some(binding) = self.bindings.get(&name)
                        {
                            invalidated.push(binding.clone());
                        }
                    }
                }
            }
            let next_arm = handler_after.clone();
            let failures = if starred {
                let failed = self.routes.point(arm, "star-raise", json!({"scope":op.id}));
                self.routes.edge(&failed, &next_arm, "next");
                vec![failed]
            } else {
                routed_handlers.clone()
            };
            let failures = failures
                .into_iter()
                .map(|target| {
                    self.cleanup(arm, &invalidated, Some(&target))
                        .unwrap_or(target)
                })
                .collect();
            self.handlers.push(failures);
            let cleaned_after = self.cleanup(arm, &invalidated, Some(&next_arm)).unwrap();
            let cleaned_break = self.cleanup(arm, &invalidated, routed_break.as_deref());
            let cleaned_continue = self.cleanup(arm, &invalidated, routed_continue.as_deref());
            let mut entry = self.build(
                body,
                &cleaned_after,
                cleaned_break.as_deref(),
                cleaned_continue.as_deref(),
                depth + 1,
                None,
            )?;
            self.handlers.pop();
            if !invalidated.is_empty() {
                let boundary = self.routes.point(arm, "", json!({}));
                self.routes.edge(&boundary, &entry, "next");
                for binding in &invalidated {
                    self.routes
                        .add(&boundary, "PATH_INVALIDATES", binding, json!({}));
                }
                entry = boundary;
            }
            let close = exceptions::catches_close(types.as_deref());
            let arm_id = self.ctx.op(arm).id.clone();
            if starred {
                let types = types.unwrap_or_default();
                let matched =
                    self.routes
                        .point(arm, "star-match", json!({"scope":op.id,"types":types}));
                self.routes.dispatch(&arm_id,json!({"operation":arm_id,"action":"star-header","close":close,"types":types,"match":matched}));
                self.routes.edge(&matched, &entry, "next");
                self.routes.edge(&arm_id, &matched, "handler");
                self.routes.edge(&arm_id, &next_arm, "skip");
                handler_after = arm_id;
            } else {
                self.routes.dispatch(&arm_id,json!({"operation":arm_id,"action":"handler","close":close,"close_blocked":close_order.contains(&"yes"),"close_uncertain":close_order.contains(&"unknown")}));
                close_order.push(close);
                self.routes.edge(&arm_id, &entry, "handler");
                entries.push(arm_id);
                if !self
                    .ctx
                    .kids(arm)
                    .iter()
                    .any(|&c| self.ctx.op(c).role == "value")
                {
                    catches_all = true;
                    break;
                }
            }
        }
        if starred {
            let star_entry = self.routes.point(i, "star-enter", json!({"scope":op.id}));
            self.routes.edge(&star_entry, &handler_after, "next");
            entries = vec![star_entry];
        }
        self.handlers.push(routed_handlers.clone());
        for &arm in kids
            .iter()
            .rev()
            .filter(|&&c| self.ctx.op(c).native_kind == "else_clause")
        {
            normal_after = self.build(
                arm,
                &normal_after,
                routed_break.as_deref(),
                routed_continue.as_deref(),
                depth + 1,
                None,
            )?;
        }
        self.handlers.pop();
        let mut propagated = routed_handlers;
        if !starred && !close_order.is_empty() && !catches_all {
            let acceptance = if close_order.contains(&"yes") {
                "no"
            } else if close_order.contains(&"unknown") {
                "unknown"
            } else {
                "yes"
            };
            let mut guarded = Vec::new();
            for target in propagated {
                let boundary = self
                    .routes
                    .point(i, "propagate", json!({"close":acceptance}));
                self.routes.edge(&boundary, &target, "next");
                guarded.push(boundary);
            }
            propagated = guarded;
        }
        if !starred && !catches_all {
            entries.extend(propagated);
        }
        self.handlers.push(entries);
        let normal = self.build(
            protected.unwrap(),
            &normal_after,
            routed_break.as_deref(),
            routed_continue.as_deref(),
            depth + 1,
            None,
        )?;
        self.handlers.pop();
        if finalizer.is_some() {
            self.routes.leave();
        }
        self.routes.edge(&op.id, &normal, "normal");
        Ok(op.id.clone())
    }
    fn finish(
        mut self,
        body: usize,
        diagnostic_paths: Option<&BTreeSet<String>>,
    ) -> Result<Vec<Fact>> {
        let exit = self.exit.clone();
        let entry = self.build(body, &exit, None, None, 0, None)?;
        for &i in self
            .ctx
            .owners
            .get(self.owner.as_str())
            .into_iter()
            .flatten()
        {
            let op = self.ctx.op(i);
            if self.python() && op.kind == "YIELD" && !self.modeled_yields.contains(&op.id) {
                self.missing.insert("suspension-expression".into());
            }
            if ["YIELD", "AWAIT", "THROW"].contains(&op.kind.as_str()) {
                self.missing.insert(op.native_kind.clone());
            }
        }
        let owner = self.owner.clone();
        self.routes.add(
            &owner,
            "CFG_ENTRY",
            &entry,
            json!({"basis":"structured-syntax"}),
        );
        self.routes.add(
            &owner,
            "CFG_EXIT",
            &exit,
            json!({"basis":"structured-syntax"}),
        );
        for (a, b, kind) in std::mem::take(&mut self.routes.edges)
            .into_iter()
            .collect::<BTreeSet<_>>()
        {
            self.routes.add(
                &a,
                "CFG_NEXT",
                &b,
                json!({"kind":kind,"basis":"structured-syntax"}),
            );
            if kind == "next" {
                self.routes.add(
                    &a,
                    "CFG_FALLTHROUGH",
                    &b,
                    json!({"basis":"structured-syntax"}),
                );
            }
        }
        for (a, r, b) in std::mem::take(&mut self.syntax) {
            self.routes.add(&a, &r, &b, json!({"basis":"syntax"}));
        }
        let diagnostics = diagnostic_paths
            .map_or(!self.ctx.graph.diagnostics.is_empty(), |paths| {
                paths.contains(&self.ctx.entity(&owner).expect("validated owner").path)
            });
        let status = if !self.missing.is_empty() || diagnostics {
            "partial"
        } else {
            "structured"
        };
        self.routes.add(&owner,"CFG_STATUS",status,json!({"level":"statement","excluded":"expression-evaluation,exceptions,suspension","reasons":self.missing,"analysis":"structured-cfg/2","gaps":self.gaps,"language":self.language}));
        Ok(self.routes.output)
    }
}
/// Append statement routes and explicit coverage, without expanding expression evaluation.
/// `diagnostic_paths` narrows parser uncertainty; `None` applies IR diagnostics to all owners.
pub fn structured_control(
    graph: &mut StructuralIr,
    diagnostic_paths: Option<&BTreeSet<String>>,
) -> Result<()> {
    let ctx = Context::new(graph);
    let bound = graph
        .facts
        .iter()
        .filter(|f| f.relation == "BINDING_REFERENCE")
        .map(|f| f.subject.clone())
        .collect();
    let mut bindings = BTreeMap::<String, BTreeMap<String, String>>::new();
    for fact in &graph.facts {
        if ["DECLARES", "HAS_PARAMETER"].contains(&fact.relation.as_str())
            && let Some(e) = ctx.entities.get(fact.object.as_str())
            && ["STORAGE", "PARAMETER"].contains(&e.kind.as_str())
        {
            bindings
                .entry(fact.subject.clone())
                .or_default()
                .insert(e.name.clone(), e.id.clone());
        }
    }
    let by_scope = exceptions::shadowed(graph)?;
    let mut output = Vec::new();
    let empty = BTreeMap::new();
    for (i, body) in graph.operations.iter().enumerate() {
        let Some(parent) = ctx.parent(i) else {
            continue;
        };
        if body.role != "body"
            || ctx.op(parent).kind != "FUNCTION"
            || body.owner != ctx.op(parent).owner
        {
            continue;
        }
        let mut shadowed = BTreeSet::new();
        let mut scope = body.owner.as_str();
        while scope.contains("::module") {
            shadowed.extend(by_scope.get(scope).into_iter().flatten().cloned());
            if scope.ends_with("::module") {
                break;
            }
            let Some((outer, _)) = scope.rsplit_once('/') else {
                break;
            };
            scope = outer;
        }
        output.extend(
            Builder::new(
                &ctx,
                &body.owner,
                &bound,
                shadowed,
                bindings.get(&body.owner).unwrap_or(&empty),
            )?
            .finish(i, diagnostic_paths)?,
        );
    }
    append(graph, output);
    Ok(())
}
