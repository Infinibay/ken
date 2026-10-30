//! Source operation lowering owns evaluation order and records unsupported semantics.
mod expressions;
mod statements;
use super::{Function, Instruction, Operand, Place, Program, Region, Result};
use crate::{Entity, Operation, ProgramError, StructuralIr};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
fn text(node: &Operation, key: &str) -> String {
    node.attrs
        .get(key)
        .and_then(|v| serde_json::from_str::<String>(v.get()).ok())
        .unwrap_or_default()
}
fn tokens(node: &Operation) -> Vec<String> {
    node.attrs
        .get("tokens")
        .and_then(|v| serde_json::from_str(v.get()).ok())
        .unwrap_or_default()
}
fn identifier(node: &Operation) -> bool {
    matches!(node.native_kind.as_str(), "identifier" | "this" | "self")
}
fn block(node: &Operation) -> bool {
    matches!(
        node.native_kind.as_str(),
        "block"
            | "statement_block"
            | "compound_statement"
            | "statement_list"
            | "else_clause"
            | "constructor_body"
    )
}
fn wrapper(node: &Operation) -> bool {
    matches!(
        node.native_kind.as_str(),
        "expression_statement"
            | "parenthesized_expression"
            | "argument"
            | "expression_list"
            | "bracketed_argument_list"
    )
}
struct Source<'a> {
    graph: &'a StructuralIr,
    children: BTreeMap<String, Vec<usize>>,
    owners: BTreeMap<String, Vec<usize>>,
    symbols: BTreeMap<String, BTreeMap<String, &'a Entity>>,
    parameters: BTreeMap<String, Vec<&'a Entity>>,
    operators: BTreeMap<String, Vec<String>>,
    optional: BTreeSet<String>,
}
impl<'a> Source<'a> {
    fn new(graph: &'a StructuralIr) -> Self {
        let mut source = Self {
            graph,
            children: BTreeMap::new(),
            owners: BTreeMap::new(),
            symbols: BTreeMap::new(),
            parameters: BTreeMap::new(),
            operators: BTreeMap::new(),
            optional: BTreeSet::new(),
        };
        let entities = graph
            .entities
            .iter()
            .map(|(id, e)| (id.as_str(), e))
            .collect::<BTreeMap<_, _>>();
        let parents = graph
            .operations
            .iter()
            .map(|op| (op.id.as_str(), op.parent.as_deref()))
            .collect::<BTreeMap<_, _>>();
        for (index, op) in graph.operations.iter().enumerate() {
            if op.native_kind == "optional_chain" || tokens(op).iter().any(|t| t == "?.") {
                let mut current = Some(op.id.as_str());
                while let Some(id) = current {
                    if !source.optional.insert(id.into()) {
                        break;
                    }
                    current = parents.get(id).copied().flatten();
                }
            }
            source
                .owners
                .entry(op.owner.clone())
                .or_default()
                .push(index);
            if let Some(parent) = &op.parent
                && !op.native_kind.contains("comment")
            {
                source
                    .children
                    .entry(parent.clone())
                    .or_default()
                    .push(index);
            }
        }
        for (_, entity) in &graph.entities {
            if matches!(entity.kind.as_str(), "PARAMETER" | "STORAGE")
                && let Some((owner, _)) = entity.id.rsplit_once('/')
            {
                source
                    .symbols
                    .entry(owner.into())
                    .or_default()
                    .insert(entity.name.clone(), entity);
            }
        }
        for fact in &graph.facts {
            match fact.relation.as_str() {
                "HAS_PARAMETER" => {
                    if let Some(parameter) = entities.get(fact.object.as_str()) {
                        source
                            .parameters
                            .entry(fact.subject.clone())
                            .or_default()
                            .push(parameter);
                    }
                }
                "OPERATOR" => source
                    .operators
                    .entry(fact.subject.clone())
                    .or_default()
                    .push(fact.object.clone()),
                _ => {}
            }
        }
        for children in source.children.values_mut() {
            children.sort_by(|&a, &b| {
                let (a, b) = (&graph.operations[a], &graph.operations[b]);
                (a.start, a.end, &a.id).cmp(&(b.start, b.end, &b.id))
            });
        }
        source
    }
}
struct Lowering<'a, 'g> {
    source: &'a Source<'g>,
    entity: &'g Entity,
    function: Function,
    counter: usize,
    active: usize,
    reasons: BTreeSet<String>,
}
impl<'a, 'g> Lowering<'a, 'g> {
    fn new(source: &'a Source<'g>, entity: &'g Entity) -> Result<Self> {
        let language = entity
            .attrs
            .get("language")
            .and_then(|v| serde_json::from_str::<String>(v.get()).ok())
            .ok_or(ProgramError::Invalid(
                "instruction callable requires a source language",
            ))?;
        let mut lowering = Self {
            source,
            entity,
            function: Function {
                id: entity.id.clone(),
                name: entity.name.clone(),
                language,
                parameters: Vec::new(),
                places: Vec::new(),
                body: Region::new(format!("{}/entry", entity.id), "entry"),
                status: "partial".into(),
                reasons: Vec::new(),
            },
            counter: 0,
            active: 0,
            reasons: BTreeSet::new(),
        };
        for param in source.parameters.get(&entity.id).into_iter().flatten() {
            let id = lowering.place(&param.name);
            lowering.function.parameters.push(id);
        }
        if !source.graph.diagnostics.is_empty() {
            lowering.reasons.insert("source-diagnostics".into());
        }
        Ok(lowering)
    }
    fn node(&self, index: usize) -> &'g Operation {
        &self.source.graph.operations[index]
    }
    fn children(&self, node: &Operation) -> Vec<usize> {
        self.source
            .children
            .get(&node.id)
            .cloned()
            .unwrap_or_default()
    }
    fn field(&self, node: &Operation, roles: &[&str]) -> Option<usize> {
        let children = self.children(node);
        roles.iter().find_map(|role| {
            children
                .iter()
                .copied()
                .find(|&i| self.node(i).role == *role)
        })
    }
    fn place(&mut self, name: &str) -> String {
        let id = format!("{}/slot/{name}", self.entity.id);
        if !self.function.places.iter().any(|(key, _)| key == &id) {
            let symbol = self
                .source
                .symbols
                .get(&self.entity.id)
                .and_then(|symbols| symbols.get(name))
                .copied();
            let native = symbol
                .and_then(|s| s.attrs.get("native_type"))
                .and_then(|v| serde_json::from_str::<String>(v.get()).ok())
                .unwrap_or_default();
            let data_type =
                serde_json::to_value(crate::parse_type(&native, &self.function.language))
                    .expect("native type descriptor");
            self.function.places.push((
                id.clone(),
                Place {
                    name: name.into(),
                    data_type,
                    source_symbol: symbol.map(|s| s.id.clone()),
                    scope: if symbol.is_some() {
                        "function"
                    } else {
                        "unresolved"
                    }
                    .into(),
                },
            ));
            if symbol.is_none() {
                self.reasons.insert(format!("unresolved-binding:{name}"));
            }
        }
        id
    }
    #[allow(clippy::too_many_arguments)]
    fn emit(
        &mut self,
        region: &mut Region,
        node: &Operation,
        opcode: &str,
        operands: Vec<Operand>,
        value: bool,
        effects: &[&str],
        regions: Vec<Region>,
        attrs: Value,
    ) -> Option<Operand> {
        let id = format!("{}/instruction/{}", self.entity.id, self.counter);
        self.counter += 1;
        let output = value.then(|| format!("{id}/value"));
        let result_type = match opcode {
            "slot.load" => self
                .function
                .places
                .iter()
                .find(|(id, _)| id == &operands[0].r#ref)
                .expect("admitted place")
                .1
                .data_type
                .clone(),
            "field.addr" | "index.addr" => json!({"kind":"address","native":""}),
            "const" => {
                let native = attrs["native_kind"].as_str().unwrap_or(&node.native_kind);
                let kind = if matches!(native, "true" | "false" | "boolean_literal") {
                    "bool"
                } else if matches!(native, "null" | "none" | "null_literal") {
                    "null"
                } else if native.contains("float") || native == "real_literal" {
                    "float"
                } else if native == "number" {
                    "number"
                } else if native.contains("int") {
                    "int"
                } else {
                    "unknown"
                };
                json!({"kind":kind,"native":native})
            }
            _ => json!({"kind":"unknown","native":""}),
        };
        region.instructions.push(Instruction{id,opcode:opcode.into(),operands,result:output.clone(),source:json!({"path":self.entity.path,"start":node.start,"end":node.end,"line":node.line,"operation":node.id}),effects:effects.iter().map(|s|(*s).into()).collect(),attrs,regions,result_type});
        output.map(|id| Operand::new("value", id))
    }
    fn opaque(&mut self, node: &Operation, region: &mut Region, reason: &str) -> Operand {
        self.reasons
            .insert(format!("{reason}:{}", node.native_kind));
        self.emit(
            region,
            node,
            "native",
            vec![],
            true,
            &["unknown"],
            vec![],
            json!({"native_kind":node.native_kind,"source_operation":node.id,"reason":reason}),
        )
        .expect("native value")
    }
    fn region(&mut self, node: &Operation, kind: &str) -> Region {
        let mut region = Region::new(format!("{}/region/{kind}", node.id), kind);
        self.statement(node, &mut region, 0);
        region
    }
    fn value_region(&mut self, node: &Operation, kind: &str, depth: usize) -> Region {
        let mut region = Region::new(format!("{}/region/{kind}", node.id), kind);
        let value = self.expression(node, &mut region, depth);
        region.outputs = vec![value.r#ref];
        region
    }
    fn finish(mut self) -> Function {
        let owned = self
            .source
            .owners
            .get(&self.entity.id)
            .cloned()
            .unwrap_or_default();
        let declarations = owned
            .iter()
            .filter(|&&i| self.node(i).kind == "FUNCTION")
            .map(|&i| self.node(i).id.as_str())
            .collect::<BTreeSet<_>>();
        let mut body = Region::new(format!("{}/entry", self.entity.id), "entry");
        for &i in &owned {
            let node = self.node(i);
            if node
                .parent
                .as_deref()
                .is_some_and(|id| declarations.contains(id))
                && matches!(
                    node.native_kind.as_str(),
                    "field_initializer_list" | "constructor_initializer"
                )
            {
                self.opaque(node, &mut body, "constructor-initialization");
            }
        }
        let bodies = owned
            .iter()
            .copied()
            .filter(|&i| {
                let op = self.node(i);
                op.role == "body"
                    && op
                        .parent
                        .as_deref()
                        .is_some_and(|id| declarations.contains(id))
            })
            .collect::<Vec<_>>();
        if bodies.len() == 1 {
            let node = self.node(bodies[0]);
            let children = self.children(node);
            if !block(node) {
                let value = self.expression(node, &mut body, 0);
                self.emit(
                    &mut body,
                    node,
                    "return",
                    vec![value],
                    false,
                    &[],
                    vec![],
                    json!({"implicit":true}),
                );
            } else if self.function.language == "rust"
                && !children.is_empty()
                && !matches!(
                    self.node(*children.last().unwrap()).native_kind.as_str(),
                    "expression_statement" | "let_declaration" | "return_expression"
                )
            {
                for &i in &children[..children.len() - 1] {
                    self.statement(self.node(i), &mut body, 0);
                }
                let tail = self.node(*children.last().unwrap());
                if tail.kind == "LOOP" {
                    self.statement(tail, &mut body, 0);
                } else {
                    let value = self.expression(tail, &mut body, 0);
                    self.emit(
                        &mut body,
                        tail,
                        "return",
                        vec![value],
                        false,
                        &[],
                        vec![],
                        json!({"implicit":true}),
                    );
                }
            } else {
                self.statement(node, &mut body, 0);
            }
        } else {
            self.reasons.insert("missing-or-ambiguous-body".into());
        }
        self.function.body = body;
        self.function.reasons = self.reasons.into_iter().collect();
        self.function.status = if self.function.reasons.is_empty() {
            "lowered"
        } else {
            "partial"
        }
        .into();
        self.function
    }
}
pub fn lower(graph: &StructuralIr) -> Result<Program> {
    if graph.view != "source" {
        return Err(ProgramError::Invalid(
            "instruction lowering requires the source IR view",
        ));
    }
    let source = Source::new(graph);
    let mut entities = graph
        .entities
        .iter()
        .map(|(_, e)| e)
        .filter(|e| e.kind == "CALLABLE")
        .collect::<Vec<_>>();
    entities.sort_by(|a, b| a.id.cmp(&b.id));
    let functions = entities
        .into_iter()
        .map(|e| Lowering::new(&source, e).map(Lowering::finish))
        .collect::<Result<Vec<_>>>()?;
    let program = Program {
        source_version: graph.version.clone(),
        functions,
        schema: "ken-instructions/1".into(),
    };
    program.verify()?;
    Ok(program)
}
