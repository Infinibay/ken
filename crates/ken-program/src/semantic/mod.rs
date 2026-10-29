//! Conservative project evidence assembled after nominal linking.
mod bindings;
mod collections;
mod effects;
mod inventory;
mod members;
mod summaries;
mod transfers;
mod types;
use crate::{Attributes, Entity, Fact, Operation, ProgramError, StructuralIr, attributes};
use serde_json::{Value, json, value::to_raw_value};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
type Result<T> = std::result::Result<T, ProgramError>;
type SetMap = BTreeMap<String, BTreeSet<String>>;
fn v(a: &Attributes, k: &str) -> Result<Value> {
    Ok(attributes::get(a, k)?.unwrap_or(Value::Null))
}
fn s(a: &Attributes, k: &str) -> Result<String> {
    Ok(v(a, k)?.as_str().unwrap_or("").into())
}
fn b(a: &Attributes, k: &str) -> Result<bool> {
    attributes::truth(a, k)
}
fn n(a: &Attributes, k: &str) -> Result<i64> {
    Ok(v(a, k)?.as_i64().unwrap_or(0))
}
fn tokens(o: &Operation) -> Result<Vec<String>> {
    attributes::tokens(&o.attrs)
}
fn attrs(value: Value) -> Attributes {
    value
        .as_object()
        .expect("semantic attrs")
        .iter()
        .map(|(k, v)| (k.clone(), to_raw_value(v).expect("semantic JSON")))
        .collect()
}
fn ev(f: &Fact) -> &str {
    f.evidence.first().map_or("", String::as_str)
}
fn trim(s: &str) -> &str {
    s.trim_matches(ken_text::unicode::whitespace)
}
fn rx(pattern: &str) -> std::sync::Arc<regex::Regex> {
    static CACHE: std::sync::OnceLock<
        std::sync::Mutex<BTreeMap<String, std::sync::Arc<regex::Regex>>>,
    > = std::sync::OnceLock::new();
    let mut cache = CACHE
        .get_or_init(Default::default)
        .lock()
        .expect("semantic pattern cache");
    cache
        .entry(pattern.into())
        .or_insert_with(|| {
            std::sync::Arc::new(
                regex::Regex::new(&ken_text::unicode::source_pattern(pattern))
                    .expect("semantic pattern"),
            )
        })
        .clone()
}
fn full<'a>(pattern: &str, text: &'a str) -> Option<regex::Captures<'a>> {
    rx(&format!(r"\A(?:{pattern})\z")).captures(text)
}
const DYNAMIC: &[&str] = &[
    "eval",
    "exec",
    "locals",
    "globals",
    "_getframe",
    "currentframe",
];
const COMMON: &[&str] = &["python", "javascript", "typescript", "java", "csharp"];
struct Graph {
    ir: StructuralIr,
    entities: BTreeMap<String, usize>,
    operations: BTreeMap<String, usize>,
    index: BTreeMap<String, Vec<usize>>,
}
impl Graph {
    fn new(ir: StructuralIr) -> Result<Self> {
        let entities = ir
            .entities
            .iter()
            .enumerate()
            .map(|(i, (id, _))| (id.clone(), i))
            .collect();
        let operations = ir
            .operations
            .iter()
            .enumerate()
            .map(|(i, o)| (o.id.clone(), i))
            .collect();
        let mut g = Self {
            ir,
            entities,
            operations,
            index: Default::default(),
        };
        g.reindex();
        for o in &g.ir.operations {
            g.e(&o.owner)?;
        }
        Ok(g)
    }
    fn reindex(&mut self) {
        self.index.clear();
        for (i, f) in self.ir.facts.iter().enumerate() {
            self.index.entry(f.relation.clone()).or_default().push(i);
        }
    }
    fn rows(&self, r: &str) -> Vec<Fact> {
        self.index
            .get(r)
            .into_iter()
            .flatten()
            .map(|&i| self.ir.facts[i].clone())
            .collect()
    }
    fn map(&self, r: &str) -> BTreeMap<String, String> {
        self.rows(r)
            .into_iter()
            .map(|f| (f.subject, f.object))
            .collect()
    }
    fn reverse(&self, r: &str) -> BTreeMap<String, String> {
        self.rows(r)
            .into_iter()
            .map(|f| (f.object, f.subject))
            .collect()
    }
    fn sets(&self, r: &str) -> SetMap {
        let mut m = SetMap::new();
        for f in self.rows(r) {
            m.entry(f.subject).or_default().insert(f.object);
        }
        m
    }
    fn groups(&self, r: &str) -> BTreeMap<String, Vec<Fact>> {
        let mut m = BTreeMap::<_, Vec<_>>::new();
        for f in self.rows(r) {
            m.entry(f.subject.clone()).or_default().push(f);
        }
        m
    }
    fn e(&self, id: &str) -> Result<&Entity> {
        self.entities
            .get(id)
            .map(|&i| &self.ir.entities[i].1)
            .ok_or(ProgramError::Invalid(
                "semantic entity reference is missing",
            ))
    }
    fn get(&self, id: &str) -> Option<&Entity> {
        self.entities.get(id).map(|&i| &self.ir.entities[i].1)
    }
    fn op(&self, id: &str) -> Option<&Operation> {
        self.operations.get(id).map(|&i| &self.ir.operations[i])
    }
    fn ids(&self) -> Vec<String> {
        self.ir.entities.iter().map(|(id, _)| id.clone()).collect()
    }
    fn evidence(&self, id: &str) -> Result<String> {
        let e = self.e(id)?;
        Ok(format!("{}:{}", e.path, e.line))
    }
    fn add(&mut self, sub: &str, rel: &str, obj: &str, evidence: &str, a: Value) {
        self.add_raw(sub, rel, obj, evidence, attrs(a));
    }
    fn add_raw(&mut self, sub: &str, rel: &str, obj: &str, evidence: &str, a: Attributes) {
        self.index
            .entry(rel.into())
            .or_default()
            .push(self.ir.facts.len());
        self.ir.relations.insert(rel.into());
        self.ir.facts.push(Fact {
            subject: sub.into(),
            relation: rel.into(),
            object: obj.into(),
            evidence: (!evidence.is_empty())
                .then(|| evidence.into())
                .into_iter()
                .collect(),
            attrs: a,
        });
    }
    fn set(&mut self, id: &str, key: &str, value: Value) -> Result<()> {
        let i = *self
            .entities
            .get(id)
            .ok_or(ProgramError::Invalid("semantic mutation target is missing"))?;
        self.ir.entities[i]
            .1
            .attrs
            .insert(key.into(), to_raw_value(&value)?);
        Ok(())
    }
    fn insert(&mut self, e: Entity) {
        if let Some(&i) = self.entities.get(&e.id) {
            self.ir.entities[i].1 = e;
        } else {
            self.entities.insert(e.id.clone(), self.ir.entities.len());
            self.ir.entities.push((e.id.clone(), e));
        }
    }
    fn owners(&self) -> BTreeMap<String, Vec<Operation>> {
        let mut m = BTreeMap::<_, Vec<_>>::new();
        for o in &self.ir.operations {
            m.entry(o.owner.clone()).or_default().push(o.clone());
        }
        m
    }
    fn params(&self) -> Result<SetMap> {
        let mut m = SetMap::new();
        for f in self.rows("HAS_PARAMETER") {
            if !b(&f.attrs, "receiver")? {
                m.entry(f.subject).or_default().insert(f.object);
            }
        }
        Ok(m)
    }
    fn nested(&self) -> Result<BTreeSet<String>> {
        let mut m = BTreeSet::new();
        for f in self.rows("OWNED_BY") {
            if self.e(&f.subject)?.kind == "CALLABLE" {
                m.insert(f.object);
            }
        }
        Ok(m)
    }
    fn dynamic(&self) -> Result<BTreeSet<String>> {
        let owners = self.reverse("HAS_CALL");
        let mut out = BTreeSet::new();
        for f in self.rows("CALLEE_NAME") {
            if DYNAMIC.contains(&f.object.as_str())
                && let Some(o) = owners.get(&f.subject)
            {
                out.insert(o.clone());
            }
        }
        Ok(out)
    }
}
/// Consume a nominal project and assemble all source-semantic enrichment phases.
/// This is not graph-cache publication or a KQL executor. On error the owned
/// partial result is dropped; callers retain their immutable input units.
pub(crate) fn enrich(
    ir: StructuralIr,
    paths: &BTreeSet<String>,
    check: &mut impl FnMut() -> Result<()>,
) -> Result<StructuralIr> {
    let mut g = Graph::new(ir)?;
    let origins = crate::control::sequential_returns(&mut g.ir, Some(paths))?;
    g.reindex();
    summaries::return_and_arguments(&mut g, &origins)?;
    check()?;
    summaries::field_defaults(&mut g)?;
    summaries::selector_and_dispatch(&mut g)?;
    summaries::publish(&mut g)?;
    types::annotation_types(&mut g)?;
    check()?;
    crate::control::structured_control(&mut g.ir, Some(paths))?;
    crate::control::syntax_contexts(&mut g.ir)?;
    crate::control::normal_completion(&mut g.ir)?;
    g.reindex();
    check()?;
    collections::snapshots(&mut g)?;
    collections::lifecycle(&mut g)?;
    members::roots(&mut g)?;
    members::access(&mut g)?;
    check()?;
    members::contracts(&mut g)?;
    members::events(&mut g)?;
    bindings::bindings(&mut g)?;
    transfers::fields(&mut g)?;
    transfers::members(&mut g)?;
    inventory::binding_writes(&mut g)?;
    effects::optional(&mut g)?;
    effects::concurrency(&mut g)?;
    inventory::allocations(&mut g)?;
    inventory::writes(&mut g)?;
    check()?;
    inventory::values(&mut g)?;
    check()?;
    Ok(g.ir)
}
fn lookup<'a>(m: &'a BTreeMap<String, String>, k: &str) -> &'a str {
    m.get(k).map_or("", String::as_str)
}
fn set(m: &SetMap, k: &str) -> BTreeSet<String> {
    m.get(k).cloned().unwrap_or_default()
}
#[cfg(test)]
mod tests;
