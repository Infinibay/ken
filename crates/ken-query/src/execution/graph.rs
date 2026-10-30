//! Immutable snapshot reads. Probes are indexed supersets; operators verify terms.
use super::values::SourceNode;
use super::{ExecutionError, Result};
use ken_program::{Entity, Fact, Operation, StructuralIr, value::GraphValue};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct FactProbe {
    pub relation: String,
    pub subject: Option<String>,
    pub object: Option<String>,
    pub attribute: Option<(String, String)>,
}
impl FactProbe {
    pub fn relation(relation: impl Into<String>) -> Self {
        Self {
            relation: relation.into(),
            subject: None,
            object: None,
            attribute: None,
        }
    }
}
/// Streaming scan callbacks must stop and propagate an error immediately. Counts
/// are planning estimates only and must poll the host interruption scope too.
pub trait GraphRead {
    fn check_snapshot(&self) -> Result<()> {
        Ok(())
    }
    fn source_snapshot_id(&self) -> i64 {
        0
    }
    fn source_units(
        &self,
        _check: &mut dyn FnMut() -> Result<()>,
        _visit: &mut dyn FnMut(i64) -> Result<()>,
    ) -> Result<()> {
        Err(ExecutionError::Unsupported("source unit membership".into()))
    }
    fn source_node(&self, _id: &str) -> Result<Option<Arc<SourceNode>>> {
        Err(ExecutionError::Unsupported(
            "source node identity reads".into(),
        ))
    }
    /// Return physical rows considered; visit may fail early and must stop reads.
    fn source_scan(
        &self,
        _probe: &SourceProbe,
        _check: &mut dyn FnMut() -> Result<()>,
        _visit: &mut dyn FnMut(Arc<SourceNode>) -> Result<()>,
    ) -> Result<u64> {
        Err(ExecutionError::Unsupported("source node scans".into()))
    }
    fn source_properties(&self, node: &SourceNode) -> Result<BTreeMap<String, GraphValue>> {
        let mut properties = if let Some(entity) = self.entity(&node.local_id)? {
            entity
                .attrs
                .iter()
                .map(|(k, v)| Ok((k.clone(), GraphValue::parse(v)?)))
                .collect::<Result<BTreeMap<_, _>>>()?
        } else {
            BTreeMap::new()
        };
        properties.insert(
            "name".into(),
            node.name
                .as_ref()
                .map_or(GraphValue::Null, |n| GraphValue::String(n.as_str().into())),
        );
        properties.insert("path".into(), GraphValue::String(node.path.as_str().into()));
        properties.insert(
            "language".into(),
            GraphValue::String(node.language.as_str().into()),
        );
        Ok(properties)
    }
    fn source_program(&self, _unit: i64) -> Result<Option<Arc<ken_program::Program>>> {
        Ok(None)
    }
    fn source_coverage(&self) -> Result<bool> {
        Ok(false)
    }
    /// Poll while discovering candidates as well as while delivering rows.
    /// Adapters with nontrivial discovery must override this default wrapper.
    fn operations_checked(
        &self,
        probe: &OperationProbe,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        check()?;
        self.operations(probe, &mut |op| {
            check()?;
            visit(op)
        })
    }
    fn operations(
        &self,
        _probe: &OperationProbe,
        _visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        Err(ExecutionError::Unsupported("source operation reads".into()))
    }
    fn facts(
        &self,
        probe: &FactProbe,
        visit: &mut dyn FnMut(Arc<Fact>) -> Result<()>,
    ) -> Result<()>;
    fn first(&self, probe: &FactProbe) -> Result<Option<Arc<Fact>>> {
        let mut first = None;
        self.facts(probe, &mut |f| {
            if first.is_none() {
                first = Some(f);
            }
            Ok(())
        })?;
        Ok(first)
    }
    fn count(&self, probe: &FactProbe) -> Result<u64>;
    fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>>;
    fn entity_ids(&self, visit: &mut dyn FnMut(&str) -> Result<()>) -> Result<()>;
    fn capabilities(&self) -> &BTreeSet<String>;
    fn relations(&self) -> &BTreeSet<String>;
}
type Posting = BTreeMap<(String, String), Vec<usize>>;
#[derive(Clone, Debug, Default)]
pub struct OperationProbe {
    pub id: Option<String>,
    pub owner: Option<String>,
    pub kind: Option<String>,
    pub region: Option<String>,
}
#[derive(Clone, Debug, Default)]
pub struct SourceProbe {
    pub kind: Option<String>,
    pub name: Option<String>,
    pub owner: Option<(i64, String)>,
    pub node_id: Option<i64>,
    pub reference: bool,
}
impl SourceProbe {
    pub fn matches(&self, node: &SourceNode) -> bool {
        self.kind.as_ref().is_none_or(|kind| kind == &node.kind)
            && self
                .name
                .as_ref()
                .is_none_or(|name| node.name.as_ref().is_none_or(|actual| actual == name))
            && self.owner.as_ref().is_none_or(|(unit, owner)| {
                *unit == node.unit && node.owner.as_ref() == Some(owner)
            })
            && self.node_id.is_none_or(|id| id == node.id)
    }
}
/// Owns snapshot membership and indexes, never per-query bindings or budgets.
pub struct MemoryGraph {
    source_nodes: BTreeMap<String, Arc<SourceNode>>,
    source_order: Vec<String>,
    source_kinds: BTreeMap<String, Vec<String>>,
    source_owners: BTreeMap<(i64, String), Vec<String>>,
    source_names: BTreeMap<(String, String), Vec<String>>,
    source_unnamed: BTreeMap<String, Vec<String>>,
    source_ids: BTreeMap<i64, Vec<String>>,
    source_programs: BTreeMap<i64, Arc<ken_program::Program>>,
    source_metadata: BTreeMap<String, BTreeMap<String, GraphValue>>,
    source_complete: bool,
    source_snapshot: i64,
    language: String,
    operations: Vec<Arc<Operation>>,
    operation_ids: BTreeMap<String, usize>,
    operation_owners: BTreeMap<String, Vec<usize>>,
    operation_kinds: BTreeMap<String, Vec<usize>>,
    operation_children: BTreeMap<String, Vec<usize>>,
    facts: Vec<Arc<Fact>>,
    entities: BTreeMap<String, Arc<Entity>>,
    relation: BTreeMap<String, Vec<usize>>,
    subject: Posting,
    object: Posting,
    attributes: BTreeMap<(String, String, String), Vec<usize>>,
    capabilities: BTreeSet<String>,
    relations: BTreeSet<String>,
}
impl MemoryGraph {
    pub fn new(ir: &StructuralIr) -> Result<Self> {
        if ir.view != "query" || ir.version != ken_program::IR_VERSION {
            return Err(ExecutionError::Invalid(
                "execution needs an immutable query graph".into(),
            ));
        }
        let mut graph = Self {
            source_nodes: BTreeMap::new(),
            source_order: vec![],
            source_kinds: BTreeMap::new(),
            source_owners: BTreeMap::new(),
            source_names: BTreeMap::new(),
            source_unnamed: BTreeMap::new(),
            source_ids: BTreeMap::new(),
            source_programs: BTreeMap::new(),
            source_metadata: BTreeMap::new(),
            source_complete: false,
            source_snapshot: 1,
            language: ir.language.clone(),
            operations: ir.operations.iter().cloned().map(Arc::new).collect(),
            operation_ids: BTreeMap::new(),
            operation_owners: BTreeMap::new(),
            operation_kinds: BTreeMap::new(),
            operation_children: BTreeMap::new(),
            facts: vec![],
            entities: ir
                .entities
                .iter()
                .map(|(k, e)| (k.clone(), Arc::new(e.clone())))
                .collect(),
            relation: BTreeMap::new(),
            subject: BTreeMap::new(),
            object: BTreeMap::new(),
            attributes: BTreeMap::new(),
            capabilities: ir.capabilities.clone(),
            relations: ir.relations.clone(),
        };
        for (i, op) in graph.operations.iter().enumerate() {
            graph.operation_ids.insert(op.id.clone(), i);
            if let Some(parent) = &op.parent {
                graph
                    .operation_children
                    .entry(parent.clone())
                    .or_default()
                    .push(i);
            }
            graph
                .operation_owners
                .entry(op.owner.clone())
                .or_default()
                .push(i);
            graph
                .operation_kinds
                .entry(op.kind.clone())
                .or_default()
                .push(i);
        }
        for f in &ir.facts {
            let i = graph.facts.len();
            graph
                .relation
                .entry(f.relation.clone())
                .or_default()
                .push(i);
            graph
                .subject
                .entry((f.relation.clone(), f.subject.clone()))
                .or_default()
                .push(i);
            graph
                .object
                .entry((f.relation.clone(), f.object.clone()))
                .or_default()
                .push(i);
            graph.relations.insert(f.relation.clone());
            for (k, v) in &f.attrs {
                let v = GraphValue::parse(v)?;
                graph
                    .attributes
                    .entry((f.relation.clone(), k.clone(), v.comparison()))
                    .or_default()
                    .push(i);
            }
            graph.facts.push(Arc::new(f.clone()));
        }
        let mut owners = BTreeMap::new();
        for f in &ir.facts {
            if matches!(
                f.relation.as_str(),
                "DECLARES" | "HAS_PARAMETER" | "HAS_FIELD" | "HAS_METHOD"
            ) {
                owners.insert(f.object.clone(), f.subject.clone());
            }
        }
        for f in &ir.facts {
            if f.relation == "OWNED_BY" {
                owners.insert(f.subject.clone(), f.object.clone());
            }
        }
        for (i, (id, entity)) in ir.entities.iter().enumerate() {
            let language = entity
                .attrs
                .get("language")
                .map(|v| GraphValue::parse(v))
                .transpose()?
                .and_then(|v| v.string())
                .unwrap_or_else(|| ir.language.clone());
            graph.insert_source_node(SourceNode {
                id: i as i64,
                unit: 0,
                local_id: id.clone(),
                kind: entity.kind.clone(),
                name: Some(entity.name.clone()),
                owner: owners.get(id).cloned().or_else(|| {
                    entity
                        .attrs
                        .get("owner")
                        .and_then(|v| GraphValue::parse(v).ok())
                        .and_then(|v| v.string())
                }),
                line: entity.line,
                end_line: entity.end_line,
                path: entity.path.clone(),
                language,
            });
        }
        Ok(graph)
    }
    fn insert_source_node(&mut self, node: SourceNode) {
        let id = node.local_id.clone();
        if !self.source_nodes.contains_key(&id) {
            self.source_order.push(id.clone());
        }
        self.source_ids.entry(node.id).or_default().push(id.clone());
        self.source_kinds
            .entry(node.kind.clone())
            .or_default()
            .push(id.clone());
        if let Some(owner) = &node.owner {
            self.source_owners
                .entry((node.unit, owner.clone()))
                .or_default()
                .push(id.clone());
        }
        if let Some(name) = &node.name {
            self.source_names
                .entry((node.kind.clone(), name.clone()))
                .or_default()
                .push(id.clone());
        } else {
            self.source_unnamed
                .entry(node.kind.clone())
                .or_default()
                .push(id.clone());
        }
        self.source_nodes.insert(id, Arc::new(node));
    }
    /// Attach an explicitly inventoried source snapshot; query facts stay immutable.
    pub fn with_source_nodes(
        mut self,
        nodes: Vec<SourceNode>,
        properties: BTreeMap<String, BTreeMap<String, GraphValue>>,
        programs: BTreeMap<i64, Arc<ken_program::Program>>,
        complete: bool,
    ) -> Self {
        self.source_nodes.clear();
        self.source_order.clear();
        self.source_kinds.clear();
        self.source_owners.clear();
        self.source_names.clear();
        self.source_unnamed.clear();
        self.source_ids.clear();
        for node in nodes {
            self.insert_source_node(node);
        }
        self.source_metadata = properties;
        self.source_programs = programs;
        self.source_complete = complete;
        self
    }
    pub fn with_source_snapshot_id(mut self, snapshot: i64) -> Self {
        self.source_snapshot = snapshot;
        self
    }
    fn source_node_inner(
        &self,
        id: &str,
        active: &mut BTreeSet<String>,
    ) -> Result<Option<Arc<SourceNode>>> {
        if let Some(node) = self.source_nodes.get(id) {
            return Ok(Some(node.clone()));
        }
        if active.len() >= 128 || !active.insert(id.into()) {
            return Err(ExecutionError::Invalid(
                "cyclic source node ownership".into(),
            ));
        }
        let result = (|| {
            if let Some(&i) = self.operation_ids.get(id) {
                let op = &self.operations[i];
                if let Some(owner) = self.source_node_inner(&op.owner, active)? {
                    return Ok(Some(Arc::new(SourceNode {
                        id: 0,
                        unit: owner.unit,
                        local_id: id.into(),
                        kind: "OPERATION".into(),
                        name: Some(String::new()),
                        owner: Some(owner.local_id.clone()),
                        line: op.line,
                        end_line: op.line,
                        path: owner.path.clone(),
                        language: owner.language.clone(),
                    })));
                }
            }
            if let Some(rows) = self.object.get(&("INSTANCE_RECEIVER".into(), id.into())) {
                for i in rows {
                    let f = &self.facts[*i];
                    if let Some(owner) = self.source_node_inner(&f.subject, active)? {
                        return Ok(Some(Arc::new(SourceNode {
                            id: 0,
                            unit: owner.unit,
                            local_id: id.into(),
                            kind: "RECEIVER".into(),
                            name: Some("this".into()),
                            owner: Some(owner.local_id.clone()),
                            line: owner.line,
                            end_line: owner.end_line,
                            path: owner.path.clone(),
                            language: owner.language.clone(),
                        })));
                    }
                }
            }
            Ok(None)
        })();
        active.remove(id);
        result
    }
    fn bucket(&self, p: &FactProbe) -> &[usize] {
        if let Some((k, v)) = &p.attribute {
            return self
                .attributes
                .get(&(p.relation.clone(), k.clone(), v.clone()))
                .map_or(&[], Vec::as_slice);
        }
        if let Some(s) = &p.subject {
            return self
                .subject
                .get(&(p.relation.clone(), s.clone()))
                .map_or(&[], Vec::as_slice);
        }
        if let Some(o) = &p.object {
            return self
                .object
                .get(&(p.relation.clone(), o.clone()))
                .map_or(&[], Vec::as_slice);
        }
        self.relation.get(&p.relation).map_or(&[], Vec::as_slice)
    }
}
impl GraphRead for MemoryGraph {
    fn source_snapshot_id(&self) -> i64 {
        self.source_snapshot
    }
    fn source_units(
        &self,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(i64) -> Result<()>,
    ) -> Result<()> {
        check()?;
        let mut units = BTreeSet::new();
        for unit in self.source_programs.keys() {
            check()?;
            units.insert(*unit);
        }
        for node in self.source_nodes.values() {
            check()?;
            units.insert(node.unit);
        }
        for unit in units {
            check()?;
            visit(unit)?;
        }
        Ok(())
    }
    fn source_node(&self, id: &str) -> Result<Option<Arc<SourceNode>>> {
        self.source_node_inner(id, &mut BTreeSet::new())
    }
    fn source_scan(
        &self,
        p: &SourceProbe,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(Arc<SourceNode>) -> Result<()>,
    ) -> Result<u64> {
        check()?;
        let ids: Box<dyn Iterator<Item = &String> + '_> = if p.reference {
            Box::new(self.source_order.iter())
        } else if let Some(id) = p.node_id {
            Box::new(self.source_ids.get(&id).into_iter().flatten())
        } else if let (Some(kind), Some(name)) = (&p.kind, &p.name) {
            Box::new(
                self.source_names
                    .get(&(kind.clone(), name.clone()))
                    .into_iter()
                    .flatten()
                    .chain(self.source_unnamed.get(kind).into_iter().flatten()),
            )
        } else if let Some(owner) = &p.owner {
            Box::new(self.source_owners.get(owner).into_iter().flatten())
        } else if let Some(kind) = &p.kind {
            Box::new(self.source_kinds.get(kind).into_iter().flatten())
        } else {
            Box::new(self.source_order.iter())
        };
        let mut scanned = 0;
        for id in ids {
            check()?;
            scanned += 1;
            let node = &self.source_nodes[id];
            if p.matches(node) {
                visit(node.clone())?;
            }
        }
        Ok(scanned)
    }
    fn source_properties(&self, node: &SourceNode) -> Result<BTreeMap<String, GraphValue>> {
        if let Some(properties) = self.source_metadata.get(&node.local_id) {
            return Ok(properties.clone());
        }
        let mut attrs = if let Some(e) = self.entities.get(&node.local_id) {
            e.attrs
                .iter()
                .map(|(k, v)| Ok((k.clone(), GraphValue::parse(v)?)))
                .collect::<Result<BTreeMap<_, _>>>()?
        } else {
            BTreeMap::new()
        };
        attrs.insert(
            "name".into(),
            node.name
                .as_ref()
                .map_or(GraphValue::Null, |s| GraphValue::String(s.as_str().into())),
        );
        attrs.insert("path".into(), GraphValue::String(node.path.as_str().into()));
        attrs.insert(
            "language".into(),
            GraphValue::String(if node.language.is_empty() {
                self.language.as_str().into()
            } else {
                node.language.as_str().into()
            }),
        );
        Ok(attrs)
    }
    fn source_program(&self, unit: i64) -> Result<Option<Arc<ken_program::Program>>> {
        Ok(self.source_programs.get(&unit).cloned())
    }
    fn source_coverage(&self) -> Result<bool> {
        Ok(self.source_complete)
    }
    fn operations(
        &self,
        p: &OperationProbe,
        visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        self.operations_checked(p, &mut || Ok(()), visit)
    }
    fn operations_checked(
        &self,
        p: &OperationProbe,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        check()?;
        let region = if let Some(region) = &p.region {
            let mut set = BTreeSet::new();
            if let Some(root) = self.operation_ids.get(region) {
                // Keep iterators into immutable postings, not a copied queue of
                // every child. Poll before traversing each syntax candidate.
                let mut pending = vec![std::slice::from_ref(root).iter()];
                while let Some(children) = pending.last_mut() {
                    check()?;
                    if let Some(&id) = children.next() {
                        if set.insert(id)
                            && let Some(children) =
                                self.operation_children.get(&self.operations[id].id)
                        {
                            pending.push(children.iter());
                        }
                    } else {
                        pending.pop();
                    }
                }
            }
            Some(set)
        } else {
            None
        };
        let ids: Box<dyn Iterator<Item = usize> + '_> = if let Some(id) = &p.id {
            Box::new(self.operation_ids.get(id).copied().into_iter())
        } else if let Some(owner) = &p.owner {
            let owner = self
                .operation_owners
                .get(owner)
                .map_or(&[][..], Vec::as_slice);
            if let Some(region) = &region
                && region.len() < owner.len()
            {
                Box::new(region.iter().copied())
            } else {
                Box::new(owner.iter().copied())
            }
        } else if let Some(kind) = &p.kind {
            let kind = self
                .operation_kinds
                .get(kind)
                .map_or(&[][..], Vec::as_slice);
            if let Some(region) = &region
                && region.len() < kind.len()
            {
                Box::new(region.iter().copied())
            } else {
                Box::new(kind.iter().copied())
            }
        } else if let Some(region) = &region {
            Box::new(region.iter().copied())
        } else {
            Box::new(0..self.operations.len())
        };
        for i in ids {
            check()?;
            let op = &self.operations[i];
            if p.id.as_ref().is_none_or(|id| *id == op.id)
                && p.owner.as_ref().is_none_or(|owner| *owner == op.owner)
                && p.kind.as_ref().is_none_or(|kind| *kind == op.kind)
                && region.as_ref().is_none_or(|set| set.contains(&i))
            {
                visit(op.clone())?;
            }
        }
        Ok(())
    }
    fn facts(&self, p: &FactProbe, visit: &mut dyn FnMut(Arc<Fact>) -> Result<()>) -> Result<()> {
        for &i in self.bucket(p) {
            visit(self.facts[i].clone())?;
        }
        Ok(())
    }
    fn first(&self, p: &FactProbe) -> Result<Option<Arc<Fact>>> {
        Ok(self.bucket(p).first().map(|&i| self.facts[i].clone()))
    }
    fn count(&self, p: &FactProbe) -> Result<u64> {
        Ok(self.bucket(p).len() as u64)
    }
    fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>> {
        Ok(self.entities.get(id).cloned())
    }
    fn entity_ids(&self, visit: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        for k in self.entities.keys() {
            visit(k)?;
        }
        Ok(())
    }
    fn capabilities(&self) -> &BTreeSet<String> {
        &self.capabilities
    }
    fn relations(&self) -> &BTreeSet<String> {
        &self.relations
    }
}
