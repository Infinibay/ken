//! Immutable snapshot reads. Probes are indexed supersets; operators verify terms.
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
/// Owns snapshot membership and indexes, never per-query bindings or budgets.
pub struct MemoryGraph {
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
        Ok(graph)
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
