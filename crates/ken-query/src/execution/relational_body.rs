//! Translate relational identities and evidence at the BODY cursor boundary.
use super::{
    ExecutionError, Result,
    body_runtime::{BodyCursor, BodyServices},
    engine::Engine,
    evidence::{Proof, Row},
    values::{Bindings, Value, repr},
};
use crate::{BodyPattern, ast::Expr};
use ken_program::value::GraphValue as Scalar;
use std::sync::Arc;
fn display(value: &Value) -> String {
    match value {
        Value::Scalar(v) => v.string().unwrap_or_else(|| v.repr()),
        _ => repr(value),
    }
}
impl Engine<'_> {
    pub fn source_body(
        &mut self,
        pattern: Arc<BodyPattern>,
        row: Row,
        out: &mut Vec<Row>,
    ) -> Result<()> {
        self.tick()?;
        let mut bindings = Bindings::new();
        for (role, id) in &row.bindings {
            self.check()?;
            let value = self
                .graph
                .source_node(id)?
                .map_or_else(|| Value::string(id.as_str()), Value::Node);
            bindings.insert(role.strip_prefix('$').unwrap_or(role).into(), value);
        }
        let owner = row
            .bindings
            .get(&format!("${}", pattern.owner))
            .map(|id| self.graph.source_node(id))
            .transpose()?
            .flatten()
            .map(|n| n.local_id.clone());
        let mut cursor = BodyCursor::new(self.graph, pattern.clone(), bindings);
        while let Some(hit) = cursor.next(&mut Services(self))? {
            self.tick()?;
            let mut next = row.clone();
            if hit.unknown {
                next.unknown.insert("source_body:unknown".into());
            }
            for role in &pattern.outputs {
                let value = hit.bindings.get(role).ok_or_else(|| {
                    ExecutionError::Invalid(format!("BODY output {role} is unbound"))
                })?;
                let value = if let Some(id) = value.local_id() {
                    id.into()
                } else if value.is_unknown() {
                    next.unknown.insert("source_body:unknown".into());
                    format!("@unknown:{role}")
                } else {
                    display(value)
                };
                next.bindings.insert(format!("${role}"), value);
            }
            next.evidence = next.append(Proof::Source(Arc::new(
                serde_json::json!({"body_owner":owner}),
            )));
            out.push(next);
        }
        Ok(())
    }
}
struct Services<'a, 'g>(&'a mut Engine<'g>);
impl BodyServices for Services<'_, '_> {
    fn check(&mut self) -> Result<()> {
        self.0.tick()
    }
    fn evaluate(&mut self, e: &Expr, b: &Bindings) -> Result<Value> {
        crate::with_stack(|| {
            self.check()?;
            match e.kind.as_str() {
                "role" => Ok(b
                    .get(&e.value)
                    .cloned()
                    .unwrap_or_else(|| Value::unknown("unbound_source_role"))),
                "literal" => Value::literal(&e.value),
                "member" => {
                    let Some(arg) = e.args.first() else {
                        return Err(ExecutionError::Invalid("member requires an operand".into()));
                    };
                    let owner = self.evaluate(arg, b)?;
                    let record = match &owner {
                        Value::Node(n) => Some(serde_json::to_value(n)),
                        Value::Operation(n) => Some(serde_json::to_value(n)),
                        _ => None,
                    };
                    if let Some(record) = record {
                        let record = record.map_err(|e| ExecutionError::Invalid(e.to_string()))?;
                        if let Some(value) = record.get(&e.value) {
                            return Value::literal(&value.to_string());
                        }
                    }
                    if let Value::Node(node) = owner
                        && let Some(value) = self.0.graph.source_properties(&node)?.get(&e.value)
                    {
                        return Ok(Value::Scalar(value.clone()));
                    }
                    Ok(Value::unknown("attribute_missing"))
                }
                "binary" => {
                    if e.args.len() != 2 {
                        return Err(ExecutionError::Invalid(
                            "binary requires two operands".into(),
                        ));
                    }
                    let a = self.evaluate(&e.args[0], b)?;
                    let c = self.evaluate(&e.args[1], b)?;
                    if a.is_unknown() || c.is_unknown() {
                        return Ok(Value::unknown("source_condition_unknown"));
                    }
                    if e.value == "and" {
                        return Ok(Value::boolean(a.is_true() && c.is_true()));
                    }
                    if e.value == "or" {
                        return Ok(Value::boolean(a.is_true() || c.is_true()));
                    }
                    if matches!(e.value.as_str(), "==" | "!=" | "<" | ">" | "<=" | ">=") {
                        let actual = match &a {
                            Value::Scalar(v) => v.clone(),
                            _ => Scalar::String(display(&a).into()),
                        };
                        let op = match e.value.as_str() {
                            "==" => "literal",
                            "!=" => "not_literal",
                            op => op,
                        };
                        return self
                            .0
                            .comparisons
                            .compare(&actual, op, &display(&c))
                            .map(Value::boolean);
                    }
                    Ok(Value::unknown("source_condition_unsupported"))
                }
                _ => Ok(Value::unknown("source_condition_unsupported")),
            }
        })
    }
    fn regex(&mut self, text: &str, e: &Expr) -> Result<bool> {
        self.check()?;
        let (pattern, flags) = e
            .value
            .strip_prefix('/')
            .and_then(|v| v.rsplit_once('/'))
            .ok_or_else(|| ExecutionError::Invalid("invalid regular expression".into()))?;
        let pattern = if flags.is_empty() {
            pattern.into()
        } else {
            format!("(?{flags}){pattern}")
        };
        self.0
            .comparisons
            .compare_source(&Scalar::String(text.into()), "regex", &pattern)
    }
}
