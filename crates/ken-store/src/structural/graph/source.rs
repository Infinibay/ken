//! Owner-scoped source views and indexed coverage for BODY consumers.
use super::{EntityFilter, FactFilter, GraphIndex, OperationFilter, Result, StructuralError};
use crate::structural::StoredNode;
use ken_program::{
    Attributes, Entity, Operation, control::supports_general_walk, value::GraphValue as V,
};
use rusqlite::{OptionalExtension, params, types::Value as Sql};
use std::collections::{BTreeMap, BTreeSet};
type EntityColumns = (i64, i64, String, Option<i64>, i64, i64, i64, i64);
#[derive(Debug, PartialEq, Eq)]
pub struct SourceCoverage {
    pub universe: BTreeSet<String>,
    pub covered: BTreeSet<String>,
    pub uncovered: BTreeSet<String>,
}
impl GraphIndex<'_> {
    pub fn source_view(&self) -> GraphSourceView<'_, '_> {
        GraphSourceView { index: self }
    }
    pub fn operation_owners(&self, kinds: &BTreeSet<String>) -> Result<BTreeSet<String>> {
        self.store.renew_reader()?;
        let mut owners = BTreeSet::new();
        let terms = kinds
            .iter()
            .map(|s| self.values().lookup(s))
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .flatten()
            .collect::<Vec<_>>();
        for batch in terms.chunks(512) {
            let mut args = vec![Sql::Integer(self.graph)];
            args.extend(batch.iter().copied().map(Sql::Integer));
            let sql = format!(
                "SELECT DISTINCT t.text FROM k2_graph_operations o INDEXED BY k2_graph_operation_kind JOIN k2_graph_terms t ON t.graph_id=o.graph_id AND t.term_id=o.owner WHERE o.graph_id=? AND o.kind IN ({})",
                vec!["?"; batch.len()].join(",")
            );
            for owner in self
                .store
                .connection()
                .prepare(&sql)?
                .query_map(rusqlite::params_from_iter(args), |r| r.get::<_, String>(0))?
            {
                owners.insert(owner?);
            }
        }
        Ok(owners)
    }
    pub fn call_witnesses(
        &self,
        names: &BTreeSet<String>,
    ) -> Result<(BTreeSet<String>, BTreeSet<String>)> {
        self.store.renew_reader()?;
        let Some(call) = self.values().lookup("CALL")?.filter(|_| !names.is_empty()) else {
            return Ok((BTreeSet::new(), BTreeSet::new()));
        };
        let mut witnesses = BTreeSet::new();
        let names = names.iter().collect::<Vec<_>>();
        for batch in names.chunks(512) {
            let mut args = vec![Sql::Integer(self.graph), Sql::Integer(call)];
            args.extend(batch.iter().map(|s| Sql::Text((*s).clone())));
            let sql = format!(
                "SELECT DISTINCT t.text FROM k2_graph_entities e JOIN k2_graph_terms t ON t.graph_id=e.graph_id AND t.term_id=e.owner WHERE e.graph_id=? AND e.kind=? AND e.name IN ({})",
                vec!["?"; batch.len()].join(",")
            );
            for owner in self
                .store
                .connection()
                .prepare(&sql)?
                .query_map(rusqlite::params_from_iter(args), |r| r.get::<_, String>(0))?
            {
                witnesses.insert(owner?);
            }
        }
        let mut missing:BTreeSet<String>=self.store.connection().prepare("SELECT DISTINCT t.text FROM k2_graph_operations o JOIN k2_graph_terms t ON t.graph_id=o.graph_id AND t.term_id=o.owner WHERE o.graph_id=?1 AND o.kind=?2 AND NOT EXISTS(SELECT 1 FROM k2_graph_entities e WHERE e.graph_id=o.graph_id AND e.kind=?2 AND e.owner=o.owner AND e.start_byte IS o.start_byte AND e.end_byte IS o.end_byte)")?.query_map(params![self.graph,call],|r|r.get(0))?.collect::<rusqlite::Result<_>>()?;
        for owner in self.store.connection().prepare("SELECT DISTINCT t.text FROM k2_graph_entities e JOIN k2_graph_terms t ON t.graph_id=e.graph_id AND t.term_id=e.owner WHERE e.graph_id=?1 AND e.kind=?2 AND e.name=''")?.query_map(params![self.graph,call],|r|r.get::<_,String>(0))?{missing.insert(owner?);}
        Ok((witnesses, missing))
    }
    pub fn source_coverage(&self, general: bool) -> Result<SourceCoverage> {
        self.store.renew_reader()?;
        let mut universe = BTreeSet::new();
        let v = self.values();
        if let (Some(entity), Some(callable)) = (v.lookup("ENTITY")?, v.lookup("CALLABLE")?) {
            universe=self.store.connection().prepare("SELECT DISTINCT t.text FROM k2_graph_facts f INDEXED BY k2_graph_fact_reverse JOIN k2_graph_terms t ON t.graph_id=f.graph_id AND t.term_id=f.subject WHERE f.graph_id=?1 AND f.relation=?2 AND f.object=?3")?.query_map(params![self.graph,entity,callable],|r|r.get(0))?.collect::<rusqlite::Result<_>>()?;
        }
        let mut covered = BTreeSet::new();
        if let (Some(status), Some(structured), Some(entry)) = (
            v.lookup("CFG_STATUS")?,
            v.lookup("structured")?,
            v.lookup("CFG_ENTRY")?,
        ) {
            covered=self.store.connection().prepare("SELECT DISTINCT t.text FROM k2_graph_facts f INDEXED BY k2_graph_fact_reverse JOIN k2_graph_terms t ON t.graph_id=f.graph_id AND t.term_id=f.subject WHERE f.graph_id=?1 AND f.relation=?2 AND f.object=?3 AND EXISTS(SELECT 1 FROM k2_graph_entities e WHERE e.graph_id=f.graph_id AND e.local_id=f.subject) AND EXISTS(SELECT 1 FROM k2_graph_facts e INDEXED BY k2_graph_fact_forward WHERE e.graph_id=f.graph_id AND e.relation=?4 AND e.subject=f.subject) AND NOT EXISTS(SELECT 1 FROM k2_graph_facts s INDEXED BY k2_graph_fact_forward WHERE s.graph_id=f.graph_id AND s.relation=?2 AND s.subject=f.subject AND s.object!=?3)")?.query_map(params![self.graph,status,structured,entry],|r|r.get(0))?.collect::<rusqlite::Result<_>>()?;
        }
        if general {
            let filter = FactFilter {
                object: Some("partial".into()),
                ..FactFilter::relation("CFG_STATUS")
            };
            let partial = self
                .facts(&filter)?
                .rows()?
                .map(|f| f.map(|f| f.subject))
                .collect::<Result<BTreeSet<_>>>()?;
            for owner in partial {
                if covered.contains(&owner) {
                    continue;
                }
                if self
                    .entities(&EntityFilter {
                        local_id: Some(owner.clone()),
                        ..Default::default()
                    })?
                    .rows()?
                    .next()
                    .transpose()?
                    .is_none()
                {
                    continue;
                }
                if !self.exists(&FactFilter {
                    subject: Some(owner.clone()),
                    ..FactFilter::relation("CFG_ENTRY")
                })? {
                    continue;
                }
                let statuses = self
                    .facts(&FactFilter {
                        subject: Some(owner.clone()),
                        ..FactFilter::relation("CFG_STATUS")
                    })?
                    .rows()?
                    .collect::<Result<Vec<_>>>()?;
                if supports_general_walk(&statuses)? {
                    covered.insert(owner);
                }
            }
        }
        let uncovered = universe.difference(&covered).cloned().collect();
        Ok(SourceCoverage {
            universe,
            covered,
            uncovered,
        })
    }
}
pub struct GraphSourceView<'a, 'b> {
    index: &'a GraphIndex<'b>,
}
impl GraphSourceView<'_, '_> {
    pub fn operation(&self, id: &str) -> Result<Option<Operation>> {
        self.index
            .operations(&OperationFilter {
                local_id: Some(id.into()),
                ..Default::default()
            })?
            .rows()?
            .next()
            .transpose()
    }
    pub fn node(&self, id: &str) -> Result<Option<StoredNode>> {
        self.node_inner(id, &mut BTreeSet::new())
    }
    fn node_inner(&self, id: &str, visited: &mut BTreeSet<String>) -> Result<Option<StoredNode>> {
        self.index.store.renew_reader()?;
        if visited.len() > 256 || !visited.insert(id.into()) {
            return Err(StructuralError::Invalid(
                "cyclic or excessively nested source ownership",
            ));
        }
        let result = self.resolve_node(id, visited);
        visited.remove(id);
        result
    }
    fn resolve_node(&self, id: &str, visited: &mut BTreeSet<String>) -> Result<Option<StoredNode>> {
        let v = self.index.values();
        let Some(term) = v.lookup(id)? else {
            return Ok(None);
        };
        let row:Option<EntityColumns>=v.db.query_row("SELECT ordinal,kind,name,source_owner,line,end_line,path,attributes FROM k2_graph_entities WHERE graph_id=?1 AND local_id=?2",params![v.graph,term],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?,r.get(6)?,r.get(7)?))).optional()?;
        if let Some((ordinal, kind, name, owner, line, end_line, path, attrs)) = row {
            let language =
                v.member(attrs, "language")?
                    .map_or(Ok(self.index.language.clone()), |value| {
                        value
                            .string()
                            .ok_or(StructuralError::Invalid("node language must be a string"))
                    })?;
            return Ok(Some(StoredNode {
                id: ordinal,
                unit: 0,
                local_id: id.into(),
                kind: v.word(kind)?,
                name: Some(name),
                owner: owner.map(|id| v.word(id)).transpose()?,
                line,
                end_line,
                path: v.word(path)?,
                language,
            }));
        }
        if let Some(op) = self.operation(id)?
            && let Some(owner) = self.node_inner(&op.owner, visited)?
        {
            return Ok(Some(StoredNode {
                id: 0,
                unit: owner.unit,
                local_id: id.into(),
                kind: "OPERATION".into(),
                name: Some(String::new()),
                owner: Some(owner.local_id),
                line: op.line,
                end_line: op.line,
                path: owner.path,
                language: owner.language,
            }));
        }
        for fact in self
            .index
            .facts(&FactFilter {
                object: Some(id.into()),
                ..FactFilter::relation("INSTANCE_RECEIVER")
            })?
            .rows()?
        {
            let fact = fact?;
            if let Some(owner) = self.node_inner(&fact.subject, visited)? {
                return Ok(Some(StoredNode {
                    id: 0,
                    unit: owner.unit,
                    local_id: id.into(),
                    kind: "RECEIVER".into(),
                    name: Some("this".into()),
                    owner: Some(owner.local_id),
                    line: owner.line,
                    end_line: owner.end_line,
                    path: owner.path,
                    language: owner.language,
                }));
            }
        }
        Ok(None)
    }
    pub fn owner_nodes(&self, owner: &str) -> Result<Vec<StoredNode>> {
        self.index
            .entities(&EntityFilter {
                source_owner: Some(owner.into()),
                ..Default::default()
            })?
            .rows()?
            .map(|e| {
                self.node(&e?.id)?
                    .ok_or(StructuralError::Invalid("missing source entity node"))
            })
            .collect()
    }
    pub fn owner_entities(&self, owner: &str) -> Result<Vec<Entity>> {
        let mut entities = self
            .index
            .entities(&EntityFilter {
                source_owner: Some(owner.into()),
                ..Default::default()
            })?
            .rows()?
            .collect::<Result<Vec<_>>>()?;
        let mut positions: BTreeMap<String, usize> = entities
            .iter()
            .enumerate()
            .map(|(i, e)| (e.id.clone(), i))
            .collect();
        let mut subjects = entities.clone();
        let mut subject_positions = positions.clone();
        for e in self
            .index
            .entities(&EntityFilter {
                owner: Some(owner.into()),
                ..Default::default()
            })?
            .rows()?
        {
            put_entity(&mut subjects, &mut subject_positions, e?);
        }
        for subject in subjects {
            let actual_owner = if let Some(value) = subject.attrs.get("owner") {
                V::parse(value)?.string()
            } else {
                self.node(&subject.id)?.and_then(|n| n.owner)
            };
            if actual_owner.as_deref() != Some(owner) {
                continue;
            }
            for relation in ["ARGUMENT", "ASSIGNMENT_VALUE", "RETURN_OPERAND", "OPERAND"] {
                for fact in self
                    .index
                    .facts(&FactFilter {
                        subject: Some(subject.id.clone()),
                        ..FactFilter::relation(relation)
                    })?
                    .rows()?
                {
                    for value in self
                        .index
                        .facts(&FactFilter {
                            subject: Some(fact?.object),
                            ..FactFilter::relation("VALUE")
                        })?
                        .rows()?
                    {
                        if let Some(entity) = self
                            .index
                            .entities(&EntityFilter {
                                local_id: Some(value?.object),
                                ..Default::default()
                            })?
                            .rows()?
                            .next()
                            .transpose()?
                        {
                            put_entity(&mut entities, &mut positions, entity);
                        }
                    }
                }
            }
        }
        Ok(entities)
    }
    pub fn properties(&self, node: &StoredNode) -> Result<Attributes> {
        let entity = self
            .index
            .entities(&EntityFilter {
                local_id: Some(node.local_id.clone()),
                ..Default::default()
            })?
            .rows()?
            .next()
            .transpose()?;
        let mut attrs = entity.map_or_else(Attributes::new, |e| e.attrs);
        for (k, v) in [
            ("name", node.name.as_deref()),
            ("path", Some(node.path.as_str())),
            ("language", Some(node.language.as_str())),
        ] {
            attrs.insert(k.into(), serde_json::value::to_raw_value(&v)?);
        }
        Ok(attrs)
    }
}
fn put_entity(entities: &mut Vec<Entity>, positions: &mut BTreeMap<String, usize>, entity: Entity) {
    if let Some(&i) = positions.get(&entity.id) {
        entities[i] = entity;
    } else {
        positions.insert(entity.id.clone(), entities.len());
        entities.push(entity);
    }
}
