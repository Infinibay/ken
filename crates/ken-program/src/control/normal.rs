//! Bounded statement completion never implies exception dispatch or reachability.
use super::{append, fact, index::Context};
use crate::{ProgramError, StructuralIr, attributes};
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};
const BLOCKS: &[&str] = &[
    "block",
    "statement_block",
    "compound_statement",
    "else_clause",
];
const HANDLERS: &[&str] = &["except_clause", "catch_clause"];
const SIMPLE: &[&str] = &[
    "expression_statement",
    "local_variable_declaration",
    "lexical_declaration",
    "variable_declaration",
    "declaration",
    "pass_statement",
    "empty_statement",
    "assert_statement",
    "assert",
    "global_statement",
    "nonlocal_statement",
    "import_statement",
    "import_from_statement",
    "delete_statement",
];
const ABRUPT: &[&str] = &[
    "return_statement",
    "throw_statement",
    "raise_statement",
    "break_statement",
    "continue_statement",
];
const SUSPENSION: &[&str] = &[
    "yield",
    "yield_expression",
    "await",
    "await_expression",
    "throw_expression",
    "co_await_expression",
    "co_yield_expression",
];
struct Completion<'a> {
    ctx: Context<'a>,
    children: Vec<Vec<usize>>,
    memo: BTreeMap<(String, usize), &'static str>,
}
impl<'a> Completion<'a> {
    fn new(graph: &'a StructuralIr) -> Self {
        let ctx = Context::new(graph);
        let mut children = vec![Vec::new(); graph.operations.len()];
        for (i, op) in graph.operations.iter().enumerate() {
            if let Some(parent) = ctx.parent(i)
                && ctx.op(parent).owner == op.owner
                && !op.native_kind.contains("comment")
            {
                children[parent].push(i);
            }
        }
        for kids in &mut children {
            kids.sort_by_key(|&i| {
                let o = ctx.op(i);
                (o.start, o.end, &o.id)
            });
        }
        Self {
            ctx,
            children,
            memo: BTreeMap::new(),
        }
    }
    fn kids(&self, i: usize) -> &[usize] {
        &self.children[self.ctx.ids[self.ctx.op(i).id.as_str()]]
    }
    fn body(&self, i: usize) -> Option<usize> {
        self.kids(i)
            .iter()
            .copied()
            .find(|&c| BLOCKS.contains(&self.ctx.op(c).native_kind.as_str()))
    }
    fn plain_try(&self, i: usize) -> bool {
        self.ctx.op(i).native_kind == "try_statement"
            && self.kids(i).iter().all(|&c| {
                self.ctx.op(c).role == "body"
                    || HANDLERS.contains(&self.ctx.op(c).native_kind.as_str())
            })
    }
    fn expression(&self, i: usize) -> bool {
        let mut todo = vec![i];
        let mut seen = BTreeSet::new();
        while let Some(i) = todo.pop() {
            let op = self.ctx.op(i);
            if !seen.insert(op.id.as_str())
                || SUSPENSION.contains(&op.native_kind.as_str())
                || matches!(op.kind.as_str(), "YIELD" | "AWAIT")
            {
                return false;
            }
            todo.extend(self.kids(i));
        }
        true
    }
    fn outcome(&mut self, i: usize, depth: usize) -> Result<&'static str, ProgramError> {
        let op = self.ctx.op(i);
        let key = (op.id.clone(), depth);
        if let Some(result) = self.memo.get(&key) {
            return Ok(result);
        }
        if depth > 64 {
            return Ok("unsupported");
        }
        let language = attributes::get(&self.ctx.entity(&op.owner)?.attrs, "language")?;
        let mut result = "unsupported";
        let kind = op.native_kind.as_str();
        let kids = self.kids(i).to_vec();
        if !self.ctx.graph.diagnostics.is_empty()
            || !language.as_ref().and_then(|v| v.as_str()).is_some_and(|l| {
                matches!(
                    l,
                    "python" | "javascript" | "typescript" | "java" | "csharp" | "cpp"
                )
            })
        {
        } else if ABRUPT.contains(&kind) {
            result = "abrupt";
        } else if SIMPLE.contains(&kind) {
            result = if self.expression(i) {
                "possible"
            } else {
                "unsupported"
            };
        } else if BLOCKS.contains(&kind) {
            result = "possible";
            for child in kids {
                result = self.outcome(child, depth + 1)?;
                if result != "possible" {
                    break;
                }
            }
        } else if HANDLERS.contains(&kind) {
            if let Some(body) = self.body(i)
                && !attributes::tokens(&op.attrs)?.iter().any(|t| t == "*")
            {
                result = self.outcome(body, depth + 1)?;
            }
        } else if matches!(kind, "if_statement" | "elif_clause") {
            let consequence = kids
                .iter()
                .copied()
                .find(|&c| self.ctx.op(c).role == "consequence");
            let alternatives = kids
                .iter()
                .copied()
                .filter(|&c| self.ctx.op(c).role == "alternative")
                .collect::<Vec<_>>();
            if let Some(consequence) = consequence {
                let mut arms = vec![self.outcome(consequence, depth + 1)?];
                for &arm in &alternatives {
                    if self.ctx.op(arm).native_kind == "elif_clause" {
                        let branch = self
                            .kids(arm)
                            .iter()
                            .copied()
                            .find(|&c| self.ctx.op(c).role == "consequence");
                        arms.push(if let Some(branch) = branch {
                            self.outcome(branch, depth + 1)?
                        } else {
                            "unsupported"
                        });
                    } else {
                        arms.push(self.outcome(arm, depth + 1)?);
                    }
                }
                if alternatives
                    .last()
                    .is_none_or(|&c| self.ctx.op(c).native_kind == "elif_clause")
                {
                    arms.push("possible");
                }
                if kids
                    .iter()
                    .copied()
                    .find(|&c| self.ctx.op(c).role == "condition")
                    .is_some_and(|c| !self.expression(c))
                {
                    arms.push("unsupported");
                }
                result = combine(&arms);
            }
        } else if self.plain_try(i) {
            let mut outcomes = Vec::new();
            for c in kids
                .into_iter()
                .filter(|&c| {
                    self.ctx.op(c).role == "body"
                        || HANDLERS.contains(&self.ctx.op(c).native_kind.as_str())
                })
                .collect::<Vec<_>>()
            {
                outcomes.push(self.outcome(c, depth + 1)?);
            }
            if !outcomes.is_empty() {
                result = combine(&outcomes);
            }
        }
        self.memo.insert(key, result);
        Ok(result)
    }
}
fn combine(outcomes: &[&str]) -> &'static str {
    if outcomes.contains(&"unsupported") {
        "unsupported"
    } else if outcomes.contains(&"possible") {
        "possible"
    } else {
        "abrupt"
    }
}
/// Append statement completion and handler/loop evidence with explicit unsupported scopes.
pub fn normal_completion(graph: &mut StructuralIr) -> Result<(), ProgramError> {
    let mut analysis = Completion::new(graph);
    let mut output = Vec::new();
    for (i, op) in graph.operations.iter().enumerate() {
        let path = analysis.ctx.entity(&op.owner)?.path.clone();
        let evidence = || Some(format!("{path}:{}", op.line));
        if matches!(
            op.native_kind.as_str(),
            "try_statement" | "try_with_resources_statement"
        ) {
            let mut pending = analysis
                .kids(i)
                .iter()
                .copied()
                .filter(|&c| analysis.ctx.op(c).native_kind == "finally_clause")
                .collect::<Vec<_>>();
            let (mut overrides, mut cyclic) = (false, false);
            let mut seen = BTreeSet::new();
            while let Some(c) = pending.pop() {
                if !seen.insert(analysis.ctx.op(c).id.as_str()) {
                    cyclic = true;
                    break;
                }
                let kind = analysis.ctx.op(c).native_kind.as_str();
                overrides |= ABRUPT.contains(&kind) || SUSPENSION.contains(&kind);
                pending.extend(analysis.kids(c));
            }
            let status = if !graph.diagnostics.is_empty()
                || op.native_kind == "try_with_resources_statement"
                || cyclic
            {
                "unsupported"
            } else if overrides {
                "may-override"
            } else {
                "no-explicit-override"
            };
            output.push(fact(
                &op.id,
                "TRY_EXIT_STATUS",
                status,
                None,
                json!({"basis":"lexical-finalizer-exits/1"}),
            ));
        }
        if BLOCKS.contains(&op.native_kind.as_str())
            || HANDLERS.contains(&op.native_kind.as_str())
            || matches!(
                op.native_kind.as_str(),
                "try_statement" | "if_statement" | "elif_clause"
            )
        {
            let ev = evidence();
            let outcome = analysis.outcome(i, 0)?;
            output.push(fact(
                &op.id,
                "NORMAL_COMPLETION",
                outcome,
                ev,
                json!({"basis":"statement-normal/1"}),
            ));
        }
        if op.kind == "LOOP"
            && let Some(body) = analysis
                .kids(i)
                .iter()
                .copied()
                .find(|&c| analysis.ctx.op(c).role == "body")
        {
            let statements = if BLOCKS.contains(&analysis.ctx.op(body).native_kind.as_str()) {
                analysis.kids(body).to_vec()
            } else {
                vec![body]
            };
            if let Some(&tail) = statements.last() {
                let tail = analysis.ctx.op(tail);
                output.push(fact(
                    &op.id,
                    "LOOP_BODY_TAIL",
                    &tail.id,
                    Some(format!(
                        "{}:{}",
                        analysis.ctx.entity(&op.owner)?.path,
                        tail.line
                    )),
                    json!({"basis":"syntax"}),
                ));
            }
        }
        if HANDLERS.contains(&op.native_kind.as_str())
            && let Some(parent) = analysis.ctx.parent(i)
            && analysis.ctx.op(parent).owner == op.owner
            && analysis.plain_try(parent)
            && analysis.outcome(i, 0)? == "possible"
        {
            output.push(fact(
                &op.id,
                "HANDLER_FALLTHROUGH",
                &analysis.ctx.op(parent).id,
                evidence(),
                json!({"basis":"statement-normal/1"}),
            ));
        }
    }
    append(graph, output);
    Ok(())
}
