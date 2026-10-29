//! Pending completions and guarded finalizer continuations share one route inventory.
use super::{fact, index::Context};
use crate::Fact;
use serde_json::{Value, json};
use std::collections::BTreeMap;
pub(super) struct Finalization {
    operation: usize,
    finalizer: usize,
    entry: String,
    leave: String,
    destinations: BTreeMap<String, String>,
    outer_return: Option<usize>,
}

pub(super) struct CompletionRoutes<'a, 'b> {
    ctx: &'a Context<'b>,
    owner: String,
    exit: String,
    pub output: Vec<Fact>,
    pub edges: Vec<(String, String, String)>,
    serial: usize,
    scopes: BTreeMap<String, Vec<String>>,
    pub finalizers: Vec<usize>,
    frames: Vec<Finalization>,
    returns: Vec<usize>,
}
impl<'a, 'b> CompletionRoutes<'a, 'b> {
    pub fn new(ctx: &'a Context<'b>, owner: &str) -> Self {
        let mut finalizers = ctx
            .owners
            .get(owner)
            .into_iter()
            .flatten()
            .copied()
            .filter(|&i| ctx.op(i).native_kind == "finally_clause")
            .collect::<Vec<_>>();
        // Stable outer-to-inner order is also the unwind scope order.
        finalizers.sort_by_key(|&i| i128::from(ctx.op(i).start) - i128::from(ctx.op(i).end));
        Self {
            ctx,
            owner: owner.into(),
            exit: format!("{owner}::cfg-exit"),
            output: Vec::new(),
            edges: Vec::new(),
            serial: 0,
            scopes: BTreeMap::new(),
            finalizers,
            frames: Vec::new(),
            returns: Vec::new(),
        }
    }
    pub fn register(
        &mut self,
        operation: usize,
        finalizer: usize,
        entry: String,
        leave: String,
    ) -> usize {
        let frame = self.frames.len();
        self.frames.push(Finalization {
            operation,
            finalizer,
            entry,
            leave,
            destinations: BTreeMap::new(),
            outer_return: self.returns.last().copied(),
        });
        frame
    }
    pub fn enter(&mut self, frame: usize) {
        self.returns.push(frame);
    }
    pub fn leave(&mut self) {
        self.returns.pop();
    }
    pub fn add(&mut self, a: &str, r: &str, b: &str, attrs: Value) {
        self.output.push(fact(a, r, b, None, attrs));
    }
    pub fn dispatch(&mut self, id: &str, attrs: Value) {
        let owner = self.owner.clone();
        self.add(&owner, "CFG_DISPATCH", id, attrs);
    }
    pub fn edge(&mut self, a: &str, b: &str, kind: &str) {
        self.edges.push((a.into(), b.into(), kind.into()));
    }
    fn lexical_scopes(&self, point: &str) -> Vec<String> {
        if let Some(scopes) = self.scopes.get(point) {
            return scopes.clone();
        }
        let Some(&i) = self.ctx.ids.get(point) else {
            return Vec::new();
        };
        let op = self.ctx.op(i);
        self.finalizers
            .iter()
            .copied()
            .filter(|&f| self.ctx.op(f).start <= op.start && op.end <= self.ctx.op(f).end)
            .map(|f| self.ctx.op(f).id.clone())
            .collect()
    }
    pub fn point(&mut self, i: usize, action: &str, attrs: Value) -> String {
        let op = self.ctx.op(i);
        self.serial += 1;
        let id = format!("{}::continuation-{}", op.id, self.serial);
        self.scopes.insert(id.clone(), self.lexical_scopes(&op.id));
        let mut data = attrs.as_object().expect("continuation attributes").clone();
        data.insert("operation".into(), op.id.clone().into());
        data.insert("action".into(), action.into());
        self.dispatch(&id, Value::Object(data));
        id
    }
    pub fn depart(&mut self, i: usize, target: &str) -> String {
        let target_scopes = self.lexical_scopes(target);
        let abandoned = self
            .lexical_scopes(&self.ctx.op(i).id)
            .into_iter()
            .filter(|s| !target_scopes.contains(s))
            .collect::<Vec<_>>();
        if abandoned.is_empty() {
            return target.into();
        }
        let point = self.point(i, "unwind", json!({"scopes":abandoned}));
        self.edge(&point, target, "next");
        point
    }
    pub fn finalize(&mut self, frame: usize, target: &str) -> String {
        if let Some(dest) = self.frames[frame].destinations.get(target) {
            return dest.clone();
        }
        let finalizer = self.frames[frame].finalizer;
        let operation = self.frames[frame].operation;
        let entry = self.frames[frame].entry.clone();
        let leave = self.frames[frame].leave.clone();
        let continuation = self.depart(finalizer, target);
        let enter = self.point(
            operation,
            "finally-enter",
            json!({"scope":self.ctx.op(finalizer).id,"target":continuation}),
        );
        self.edge(&enter, &entry, "next");
        self.edge(&leave, &continuation, "resume");
        self.frames[frame]
            .destinations
            .insert(target.into(), enter.clone());
        enter
    }
    fn return_route(&mut self, frame: usize, terminal: &str) -> String {
        let target = if let Some(outer) = self.frames[frame].outer_return {
            self.return_route(outer, terminal)
        } else {
            terminal.into()
        };
        self.finalize(frame, &target)
    }
    pub fn returned(&mut self, i: usize) -> String {
        let terminal = self.point(i, "return-complete", json!({}));
        let exit = self.exit.clone();
        self.edge(&terminal, &exit, "return");
        let target = if let Some(&frame) = self.returns.last() {
            self.return_route(frame, &terminal)
        } else {
            terminal
        };
        let evaluated = self.point(i, "return-eval", json!({}));
        self.edge(&evaluated, &target, "next");
        evaluated
    }
}
