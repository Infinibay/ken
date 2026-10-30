//! Streaming depth-first joins; no collection of intermediate binding frames.
use super::super::{SourceProbe, values::Value};
use super::*;
use crate::{BodyPattern, Scan};
impl Runtime<'_, '_> {
    pub(super) fn walk(&mut self, index: usize, frame: Frame) -> Result<()> {
        crate::with_stack(|| {
            if index == 0 && self.run.initial_checked {
                self.run.initial_checked = false;
            } else {
                self.check()?;
            }
            if index == self.steps.len() {
                return self.project(frame);
            }
            let step = self.steps[index].clone();
            self.metric(index, "input_rows", 1);
            let started = Instant::now();
            match step {
                Step::Action(action) => {
                    let value = self.evaluate(&action.expression, &frame.bindings)?;
                    let mut frame = frame;
                    if !action.role.is_empty() {
                        frame.bindings.insert(action.role, value);
                    } else if value.is_false() {
                        self.elapsed(index, started);
                        return Ok(());
                    } else {
                        frame.uncertain |= value.is_unknown();
                    }
                    self.emit(index, frame, started)
                }
                Step::Body(pattern) => self.body(index, pattern, frame),
                Step::Scan(scan) => self.scan(index, scan, frame),
            }
        })
    }
    fn emit(&mut self, index: usize, frame: Frame, started: Instant) -> Result<()> {
        self.metric(index, "output_rows", 1);
        self.elapsed(index, started);
        self.walk(index + 1, frame)
    }
    fn body(&mut self, index: usize, pattern: BodyPattern, frame: Frame) -> Result<()> {
        let graph = self.graph;
        let mut cursor =
            super::super::body_runtime::BodyCursor::new(graph, Arc::new(pattern), frame.bindings);
        loop {
            let started = Instant::now();
            let Some(found) = cursor.next(self)? else {
                self.elapsed(index, started);
                break;
            };
            self.emit(
                index,
                Frame {
                    bindings: found.bindings,
                    uncertain: frame.uncertain || found.unknown,
                },
                started,
            )?;
        }
        Ok(())
    }
    fn scan(&mut self, index: usize, scan: Scan, frame: Frame) -> Result<()> {
        if let Some(name) = scan.selector.strip_prefix("enum:") {
            let members = self
                .program
                .enums
                .iter()
                .find(|(n, _)| n == name)
                .map(|(_, v)| v.clone())
                .ok_or_else(|| invalid("unknown enum domain"))?;
            for member in members {
                let started = Instant::now();
                self.check()?;
                let value = Value::Enum {
                    r#type: name.into(),
                    name: member,
                };
                if frame.bindings.get(&scan.role).is_some_and(|v| *v != value) {
                    continue;
                }
                let mut next = frame.clone();
                next.bindings.insert(scan.role.clone(), value);
                self.emit(index, next, started)?;
            }
            return Ok(());
        }
        let parent = scan
            .owner
            .as_ref()
            .map(|owner| {
                frame
                    .bindings
                    .get(owner)
                    .cloned()
                    .ok_or_else(|| invalid("scan owner is not bound"))
            })
            .transpose()?;
        if matches!(scan.selector.as_str(), "node" | "expression" | "statement") {
            let parent = match parent {
                None => None,
                Some(Value::Ast(v)) => Some(v),
                _ => return Err(invalid("AST selector requires an AST parent")),
            };
            let exact = |name: &str| {
                scan.properties
                    .iter()
                    .find(|(key, e)| key == name && e.kind == "literal")
                    .map(|(_, e)| {
                        Value::literal(&e.value).and_then(|v| {
                            v.text()
                                .ok_or_else(|| invalid("AST lookup requires a string"))
                        })
                    })
                    .transpose()
            };
            let name = if self.run.execution.options.reference {
                None
            } else {
                exact("name")?
            };
            let kind = if self.run.execution.options.reference {
                None
            } else {
                exact("kind")?
            };
            return self.ast_visit(
                &scan.selector,
                parent.as_deref(),
                name.as_deref(),
                kind.as_deref(),
                &mut |runtime, value| runtime.accept(index, &scan, &frame, value, false),
            );
        }
        if scan.selector == "operation" {
            let owner = match parent {
                None => None,
                Some(Value::Node(v)) => Some(v),
                _ => return Err(invalid("operation selector requires a source owner")),
            };
            return self.operation_visit(owner.as_deref(), &mut |runtime, value| {
                runtime.accept(index, &scan, &frame, value, false)
            });
        }
        let owner = match parent {
            None => None,
            Some(Value::Node(v)) => Some(v),
            _ => return Err(invalid("source selector requires a source owner")),
        };
        let existing = match frame.bindings.get(&scan.role) {
            None => None,
            Some(Value::Node(v)) => Some(v.clone()),
            _ => return Err(invalid("source scan role must be a node")),
        };
        let name = scan
            .properties
            .iter()
            .find(|(key, e)| key == "name" && e.kind == "literal")
            .map(|(_, e)| {
                Value::literal(&e.value).and_then(|v| {
                    v.text()
                        .ok_or_else(|| invalid("name lookup requires a string"))
                })
            })
            .transpose()?;
        let kinds = crate::capabilities::vocabulary()
            .kinds
            .get(&scan.selector)
            .cloned()
            .ok_or_else(|| invalid("unknown source selector"))?;
        for kind in kinds {
            let probe = SourceProbe {
                kind: Some(kind),
                name: name.clone(),
                owner: owner.as_ref().map(|n| (n.unit, n.local_id.clone())),
                node_id: existing.as_ref().map(|n| n.id),
                reference: self.run.execution.options.reference,
            };
            self.entity_visit(&probe, &mut |runtime, node| {
                if matches!(
                    scan.selector.as_str(),
                    "var" | "param" | "receiver" | "constructor"
                ) {
                    let property = match scan.selector.as_str() {
                        "var" => "declared",
                        "constructor" => "constructor",
                        _ => "receiver",
                    };
                    let actual = runtime.property(&Value::Node(node.clone()), property)?;
                    if actual.is_unknown() {
                        runtime.run.out.unknown_candidates += 1;
                        return Ok(());
                    }
                    let pass = if matches!(scan.selector.as_str(), "param" | "receiver") {
                        match &actual {
                            Value::Scalar(value) => value.truthy() == (scan.selector == "receiver"),
                            _ => false,
                        }
                    } else {
                        actual.is_true()
                    };
                    if !pass {
                        return Ok(());
                    }
                }
                runtime.accept(index, &scan, &frame, Value::Node(node), true)
            })?;
        }
        Ok(())
    }
    fn accept(
        &mut self,
        index: usize,
        scan: &Scan,
        frame: &Frame,
        value: Value,
        typed: bool,
    ) -> Result<()> {
        let started = Instant::now();
        if frame.bindings.get(&scan.role).is_some_and(|v| *v != value) {
            return Ok(());
        }
        let mut next = frame.clone();
        for (name, expected) in &scan.properties {
            if expected.kind == "wildcard" {
                continue;
            }
            let truth = if typed && matches!(name.as_str(), "type" | "return_type") {
                let Value::Node(node) = &value else {
                    return Err(invalid("source type property requires a node"));
                };
                self.with_source(|s| {
                    let descriptor = s.type_of(&node.local_id, name == "return_type")?;
                    s.matches(&descriptor, expected)
                })
                .map(source::truth)?
            } else {
                let actual = self.property(&value, name)?;
                if actual.is_unknown() {
                    Value::unknown("capability_missing")
                } else if expected.kind == "regex" {
                    if let Some(text) = actual.text() {
                        Value::boolean(self.regex(&text, expected)?)
                    } else {
                        Value::boolean(false)
                    }
                } else {
                    let expected = if expected.kind == "literal" {
                        Value::literal(&expected.value)?
                    } else {
                        Value::null()
                    };
                    // Python property matching permits numeric equality for AST/op
                    // attributes, while entity property tests retain type identity.
                    let equal = if typed {
                        actual.identity()? == expected.identity()?
                    } else {
                        match super::super::values::compare(&actual, &expected) {
                            Ok(order) => order == std::cmp::Ordering::Equal,
                            Err(_) => actual == expected,
                        }
                    };
                    Value::boolean(equal)
                }
            };
            if truth.is_false() {
                self.elapsed(index, started);
                return Ok(());
            }
            next.uncertain |= truth.is_unknown();
        }
        next.bindings.insert(scan.role.clone(), value);
        self.emit(index, next, started)
    }
    fn project(&mut self, frame: Frame) -> Result<()> {
        self.check()?;
        let mut computed = frame.bindings.clone();
        let mut uncertain = frame.uncertain;
        if self.program.steps.is_empty() {
            let actions = if self.program.actions.is_empty() {
                self.program
                    .filters
                    .iter()
                    .cloned()
                    .map(|e| (String::new(), e))
                    .collect()
            } else {
                self.program.actions.clone()
            };
            for (role, condition) in actions {
                let value = self.evaluate(&condition, &computed)?;
                if !role.is_empty() {
                    computed.insert(role, value);
                } else if value.is_false() {
                    return Ok(());
                } else {
                    uncertain |= value.is_unknown();
                }
            }
        }
        let projection = self.program.projection.clone();
        let ordering = self.program.ordering.clone();
        let mut row = vec![];
        let mut order = vec![];
        for e in &projection {
            row.push(
                self.evaluate(
                    e.args
                        .first()
                        .ok_or_else(|| invalid("projection operand missing"))?,
                    &computed,
                )?,
            );
        }
        for e in &ordering {
            order.push(
                self.evaluate(
                    e.args
                        .first()
                        .ok_or_else(|| invalid("ordering operand missing"))?,
                    &computed,
                )?,
            );
        }
        if uncertain || row.iter().chain(&order).any(Value::is_unknown) {
            self.run.out.unknown_candidates += 1;
            return Ok(());
        }
        let key = Value::tuple(row.clone()).identity()?;
        if !self.run.seen.contains(&key) {
            if self
                .run
                .execution
                .options
                .max_rows
                .is_some_and(|max| self.run.materialized.len() as u64 >= max)
            {
                return Err(ExecutionError::Exhausted("max_rows"));
            }
            self.run.seen.insert(key);
            self.run.materialized.push((row, order));
        }
        for optional in self.program.optional.clone() {
            let truth = self.evaluate(&optional, &computed)?;
            let bindings: serde_json::Map<String, Json> = frame
                .bindings
                .iter()
                .map(|(key, value)| {
                    (
                        key.clone(),
                        match value {
                            Value::Node(n) => json!(n.id),
                            other => json!(source::repr(other)),
                        },
                    )
                })
                .collect();
            self.run.out.optional_evidence.push(json!({"source":optional.span.source,"start":optional.span.start,"end":optional.span.end,"status":if truth.is_unknown(){"unknown"}else if truth.is_true(){"matched"}else{"absent"},"bindings":bindings}));
        }
        Ok(())
    }
}
