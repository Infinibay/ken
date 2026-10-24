//! Canonical ownership and lexical containment of immutable physical snapshots.
use crate::{
    EntityKey, Passage, Span,
    model::evidence_matches,
    query::{CodeMatch, merge_spans},
    source_locator::module_name,
    source_snapshot::{SourceAuthority, SourceResult, SourceSnapshot, invalid},
};
use ken_text::unicode::whitespace;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashMap},
    sync::{Arc, OnceLock},
};

pub fn entity_fields(key: &EntityKey) -> Value {
    json!({"kind":key.kind,"qualname":key.qualname,"owner":key.owner,"definition_ordinal":key.definition_ordinal})
}
pub fn entity_id(key: &EntityKey) -> String {
    let fields = BTreeMap::from([
        ("definition_ordinal", json!(key.definition_ordinal)),
        ("kind", json!(key.kind)),
        ("owner", json!(key.owner)),
        ("path", json!(key.path)),
        ("qualname", json!(key.qualname)),
    ]);
    serde_json::to_string(&fields).expect("scalar entity identity")
}
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum PieceIdentity {
    Entity(EntityKey),
    Path(String),
}
struct Scope {
    extent: [usize; 2],
    class: Option<EntityKey>,
    members: OnceLock<Option<Vec<EntityKey>>>,
}
pub struct SourceCatalog {
    source: Arc<SourceAuthority>,
    owners: Vec<(EntityKey, Vec<Passage>)>,
    lookup: HashMap<EntityKey, usize>,
    by_path: BTreeMap<String, Vec<EntityKey>>,
    snapshots: BTreeMap<String, SourceSnapshot>,
    scopes: Vec<Scope>,
}
fn callable(kind: &str) -> bool {
    matches!(kind, "function" | "method" | "constructor" | "destructor")
}
pub(crate) fn piece_entity_kind(kind: &str, entity_kind: &str) -> bool {
    match kind {
        "class" => entity_kind == "class",
        "symbol" => callable(entity_kind) || matches!(entity_kind, "const" | "constant"),
        _ => false,
    }
}
impl SourceCatalog {
    pub fn new(
        source: Arc<SourceAuthority>,
        owners: Vec<(EntityKey, Vec<Passage>)>,
    ) -> SourceResult<Self> {
        let mut catalog = Self {
            source,
            owners,
            lookup: HashMap::new(),
            by_path: BTreeMap::new(),
            snapshots: BTreeMap::new(),
            scopes: Vec::new(),
        };
        for (index, (key, passages)) in catalog.owners.iter().enumerate() {
            if passages.is_empty() {
                return Err(invalid("empty source owner"));
            }
            if catalog.lookup.insert(key.clone(), index).is_some() {
                return Err(invalid("duplicate source owner"));
            }
            if !catalog.snapshots.contains_key(&key.path) {
                catalog
                    .snapshots
                    .insert(key.path.clone(), catalog.source.read(&key.path)?);
            }
            let snapshot = &catalog.snapshots[&key.path];
            if passages.iter().any(|p| p.source_hash != snapshot.hash()) {
                return Err(invalid(format!("stale source catalog: {}", key.path)));
            }
            if passages.iter().any(|p| {
                p.entity != *key
                    || [p.span, p.entity_span].iter().any(|s| {
                        s.start_line == 0
                            || s.start_line > s.end_line
                            || s.end_line > snapshot.lines().len()
                    })
            }) {
                return Err(invalid("catalog source owner is invalid"));
            }
            catalog
                .by_path
                .entry(key.path.clone())
                .or_default()
                .push(key.clone());
            catalog.scopes.push(Scope {
                extent: [
                    passages
                        .iter()
                        .map(|p| p.entity_span.start_line)
                        .min()
                        .unwrap(),
                    passages
                        .iter()
                        .map(|p| p.entity_span.end_line)
                        .max()
                        .unwrap(),
                ],
                class: None,
                members: OnceLock::new(),
            });
        }
        for (i, (key, _)) in catalog.owners.iter().enumerate() {
            let mut candidates: Vec<_> = catalog.by_path[&key.path]
                .iter()
                .filter(|outer| outer.kind == "class" && catalog.encloses(outer, key).unwrap())
                .collect();
            candidates.sort_by_key(|key| {
                let [a, b] = catalog.extent(key).unwrap();
                (b - a, entity_id(key))
            });
            if candidates.len() > 1
                && catalog.extent(candidates[0])? == catalog.extent(candidates[1])?
            {
                return Err(invalid("ambiguous enclosing class"));
            }
            catalog.scopes[i].class = candidates.first().map(|key| (*key).clone());
        }
        Ok(catalog)
    }
    fn index(&self, key: &EntityKey) -> SourceResult<usize> {
        self.lookup
            .get(key)
            .copied()
            .ok_or_else(|| invalid("unknown source owner"))
    }
    pub fn source(&self) -> &Arc<SourceAuthority> {
        &self.source
    }
    pub fn owners(&self) -> &[(EntityKey, Vec<Passage>)] {
        &self.owners
    }
    pub fn passages(&self, key: &EntityKey) -> SourceResult<&[Passage]> {
        Ok(&self.owners[self.index(key)?].1)
    }
    /// Admit retrieval support only from this canonical owner/source generation.
    pub fn admit_match(&self, matched: &CodeMatch) -> SourceResult<()> {
        if !evidence_matches(&matched.entity, &matched.source_hash, &matched.evidence)
            || self
                .snapshots
                .get(&matched.entity.path)
                .is_none_or(|s| s.hash() != matched.source_hash)
            || self.passages(&matched.entity).is_err()
        {
            return Err(invalid("retrieved member is outside the piece source"));
        }
        Ok(())
    }
    pub fn by_path(&self) -> &BTreeMap<String, Vec<EntityKey>> {
        &self.by_path
    }
    pub fn snapshots(&self) -> &BTreeMap<String, SourceSnapshot> {
        &self.snapshots
    }
    pub fn enclosing_class(&self, key: &EntityKey) -> SourceResult<Option<&EntityKey>> {
        Ok(self.scopes[self.index(key)?].class.as_ref())
    }
    pub fn extent(&self, key: &EntityKey) -> SourceResult<[usize; 2]> {
        Ok(self.scopes[self.index(key)?].extent)
    }
    pub fn encloses(&self, outer: &EntityKey, inner: &EntityKey) -> SourceResult<bool> {
        if outer == inner || outer.path != inner.path {
            return Ok(false);
        }
        let (Some(outer_name), Some(inner_name)) = (&outer.qualname, &inner.qualname) else {
            return Ok(false);
        };
        if outer_name.is_empty() || !inner_name.starts_with(&format!("{outer_name}.")) {
            return Ok(false);
        }
        let [a, b] = self.extent(outer)?;
        let [c, d] = self.extent(inner)?;
        Ok(a <= c && c <= d && d <= b)
    }
    pub fn owned_ranges(
        &self,
        key: &EntityKey,
        implementation: bool,
    ) -> SourceResult<Vec<[usize; 2]>> {
        let intervals: Vec<_> = self.owners[self.index(key)?]
            .1
            .iter()
            .filter_map(|p| {
                let start = if implementation {
                    p.span
                        .start_line
                        .max(p.implementation_start_line.unwrap_or(0))
                } else {
                    p.span.start_line
                };
                (start <= p.span.end_line).then_some(Span {
                    start_line: start,
                    end_line: p.span.end_line,
                })
            })
            .collect();
        Ok(merge_spans(&intervals)
            .into_iter()
            .map(|s| [s.start_line, s.end_line])
            .collect())
    }
    pub fn scope_members(&self, key: &EntityKey) -> SourceResult<Option<Vec<EntityKey>>> {
        let scope = &self.scopes[self.index(key)?];
        Ok(scope
            .members
            .get_or_init(|| {
                let mut descendants: Vec<_> = self.by_path[&key.path]
                    .iter()
                    .filter(|k| self.encloses(key, k).unwrap())
                    .cloned()
                    .collect();
                descendants.sort_by_key(entity_id);
                let mut ranges = Vec::new();
                for member in std::iter::once(key).chain(descendants.iter()) {
                    ranges.extend(self.owned_ranges(member, false).unwrap());
                }
                let [start, end] = scope.extent;
                let lines = self.snapshots[&key.path].lines();
                (start..=end)
                    .all(|n| {
                        lines[n - 1].chars().all(whitespace)
                            || ranges.iter().any(|[a, b]| *a <= n && n <= *b)
                    })
                    .then_some(descendants)
            })
            .clone())
    }
    pub fn enclosing_callable(&self, key: &EntityKey) -> SourceResult<Option<EntityKey>> {
        self.index(key)?;
        let order = |key: &EntityKey| {
            let [a, b] = self.extent(key).unwrap();
            (
                b - a,
                std::cmp::Reverse(key.qualname.as_ref().map_or(0, |n| n.chars().count())),
            )
        };
        let mut candidates: Vec<_> = self.by_path[&key.path]
            .iter()
            .filter(|k| callable(&k.kind) && self.encloses(k, key).unwrap())
            .collect();
        candidates.sort_by_key(|k| (order(k), entity_id(k)));
        if candidates.len() > 1 && order(candidates[0]) == order(candidates[1]) {
            return Ok(None);
        }
        Ok(candidates.first().map(|k| (*k).clone()))
    }
    pub fn primary(&self, key: &EntityKey, kind: &str) -> SourceResult<Option<PieceIdentity>> {
        self.index(key)?;
        Ok(match kind {
            "class" if piece_entity_kind(kind, &key.kind) => {
                Some(PieceIdentity::Entity(key.clone()))
            }
            "class" => self
                .enclosing_class(key)?
                .cloned()
                .map(PieceIdentity::Entity),
            "symbol" if piece_entity_kind(kind, &key.kind) => {
                Some(PieceIdentity::Entity(key.clone()))
            }
            "symbol" => None,
            "module" => module_name(&key.path).map(|_| PieceIdentity::Path(key.path.clone())),
            "file" => Some(PieceIdentity::Path(key.path.clone())),
            _ => return Err(invalid("unknown piece kind")),
        })
    }
    pub fn source_inventory(&self) -> SourceResult<Vec<Value>> {
        let mut keys: Vec<_> = self.owners.iter().map(|(key, _)| key).collect();
        keys.sort_by_key(|key| entity_id(key));
        keys.into_iter().map(|key| {
            let owned: Vec<_> = self.owners[self.index(key)?].1.iter().map(|p| [p.span.start_line,p.span.end_line]).collect();
            Ok(json!({"path":key.path,"entity":entity_fields(key),"source_hash":self.snapshots[&key.path].hash(),"extent":self.extent(key)?,"owned_ranges":owned,"enclosing_class":self.enclosing_class(key)?.map(entity_fields)}))
        }).collect()
    }
}
