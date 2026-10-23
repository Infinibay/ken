//! Complete requested units and description reuse owned by one source catalog.
use crate::{
    EntityKey, Result, RetrievalError,
    description::{OwnerDescription, describe_owner},
    model::evidence_matches,
    query::CodeMatch,
    source_catalog::{PieceIdentity, SourceCatalog},
};
use serde::{Serialize, Serializer, ser::SerializeSeq};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn serialize_members<S: Serializer>(
    members: &[Arc<OwnerDescription>],
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    let mut sequence = serializer.serialize_seq(Some(members.len()))?;
    for member in members {
        sequence.serialize_element(member.as_ref())?;
    }
    sequence.end()
}
#[derive(Clone, Debug, Serialize)]
pub struct PieceCandidate {
    kind: String,
    path: String,
    entity: Option<EntityKey>,
    #[serde(serialize_with = "serialize_members")]
    members: Vec<Arc<OwnerDescription>>,
    matches: Vec<CodeMatch>,
}
impl PieceCandidate {
    pub fn new(
        kind: String,
        path: String,
        entity: Option<EntityKey>,
        members: Vec<Arc<OwnerDescription>>,
        matches: Vec<CodeMatch>,
    ) -> Result<Self> {
        if !matches!(kind.as_str(), "class" | "module" | "symbol" | "file")
            || members.is_empty()
            || matches.is_empty()
        {
            return Err(invalid(
                "requested piece requires members and retrieved evidence",
            ));
        }
        if matches!(kind.as_str(), "class" | "symbol") != entity.is_some() {
            return Err(invalid("requested piece identity disagrees with its kind"));
        }
        let keys: HashSet<_> = members.iter().map(|m| &m.entity).collect();
        if keys.len() != members.len() || members.iter().any(|m| m.entity.path != path) {
            return Err(invalid("piece member identity differs"));
        }
        let source_hash = &members[0].source_hash;
        if members.iter().any(|m| m.source_hash != *source_hash) {
            return Err(invalid("piece member source versions differ"));
        }
        if let Some(entity) = &entity {
            let prefix = format!("{}.", entity.qualname.as_deref().unwrap_or(""));
            if !keys.contains(entity)
                || keys.iter().any(|key| {
                    *key != entity
                        && (kind != "class"
                            || !key.qualname.as_deref().unwrap_or("").starts_with(&prefix))
                })
            {
                return Err(invalid("piece member lies outside requested entity"));
            }
        }
        if members
            .iter()
            .any(|m| !evidence_matches(&m.entity, &m.source_hash, &m.passages))
        {
            return Err(invalid("piece member evidence is invalid"));
        }
        if matches.iter().any(|m| {
            !keys.contains(&m.entity)
                || m.source_hash != *source_hash
                || !evidence_matches(&m.entity, &m.source_hash, &m.evidence)
        }) {
            return Err(invalid("retrieved member is outside the piece source"));
        }
        Ok(Self {
            kind,
            path,
            entity,
            members,
            matches,
        })
    }
    pub fn kind(&self) -> &str {
        &self.kind
    }
    pub fn path(&self) -> &str {
        &self.path
    }
    pub fn entity(&self) -> Option<&EntityKey> {
        self.entity.as_ref()
    }
    pub fn members(&self) -> &[Arc<OwnerDescription>] {
        &self.members
    }
    pub fn matches(&self) -> &[CodeMatch] {
        &self.matches
    }
    pub fn declaration(&self) -> Option<&OwnerDescription> {
        self.members
            .iter()
            .find(|m| {
                self.entity.as_ref() == Some(&m.entity)
                    || self.entity.is_none() && m.entity.qualname.is_none()
            })
            .map(Arc::as_ref)
    }
}
pub struct PieceAssembler {
    catalog: Arc<SourceCatalog>,
    descriptions: HashMap<EntityKey, Arc<OwnerDescription>>,
}
impl PieceAssembler {
    pub fn new(catalog: Arc<SourceCatalog>) -> Self {
        Self {
            catalog,
            descriptions: HashMap::new(),
        }
    }
    pub fn cache_len(&self) -> usize {
        self.descriptions.len()
    }
    pub fn assemble(
        &mut self,
        matches: &[CodeMatch],
        kind: &str,
        limit: usize,
    ) -> Result<Vec<PieceCandidate>> {
        if limit == 0 {
            return Err(invalid("positive piece candidate limit required"));
        }
        let mut groups: Vec<(PieceIdentity, Vec<CodeMatch>)> = Vec::new();
        let mut lookup = HashMap::new();
        for matched in matches {
            if !evidence_matches(&matched.entity, &matched.source_hash, &matched.evidence)
                || self
                    .catalog
                    .snapshots()
                    .get(&matched.entity.path)
                    .is_none_or(|source| source.hash() != matched.source_hash)
                || self.catalog.passages(&matched.entity).is_err()
            {
                return Err(invalid("retrieved member is outside the piece source"));
            }
            if let Some(primary) = self
                .catalog
                .primary(&matched.entity, kind)
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?
            {
                let index = *lookup.entry(primary.clone()).or_insert_with(|| {
                    let i = groups.len();
                    groups.push((primary, Vec::new()));
                    i
                });
                groups[index].1.push(matched.clone());
            }
        }
        let mut result = Vec::new();
        for (primary, mut supporting) in groups.into_iter().take(limit) {
            let (path, entity) = match primary {
                PieceIdentity::Entity(key) => (key.path.clone(), Some(key)),
                PieceIdentity::Path(path) => (path, None),
            };
            let keys: Vec<_> = self.catalog.by_path()[&path]
                .iter()
                .filter(|key| match kind {
                    "class" => {
                        Some(*key) == entity.as_ref()
                            || self.catalog.enclosing_class(key).unwrap() == entity.as_ref()
                    }
                    "symbol" => Some(*key) == entity.as_ref(),
                    _ => true,
                })
                .cloned()
                .collect();
            let mut members = Vec::new();
            for key in keys {
                if !self.descriptions.contains_key(&key) {
                    let description =
                        describe_owner(self.catalog.passages(&key).expect("catalog-owned key"))?;
                    self.descriptions.insert(key.clone(), Arc::new(description));
                }
                members.push(self.descriptions[&key].clone());
            }
            supporting.sort_by(|a, b| {
                b.score
                    .partial_cmp(&a.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            for matched in &mut supporting {
                matched.evidence = self
                    .catalog
                    .passages(&matched.entity)
                    .expect("admitted owner")
                    .to_vec();
            }
            result.push(PieceCandidate::new(
                kind.into(),
                path,
                entity,
                members,
                supporting,
            )?);
        }
        Ok(result)
    }
}
