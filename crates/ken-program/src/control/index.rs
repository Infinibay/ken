use crate::{Entity, Operation, ProgramError, StructuralIr};
use std::collections::BTreeMap;
pub(super) struct Context<'a> {
    pub graph: &'a StructuralIr,
    pub ids: BTreeMap<&'a str, usize>,
    pub entities: BTreeMap<&'a str, &'a Entity>,
    same: Vec<Vec<usize>>,
    all: Vec<Vec<usize>>,
    pub owners: BTreeMap<&'a str, Vec<usize>>,
}
impl<'a> Context<'a> {
    pub fn new(graph: &'a StructuralIr) -> Self {
        let ids = graph
            .operations
            .iter()
            .enumerate()
            .map(|(i, o)| (o.id.as_str(), i))
            .collect::<BTreeMap<_, _>>();
        let entities = graph
            .entities
            .iter()
            .map(|(id, e)| (id.as_str(), e))
            .collect();
        let mut all = vec![Vec::new(); graph.operations.len()];
        let mut same = all.clone();
        let mut owners = BTreeMap::<&str, Vec<usize>>::new();
        for (i, op) in graph.operations.iter().enumerate() {
            owners.entry(&op.owner).or_default().push(i);
            if let Some(&parent) = op.parent.as_deref().and_then(|p| ids.get(p)) {
                all[parent].push(i);
                if graph.operations[parent].owner == op.owner {
                    same[parent].push(i);
                }
            }
        }
        for children in &mut same {
            children.sort_by_key(|&i| graph.operations[i].start);
        }
        for children in &mut all {
            children.sort_by_key(|&i| (graph.operations[i].start, graph.operations[i].end));
        }
        Self {
            graph,
            ids,
            entities,
            same,
            all,
            owners,
        }
    }
    pub fn op(&self, i: usize) -> &'a Operation {
        &self.graph.operations[i]
    }
    pub fn parent(&self, i: usize) -> Option<usize> {
        self.op(i)
            .parent
            .as_deref()
            .and_then(|p| self.ids.get(p))
            .copied()
    }
    pub fn kids(&self, i: usize) -> &[usize] {
        &self.same[self.ids[self.op(i).id.as_str()]]
    }
    pub fn all_kids(&self, i: usize) -> &[usize] {
        &self.all[self.ids[self.op(i).id.as_str()]]
    }
    pub fn entity(&self, owner: &str) -> Result<&'a Entity, ProgramError> {
        self.entities
            .get(owner)
            .copied()
            .ok_or(ProgramError::Invalid("unknown structural control owner"))
    }
}
