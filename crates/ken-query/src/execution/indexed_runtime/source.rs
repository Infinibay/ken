//! Source domains, metadata and canonical AST values retain distinct identities.
use super::super::{
    OperationProbe, SourceProbe,
    source::{Knowledge, Truth},
    values::{AstValue, OperationValue, SourceNode},
};
use super::*;
use ken_program::value::GraphValue as Scalar;
use std::cmp::Ordering;
pub(super) fn truth(value: Truth) -> Value {
    match value {
        Knowledge::Known(v) => Value::boolean(v),
        Knowledge::Unknown(reason) => Value::unknown(reason),
    }
}
pub(super) fn path(value: &Value) -> Option<&str> {
    match value {
        Value::Node(v) => Some(&v.path),
        Value::Operation(v) => Some(&v.path),
        Value::Ast(v) => Some(&v.path),
        _ => None,
    }
}
pub(super) fn local_id(value: &Value) -> Option<String> {
    match value {
        Value::Ast(v) => Some(format!("{}::ast:{}", v.path, v.node.id)),
        _ => value.local_id().map(str::to_owned),
    }
}
pub(super) fn order_value(a: &Value, b: &Value) -> Ordering {
    fn category(v: &Value) -> &str {
        match v {
            Value::Node(_) | Value::Operation(_) | Value::Ast(_) => "Entity",
            Value::Enum { .. } => "Enum",
            Value::Scalar(Scalar::String(_)) => "str",
            Value::Scalar(Scalar::Int(_)) => "int",
            Value::Scalar(Scalar::Float(_)) => "float",
            Value::Scalar(Scalar::Bool(_)) => "bool",
            _ => "Null",
        }
    }
    let (ca, cb) = (category(a), category(b));
    let order = ca.cmp(cb);
    if order != Ordering::Equal {
        return order;
    }
    match (a, b) {
        (
            Value::Enum {
                r#type: at,
                name: an,
            },
            Value::Enum {
                r#type: bt,
                name: bn,
            },
        ) => format!("{at}.{an}").cmp(&format!("{bt}.{bn}")),
        (Value::Scalar(Scalar::Bool(a)), Value::Scalar(Scalar::Bool(b))) => a.cmp(b),
        _ if ca == "Entity" => format!(
            "{}:{}",
            path(a).unwrap_or(""),
            local_id(a).unwrap_or_default()
        )
        .cmp(&format!(
            "{}:{}",
            path(b).unwrap_or(""),
            local_id(b).unwrap_or_default()
        )),
        _ if matches!(ca, "str" | "int" | "float") => {
            super::super::values::compare(a, b).unwrap_or(Ordering::Equal)
        }
        _ => Ordering::Equal,
    }
}
pub(super) use super::super::values::repr;
impl Runtime<'_, '_> {
    fn properties(&mut self, node: &SourceNode) -> Result<BTreeMap<String, Scalar>> {
        if let Some(value) = self.properties.get(&node.local_id) {
            return Ok(value.clone());
        }
        let value = self.graph.source_properties(node)?;
        while self.properties.len() >= 1024 {
            if let Some(key) = self.property_order.pop_front() {
                self.properties.remove(&key);
            } else {
                break;
            }
        }
        self.properties.insert(node.local_id.clone(), value.clone());
        self.property_order.push_back(node.local_id.clone());
        Ok(value)
    }
    pub(super) fn property(&mut self, value: &Value, name: &str) -> Result<Value> {
        let found = match value {
            Value::Node(node) => {
                if matches!(
                    name,
                    "type" | "return_type" | "type_status" | "return_type_status"
                ) {
                    let descriptor = self
                        .with_source(|s| s.type_of(&node.local_id, name.starts_with("return_")))?;
                    return Ok(if name.ends_with("status") {
                        Value::string(if matches!(descriptor, Knowledge::Known(_)) {
                            "known"
                        } else {
                            "unknown"
                        })
                    } else {
                        match descriptor {
                            Knowledge::Known(v) => Value::Type(v),
                            Knowledge::Unknown(r) => Value::unknown(r),
                        }
                    });
                }
                match name {
                    "name" => node
                        .name
                        .as_ref()
                        .map(|v| Scalar::String(v.as_str().into())),
                    "path" => Some(Scalar::String(node.path.as_str().into())),
                    "language" => Some(Scalar::String(node.language.as_str().into())),
                    _ => self.properties(node)?.get(name).cloned(),
                }
            }
            Value::Operation(node) => match name {
                "snapshot" => Some(Scalar::Int(node.snapshot.to_string())),
                "local_id" => Some(Scalar::String(node.local_id.as_str().into())),
                "kind" => Some(Scalar::String(node.kind.as_str().into())),
                "native_kind" => Some(Scalar::String(node.native_kind.as_str().into())),
                "path" => Some(Scalar::String(node.path.as_str().into())),
                "line" => Some(Scalar::Int(node.line.to_string())),
                "owner" => Some(Scalar::String(node.owner.as_str().into())),
                "language" => Some(Scalar::String(node.language.as_str().into())),
                "execution" => Some(Scalar::String(node.execution.as_str().into())),
                _ => None,
            },
            Value::Ast(node) => match name {
                "normalized" => Some(Scalar::Bool(node.node.category != "opaque")),
                "namespace" => Some(Scalar::String(node.namespace.as_str().into())),
                "scope_kind" => Some(Scalar::String(node.scope_kind.as_str().into())),
                "path" => Some(Scalar::String(node.path.as_str().into())),
                "language" => Some(Scalar::String(node.language.as_str().into())),
                _ => {
                    let field = match name {
                        "start_byte" => "start",
                        "end_byte" => "end",
                        other => other,
                    };
                    let serialized =
                        serde_json::to_value(&node.node).map_err(|e| invalid(e.to_string()))?;
                    serialized
                        .get(field)
                        .map(|v| {
                            serde_json::value::RawValue::from_string(v.to_string())
                                .map_err(|e| invalid(e.to_string()))
                                .and_then(|v| Scalar::parse(&v).map_err(Into::into))
                        })
                        .transpose()?
                }
            },
            _ => None,
        };
        Ok(match found {
            None | Some(Scalar::Null) => Value::unknown("capability_missing"),
            Some(value) => Value::Scalar(value),
        })
    }
    pub(super) fn entity_visit(
        &mut self,
        probe: &SourceProbe,
        visit: &mut dyn FnMut(&mut Self, Arc<SourceNode>) -> Result<()>,
    ) -> Result<()> {
        let graph = self.graph;
        let interruption = self.run.execution.interruption.clone();
        let mut delivered = 0u64;
        let result = graph.source_scan(probe, &mut || interruption.check(), &mut |node| {
            delivered += 1;
            self.check()?;
            visit(self, node)
        });
        self.run.out.scanned_nodes = self
            .run
            .out
            .scanned_nodes
            .saturating_add(result.as_ref().copied().unwrap_or(delivered));
        result.map(|_| ())
    }
    pub(super) fn ast_program(&mut self, unit: i64) -> Result<Option<Arc<ken_program::Program>>> {
        if let Some(p) = self.ast_programs.get(&unit) {
            return Ok(Some(p.clone()));
        }
        let program = self.graph.source_program(unit)?;
        if let Some(p) = &program {
            p.validate()?;
            if self.ast_programs.len() >= 2 {
                self.ast_programs.clear();
            }
            self.ast_programs.insert(unit, p.clone());
        }
        Ok(program)
    }
    pub(super) fn ast_visit(
        &mut self,
        selector: &str,
        parent: Option<&AstValue>,
        name: Option<&str>,
        kind: Option<&str>,
        visit: &mut dyn FnMut(&mut Self, Value) -> Result<()>,
    ) -> Result<()> {
        let mut units = vec![];
        let interruption = self.run.execution.interruption.clone();
        if let Some(parent) = parent {
            units.push(parent.unit);
        } else {
            self.graph
                .source_units(&mut || interruption.check(), &mut |unit| {
                    units.push(unit);
                    Ok(())
                })?;
        }
        for unit in units {
            self.check()?;
            let Some(program) = self.ast_program(unit)? else {
                continue;
            };
            for node in &program.nodes {
                if parent.is_some_and(|p| node.parent != Some(p.node.id))
                    || name.is_some_and(|s| node.name != s)
                    || kind.is_some_and(|s| node.kind != s)
                {
                    continue;
                }
                self.run.out.scanned_nodes = self.run.out.scanned_nodes.saturating_add(1);
                self.check()?;
                if selector != "node" && selector != node.category {
                    continue;
                }
                let scope = program
                    .scopes
                    .get(node.scope)
                    .ok_or_else(|| invalid("AST scope missing"))?;
                let value = Value::Ast(Arc::new(AstValue {
                    snapshot: self.graph.source_snapshot_id(),
                    unit,
                    node: node.clone(),
                    path: program.path.clone(),
                    language: program.language.clone(),
                    namespace: scope.namespace.clone(),
                    scope_kind: scope.kind.clone(),
                }));
                visit(self, value)?;
            }
        }
        Ok(())
    }
    pub(super) fn operation_visit(
        &mut self,
        owner: Option<&SourceNode>,
        visit: &mut dyn FnMut(&mut Self, Value) -> Result<()>,
    ) -> Result<()> {
        let graph = self.graph;
        let interruption = self.run.execution.interruption.clone();
        let probe = OperationProbe {
            owner: owner.map(|n| n.local_id.clone()),
            ..Default::default()
        };
        let mut units = vec![];
        if let Some(owner) = owner {
            units.push(owner.unit);
        } else {
            graph.source_units(&mut || interruption.check(), &mut |unit| {
                units.push(unit);
                Ok(())
            })?;
        }
        let mut operations: BTreeMap<i64, Vec<(Arc<ken_program::Operation>, String, String)>> =
            BTreeMap::new();
        let mut metadata: BTreeMap<String, (i64, String, String)> = BTreeMap::new();
        graph.operations_checked(&probe, &mut || interruption.check(), &mut |op| {
            let source = if let Some(source) = metadata.get(&op.owner) {
                source.clone()
            } else {
                let node = graph
                    .source_node(&op.owner)?
                    .ok_or_else(|| invalid("operation source owner is missing"))?;
                let source = (node.unit, node.path.clone(), node.language.clone());
                metadata.insert(op.owner.clone(), source.clone());
                source
            };
            operations
                .entry(source.0)
                .or_default()
                .push((op, source.1, source.2));
            Ok(())
        })?;
        for unit in units {
            self.check()?;
            let mut operations = operations.remove(&unit).unwrap_or_default();
            // The original operation loader defines public enumeration order;
            // BODY independently needs the producer's IR order, so sort only here.
            operations.sort_by(|(a, _, _), (b, _, _)| {
                a.start
                    .cmp(&b.start)
                    .then_with(|| b.end.cmp(&a.end))
                    .then_with(|| a.id.cmp(&b.id))
            });
            for (op, path, language) in operations {
                self.check()?;
                let execution = op
                    .attrs
                    .get("execution")
                    .map(|v| Scalar::parse(v))
                    .transpose()?
                    .and_then(|v| v.string())
                    .unwrap_or("unknown".into());
                let value = Value::Operation(Arc::new(OperationValue {
                    snapshot: graph.source_snapshot_id(),
                    local_id: op.id.clone(),
                    kind: op.kind.to_lowercase(),
                    native_kind: op.native_kind.clone(),
                    path,
                    line: op.line,
                    owner: op.owner.clone(),
                    language,
                    execution,
                }));
                visit(self, value)?;
            }
        }
        Ok(())
    }
    pub(super) fn closed_domain(&mut self, name: &str) -> Result<bool> {
        if let Some(complete) = self.domain_closed.get(name) {
            return Ok(*complete);
        }
        let mut complete = self.graph.source_coverage()?;
        if matches!(name, "CodeNode" | "Expression" | "Statement") {
            let mut units = vec![];
            let interruption = self.run.execution.interruption.clone();
            self.graph
                .source_units(&mut || interruption.check(), &mut |u| {
                    units.push(u);
                    Ok(())
                })?;
            for unit in units {
                self.check()?;
                complete &= self.ast_program(unit)?.is_some_and(|p| {
                    !p.nodes.is_empty() && !p.nodes.iter().any(|n| n.category == "opaque")
                });
            }
        }
        if matches!(name, "Parameter" | "Receiver" | "Binding") {
            let kind = if name == "Binding" {
                "STORAGE"
            } else {
                "PARAMETER"
            };
            let key = if name == "Binding" {
                "declared"
            } else {
                "receiver"
            };
            let graph = self.graph;
            let interruption = self.run.execution.interruption.clone();
            graph.source_scan(
                &SourceProbe {
                    kind: Some(kind.into()),
                    ..Default::default()
                },
                &mut || interruption.check(),
                &mut |node| {
                    if !matches!(self.properties(&node)?.get(key), Some(Scalar::Bool(_))) {
                        complete = false;
                    }
                    Ok(())
                },
            )?;
        }
        self.domain_closed.insert(name.into(), complete);
        Ok(complete)
    }
    pub(super) fn domain(
        &mut self,
        name: &str,
        candidate: Option<(&str, &Expr, &Bindings)>,
    ) -> Result<(Vec<Value>, bool)> {
        if let Some((_, members)) = self.program.enums.iter().find(|(n, _)| n == name) {
            return Ok((
                members
                    .iter()
                    .map(|member| Value::Enum {
                        r#type: name.into(),
                        name: member.clone(),
                    })
                    .collect(),
                true,
            ));
        }
        let selector = crate::capabilities::vocabulary()
            .types
            .get(name)
            .cloned()
            .ok_or_else(|| invalid(format!("unknown finite domain {name}")))?;
        let complete = self.closed_domain(name)?;
        let mut values = vec![];
        if matches!(selector.as_str(), "node" | "expression" | "statement") {
            self.ast_visit(&selector, None, None, None, &mut |_, v| {
                values.push(v);
                Ok(())
            })?;
            return Ok((values, complete));
        }
        if selector == "operation" {
            self.operation_visit(None, &mut |_, v| {
                values.push(v);
                Ok(())
            })?;
            return Ok((values, complete));
        }
        let (mut owner, mut exact_name) = (None, None);
        if !self.run.execution.options.reference
            && let Some((role, condition, bindings)) = candidate
        {
            let mut atoms = vec![condition];
            while let Some(atom) = atoms.pop() {
                if atom.kind == "binary" && atom.value == "and" {
                    atoms.extend(&atom.args);
                    continue;
                }
                if atom.kind == "call"
                    && atom.value == "owns"
                    && atom.args.len() == 2
                    && let (Some(parent), Some(child)) =
                        (atom.args[0].args.first(), atom.args[1].args.first())
                    && child.kind == "role"
                    && child.value == role
                    && parent.kind == "role"
                    && let Some(Value::Node(n)) = bindings.get(&parent.value)
                {
                    owner = Some((n.unit, n.local_id.clone()));
                }
                if atom.kind == "binary" && atom.value == "==" && atom.args.len() == 2 {
                    for (member, literal) in [
                        (&atom.args[0], &atom.args[1]),
                        (&atom.args[1], &atom.args[0]),
                    ] {
                        if member.kind == "member"
                            && member.value == "name"
                            && member
                                .args
                                .first()
                                .is_some_and(|e| e.kind == "role" && e.value == role)
                            && literal.kind == "literal"
                        {
                            exact_name = Value::literal(&literal.value)?.text();
                        }
                    }
                }
            }
        }
        for kind in &crate::capabilities::vocabulary().kinds[&selector] {
            let probe = SourceProbe {
                kind: Some(kind.clone()),
                owner: owner.clone(),
                name: exact_name.clone(),
                reference: self.run.execution.options.reference,
                ..Default::default()
            };
            self.entity_visit(&probe, &mut |runtime, node| {
                if matches!(name, "Parameter" | "Receiver") {
                    let receiver = runtime.properties(&node)?.get("receiver").cloned();
                    if receiver.as_ref().is_none_or(|v| matches!(v, Scalar::Null))
                        || receiver
                            .as_ref()
                            .is_some_and(|v| v.truthy() != (name == "Receiver"))
                    {
                        return Ok(());
                    }
                }
                if name == "Binding"
                    && !matches!(
                        runtime.properties(&node)?.get("declared"),
                        Some(Scalar::Bool(true))
                    )
                {
                    return Ok(());
                }
                values.push(Value::Node(node));
                Ok(())
            })?;
        }
        Ok((values, complete))
    }
}
