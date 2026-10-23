//! Branch-specific syntactic bodies preserve preorder subtree intervals.
use crate::Program;
use serde::{Serialize, Serializer, ser::SerializeStruct};
use std::collections::BTreeSet;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BodyRange {
    pub owner: usize,
    pub relation: String,
    pub root: usize,
    pub subtree_end: usize,
}
impl BodyRange {
    pub fn final_node(&self) -> usize {
        self.subtree_end - 1
    }
}
impl Serialize for BodyRange {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut value = serializer.serialize_struct("BodyRange", 5)?;
        value.serialize_field("owner", &self.owner)?;
        value.serialize_field("relation", &self.relation)?;
        value.serialize_field("root", &self.root)?;
        value.serialize_field("subtree_end", &self.subtree_end)?;
        value.serialize_field("final_node", &self.final_node())?;
        value.end()
    }
}
pub fn body_ranges(program: &Program) -> Vec<BodyRange> {
    let mut roots = BTreeSet::new();
    for node in &program.nodes {
        if let Some(parent) = node.parent
            && matches!(
                node.role.as_str(),
                "body" | "then" | "else" | "handler" | "finalizer"
            )
        {
            roots.insert((
                parent,
                if node.role == "then" {
                    "body".into()
                } else {
                    node.role.clone()
                },
                node.id,
            ));
        }
    }
    for link in &program.links {
        if matches!(link.relation.as_str(), "body" | "else") {
            roots.insert((link.source, link.relation.clone(), link.target));
        }
    }
    let explicit: BTreeSet<_> = roots
        .iter()
        .filter(|(_, r, _)| r == "body")
        .map(|(owner, _, _)| *owner)
        .collect();
    for node in &program.nodes {
        if matches!(node.kind.as_str(), "module" | "block") && !explicit.contains(&node.id) {
            roots.insert((node.id, "body".into(), node.id));
        }
    }
    roots
        .into_iter()
        .map(|(owner, relation, root)| BodyRange {
            owner,
            relation,
            root,
            subtree_end: program.nodes[root].subtree_end,
        })
        .collect()
}
