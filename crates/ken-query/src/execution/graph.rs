//! Immutable snapshot reads. Probes are indexed supersets; operators verify terms.
use super::{ExecutionError, Result};
use ken_program::{Entity, Fact, StructuralIr, value::GraphValue};
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
/// Owns snapshot membership and indexes, never per-query bindings or budgets.
pub struct MemoryGraph {
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
