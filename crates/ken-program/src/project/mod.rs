//! Nominal project linking precedes interprocedural value/effect enrichment.
mod calls;
mod cpp;
mod imports;
mod resolution;
mod types;
use crate::{Attributes, Entity, Fact, IR_VERSION, ProgramError, StructuralIr};
use serde_json::{Value, json, value::to_raw_value};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, ProgramError>;
#[derive(Default)]
struct Ordered<K: Ord, V> {
    order: Vec<K>,
    values: BTreeMap<K, V>,
}
impl<K: Ord + Clone, V> Ordered<K, V> {
    fn insert(&mut self, key: K, value: V) {
        if !self.values.contains_key(&key) {
            self.order.push(key.clone());
        }
        self.values.insert(key, value);
    }
    fn get(&self, key: &K) -> Option<&V> {
        self.values.get(key)
    }
    fn iter(&self) -> impl Iterator<Item = (&K, &V)> {
        self.order.iter().map(|k| (k, &self.values[k]))
    }
}
fn attrs(value: Value) -> Attributes {
    value
        .as_object()
        .expect("project attributes object")
        .iter()
        .map(|(k, v)| (k.clone(), to_raw_value(v).expect("project JSON attribute")))
        .collect()
}
fn fact_attr(fact: &Fact, key: &str) -> Value {
    fact.attrs
        .get(key)
        .map(|v| serde_json::from_str(v.get()).expect("validated project attribute"))
        .unwrap_or(Value::Null)
}
fn truth(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
        Value::Number(v) => v.as_f64() != Some(0.0),
    }
}
fn trim(value: &str) -> &str {
    value.trim_matches(ken_text::unicode::whitespace)
}
fn regex(pattern: &str) -> std::sync::Arc<regex::Regex> {
    static CACHE: std::sync::OnceLock<
        std::sync::Mutex<BTreeMap<String, std::sync::Arc<regex::Regex>>>,
    > = std::sync::OnceLock::new();
    let mut cache = CACHE
        .get_or_init(Default::default)
        .lock()
        .expect("nominal regex cache");
    cache
        .entry(pattern.into())
        .or_insert_with(|| {
            std::sync::Arc::new(
                regex::Regex::new(&ken_text::unicode::source_pattern(pattern))
                    .expect("project regex literal"),
            )
        })
        .clone()
}
fn full<'a>(pattern: &str, text: &'a str) -> Option<regex::Captures<'a>> {
    regex(&format!(r"\A(?:{pattern})\z")).captures(text)
}
struct Project {
    graph: StructuralIr,
    positions: BTreeMap<String, usize>,
    input: BTreeMap<String, Vec<usize>>,
    imports: imports::Imports,
    bindings: BTreeMap<(String, String), Vec<String>>,
    class_names: BTreeMap<(String, String), Vec<String>>,
    types: BTreeSet<String>,
    java_types: BTreeMap<String, Vec<String>>,
    go_types: BTreeMap<((String, String), String), Vec<String>>,
    known: BTreeMap<String, BTreeSet<String>>,
    declared: BTreeMap<String, String>,
    owners: Ordered<String, String>,
    methods: Ordered<(String, String), Vec<String>>,
    bases: BTreeMap<String, BTreeSet<String>>,
    callees: Ordered<String, String>,
    receivers: Ordered<String, String>,
    call_owner: BTreeMap<String, String>,
    allocations: BTreeMap<String, String>,
    fields: BTreeMap<(String, String), String>,
    lexical: BTreeMap<String, String>,
    lexical_calls: BTreeMap<(String, String), Vec<String>>,
}
impl Project {
    fn from_owned(
        units: Vec<StructuralIr>,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<Self> {
        let mut graph = StructuralIr {
            path: "<project>".into(),
            language: "mixed".into(),
            entities: Vec::new(),
            operations: Vec::new(),
            facts: Vec::new(),
            capabilities: units
                .first()
                .map(|u| u.capabilities.clone())
                .unwrap_or_default(),
            diagnostics: Vec::new(),
            version: IR_VERSION.into(),
            relations: Default::default(),
            view: "source".into(),
        };
        let mut positions = BTreeMap::new();
        let mut unit_metadata = Vec::new();
        for unit in units {
            check()?;
            if unit.version != IR_VERSION {
                return Err(ProgramError::Invalid("incompatible project IR version"));
            }
            unit_metadata.push((unit.path.clone(), unit.language.clone()));
            graph.capabilities.retain(|c| unit.capabilities.contains(c));
            for (id, entity) in unit.entities {
                if let Some(&position) = positions.get(&id) {
                    graph.entities[position] = (id, entity);
                } else {
                    positions.insert(id.clone(), graph.entities.len());
                    graph.entities.push((id, entity));
                }
            }
            graph.operations.extend(unit.operations);
            graph.facts.extend(unit.facts);
            graph.diagnostics.extend(unit.diagnostics);
        }
        let interpreted = [
            "language",
            "expression",
            "type_parameters",
            "construction",
            "constructor",
            "static",
            "declared",
            "return_type",
            "type",
            "native_type",
            "execution",
            "decorators",
            "cpp_signature_syntax",
            "cv_qualifiers",
            "ref_qualifier",
            "cpp_variadic",
            "explicit_virtual",
        ];
        for (_, entity) in &graph.entities {
            for key in interpreted {
                if let Some(raw) = entity.attrs.get(key) {
                    serde_json::from_str::<Value>(raw.get())?;
                }
            }
        }
        for fact in &graph.facts {
            let interpreted: &[&str] = match fact.relation.as_str() {
                "IMPORT_SYNTAX" => &["language"],
                "BASE_VALUE" => &["name"],
                "HAS_PARAMETER" => &["receiver", "position"],
                "ARGUMENT" => &["kind"],
                _ => &[],
            };
            for key in interpreted {
                if let Some(raw) = fact.attrs.get(*key) {
                    serde_json::from_str::<Value>(raw.get())?;
                }
            }
        }
        let mut input = BTreeMap::<String, Vec<usize>>::new();
        for (i, f) in graph.facts.iter().enumerate() {
            input.entry(f.relation.clone()).or_default().push(i);
        }
        let imports = imports::Imports::build(&graph, &unit_metadata)?;
        let mut project = Self {
            graph,
            positions,
            input,
            imports,
            bindings: BTreeMap::new(),
            class_names: BTreeMap::new(),
            types: BTreeSet::new(),
            java_types: BTreeMap::new(),
            go_types: BTreeMap::new(),
            known: BTreeMap::new(),
            declared: BTreeMap::new(),
            owners: Ordered::default(),
            methods: Ordered::default(),
            bases: BTreeMap::new(),
            callees: Ordered::default(),
            receivers: Ordered::default(),
            call_owner: BTreeMap::new(),
            allocations: BTreeMap::new(),
            fields: BTreeMap::new(),
            lexical: BTreeMap::new(),
            lexical_calls: BTreeMap::new(),
        };
        project.index_symbols();
        Ok(project)
    }
    fn entity(&self, id: &str) -> &Entity {
        &self.graph.entities[self.positions[id]].1
    }
    fn attr(&self, id: &str, key: &str) -> Value {
        self.positions
            .get(id)
            .and_then(|&i| self.graph.entities[i].1.attrs.get(key))
            .map(|v| serde_json::from_str(v.get()).expect("validated nominal attribute"))
            .unwrap_or(Value::Null)
    }
    fn flag(&self, id: &str, key: &str) -> bool {
        truth(&self.attr(id, key))
    }
    fn set(&mut self, id: &str, key: &str, value: Value) {
        let position = self.positions[id];
        self.graph.entities[position]
            .1
            .attrs
            .insert(key.into(), to_raw_value(&value).expect("project attribute"));
    }
    fn insert(&mut self, entity: Entity) {
        if let Some(&i) = self.positions.get(&entity.id) {
            self.graph.entities[i].1 = entity;
        } else {
            self.positions
                .insert(entity.id.clone(), self.graph.entities.len());
            self.graph.entities.push((entity.id.clone(), entity));
        }
    }
    fn add(
        &mut self,
        subject: &str,
        relation: &str,
        object: &str,
        evidence: &str,
        attributes: Value,
    ) {
        self.graph.relations.insert(relation.into());
        self.graph.facts.push(Fact {
            subject: subject.into(),
            relation: relation.into(),
            object: object.into(),
            evidence: (!evidence.is_empty())
                .then(|| evidence.into())
                .into_iter()
                .collect(),
            attrs: attrs(attributes),
        });
    }
    fn rows(&self, relation: &str) -> Vec<Fact> {
        self.input
            .get(relation)
            .into_iter()
            .flatten()
            .map(|&i| self.graph.facts[i].clone())
            .collect()
    }
    fn ev(&self, id: &str) -> String {
        format!("{}:{}", self.entity(id).path, self.entity(id).line)
    }
    fn ancestors(&self, cls: &str) -> BTreeSet<String> {
        let mut seen = BTreeSet::new();
        let mut frontier = vec![cls.to_owned()];
        while let Some(current) = frontier.pop() {
            for base in self.bases.get(&current).into_iter().flatten() {
                if seen.insert(base.clone()) {
                    frontier.push(base.clone());
                }
            }
        }
        seen
    }
    fn finish(mut self, check: &mut impl FnMut() -> Result<()>) -> Result<StructuralIr> {
        self.link_types();
        self.link_methods();
        self.allocate();
        self.propagate(check)?;
        self.lexical_captures();
        self.link_lexical_calls();
        self.link_receivers();
        let resolved = self
            .graph
            .facts
            .iter()
            .filter(|f| f.relation == "TARGET")
            .map(|f| f.subject.clone())
            .collect::<BTreeSet<_>>();
        let ambiguous = self
            .graph
            .facts
            .iter()
            .filter(|f| f.relation == "MAY_TARGET")
            .map(|f| f.subject.clone())
            .collect::<BTreeSet<_>>();
        for id in self
            .graph
            .entities
            .iter()
            .filter(|(_, e)| e.kind == "CALL")
            .map(|(id, _)| id.clone())
            .collect::<Vec<_>>()
        {
            self.set(
                &id,
                "resolution",
                if ambiguous.contains(&id) {
                    "ambiguous"
                } else if resolved.contains(&id) {
                    "resolved"
                } else {
                    "unresolved"
                }
                .into(),
            );
        }
        check()?;
        Ok(self.graph)
    }
}
/// Merge immutable units and link explicit imports, nominal types and call targets.
/// This phase does not run sequential returns, whole-program effects or KQL.
/// Source facts remain a prefix; derived facts use deterministic graph ordering.
pub fn link_nominal(units: &[StructuralIr]) -> Result<StructuralIr> {
    link_nominal_with_check(units, || Ok(()))
}
/// Cooperative cancellation is checked before acquisition, each unit, each bounded
/// propagation pass and completion. Input units remain unchanged on every outcome.
pub fn link_nominal_with_check(
    units: &[StructuralIr],
    mut check: impl FnMut() -> Result<()>,
) -> Result<StructuralIr> {
    check()?;
    Project::from_owned(units.to_vec(), &mut check)?.finish(&mut check)
}
/// Transfer disposable units without cloning their entity and source-fact payloads.
pub fn link_nominal_owned(units: Vec<StructuralIr>) -> Result<StructuralIr> {
    let mut check = || Ok(());
    check()?;
    Project::from_owned(units, &mut check)?.finish(&mut check)
}
