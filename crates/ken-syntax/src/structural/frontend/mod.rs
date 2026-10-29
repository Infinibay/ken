//! Full source lowering, coordinated through explicit declaration and value phases.
mod calls;
mod conditions;
mod cpp;
mod declarations;
mod inventories;
mod semantics;
mod values;
use super::{
    LoweringError, attributes,
    ownership::Ownership,
    source::{self, field, text},
    vocabulary::vocabulary,
};
use crate::{GrammarCatalog, Language, SyntaxNode};
use ken_program::{Entity, Fact, IR_VERSION, StructuralIr, control::lexical_execution};
use regex::Regex;
use serde_json::{Value, json, value::to_raw_value};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    sync::{Arc, Mutex, OnceLock},
};

pub(super) fn rx(pattern: &str) -> Arc<Regex> {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<Regex>>>> = OnceLock::new();
    let mut cache = CACHE
        .get_or_init(Default::default)
        .lock()
        .expect("source regex cache");
    cache
        .entry(pattern.into())
        .or_insert_with(|| {
            Arc::new(
                Regex::new(&ken_text::unicode::source_pattern(pattern))
                    .expect("source regex literal"),
            )
        })
        .clone()
}
fn full<'a>(pattern: &str, text: &'a str) -> Option<regex::Captures<'a>> {
    rx(&format!(r"\A(?:{pattern})\z")).captures(text)
}
// These source patterns have a leading Python word boundary. Rust regex's
// built-in boundary uses a different Unicode word table, so check it explicitly.
fn word_capture<'s>(pattern: &str, text: &'s str) -> Option<regex::Captures<'s>> {
    rx(pattern).captures_iter(text).find(|m| {
        text[..m.get(0).expect("whole match").start()]
            .chars()
            .next_back()
            .is_none_or(|c| !ken_text::unicode::word(c))
    })
}
fn trim(text: &str) -> &str {
    text.trim_matches(ken_text::unicode::whitespace)
}
fn empty_ir(path: &str, language: Language) -> StructuralIr {
    StructuralIr {
        path: path.into(),
        language: language.as_str().into(),
        entities: Vec::new(),
        operations: Vec::new(),
        facts: Vec::new(),
        capabilities: [
            "syntax",
            "declarations",
            "calls",
            "local_storage",
            "control",
            "parameters",
            "imports",
            "generators",
        ]
        .into_iter()
        .map(Into::into)
        .collect(),
        diagnostics: Vec::new(),
        version: IR_VERSION.into(),
        relations: Default::default(),
        view: "source".into(),
    }
}
#[derive(Default)]
struct Bindings {
    names: BTreeMap<(String, String), String>,
    blocks: BTreeMap<(String, usize, String), String>,
    receivers: BTreeMap<String, String>,
}
#[derive(Default)]
struct Declarations<'a> {
    nodes: BTreeMap<usize, String>,
    types: Vec<(String, SyntaxNode<'a>)>,
    type_ids: BTreeSet<String>,
    type_positions: BTreeMap<String, usize>,
    type_groups: BTreeMap<usize, Vec<String>>,
    methods: BTreeMap<String, Vec<String>>,
    enums: BTreeMap<String, BTreeSet<String>>,
    bases: Vec<(String, String, String)>,
    base_values: Vec<(String, SyntaxNode<'a>, String)>,
    annotations: Vec<(String, String, String)>,
    field_initializers: BTreeMap<usize, Vec<(String, String, SyntaxNode<'a>)>>,
}
struct Unit<'a, 's> {
    source: &'s [u8],
    language: Language,
    root: SyntaxNode<'a>,
    module: String,
    ir: StructuralIr,
    positions: BTreeMap<String, usize>,
    declaration_facts: BTreeMap<(String, String), Vec<usize>>,
    owners: Ownership,
    bindings: Bindings,
    lexical_blocks: BTreeMap<usize, Option<SyntaxNode<'a>>>,
    declarations: Declarations<'a>,
    expression_values: BTreeSet<String>,
    call_nodes: BTreeMap<String, SyntaxNode<'a>>,
    context_decorators: BTreeSet<String>,
    exported_names: BTreeSet<String>,
    undefined_shadowed: bool,
    operation_by_id: BTreeMap<String, usize>,
}
impl<'a, 's> Unit<'a, 's> {
    fn new(root: SyntaxNode<'a>, source: &'s [u8], language: Language, path: &str) -> Self {
        let module = format!("{path}::module");
        let mut unit = Self {
            source,
            language,
            root,
            module: module.clone(),
            ir: empty_ir(path, language),
            positions: BTreeMap::new(),
            declaration_facts: BTreeMap::new(),
            owners: Ownership::default(),
            bindings: Bindings::default(),
            lexical_blocks: BTreeMap::new(),
            declarations: Declarations::default(),
            expression_values: BTreeSet::new(),
            call_nodes: BTreeMap::new(),
            context_decorators: BTreeSet::new(),
            exported_names: BTreeSet::new(),
            undefined_shadowed: false,
            operation_by_id: BTreeMap::new(),
        };
        unit.insert(Entity {
            id: module.clone(),
            kind: "MODULE".into(),
            name: path.into(),
            path: path.into(),
            line: 1,
            end_line: (root.end_point()[0] + 1) as i64,
            attrs: Default::default(),
        });
        unit.add(
            &module,
            "IS",
            "MODULE",
            &format!("{path}:1"),
            json!({"basis":"module-root"}),
        );
        // Index lexical ancestry once. Native parent() searches from the tree root;
        // walking every ancestor for each deep expression would be cubic work.
        let mut pending = vec![(root, None)];
        while let Some((node, enclosing)) = pending.pop() {
            unit.lexical_blocks.insert(node.id(), enclosing);
            let enclosing = if vocabulary().functions.contains(node.kind()) {
                None
            } else if matches!(
                node.kind(),
                "block" | "statement_block" | "compound_statement"
            ) {
                Some(node)
            } else {
                enclosing
            };
            pending.extend(
                node.named_children()
                    .into_iter()
                    .map(|child| (child, enclosing)),
            );
        }
        unit.import_context();
        unit
    }
    fn text(&self, node: Option<SyntaxNode<'_>>) -> String {
        text(node, self.source)
    }
    fn evidence(&self, node: SyntaxNode<'_>) -> String {
        format!("{}:{}", self.ir.path, node.start_point()[0] + 1)
    }
    fn add(&mut self, subject: &str, relation: &str, object: &str, evidence: &str, attrs: Value) {
        self.ir.relations.insert(relation.into());
        if matches!(relation, "DECLARES" | "HAS_FIELD") {
            self.declaration_facts
                .entry((subject.into(), object.into()))
                .or_default()
                .push(self.ir.facts.len());
        }
        self.ir.facts.push(Fact {
            subject: subject.into(),
            relation: relation.into(),
            object: object.into(),
            evidence: (!evidence.is_empty())
                .then(|| evidence.into())
                .into_iter()
                .collect(),
            attrs: attributes(attrs),
        });
    }
    fn update_declared_static(&mut self, scope: &str, target: &str, value: bool, fields: bool) {
        for &index in self
            .declaration_facts
            .get(&(scope.into(), target.into()))
            .into_iter()
            .flatten()
        {
            let fact = &mut self.ir.facts[index];
            if fact.relation == "DECLARES" || fields {
                fact.attrs.insert(
                    "static".into(),
                    to_raw_value(&value).expect("static attribute"),
                );
            }
        }
    }
    fn insert(&mut self, e: Entity) {
        if let Some(&i) = self.positions.get(&e.id) {
            self.ir.entities[i].1 = e;
        } else {
            self.positions.insert(e.id.clone(), self.ir.entities.len());
            self.ir.entities.push((e.id.clone(), e));
        }
    }
    fn entity_ref(&self, id: &str) -> &Entity {
        &self.ir.entities[self.positions[id]].1
    }
    fn entity_mut(&mut self, id: &str) -> &mut Entity {
        let i = self.positions[id];
        &mut self.ir.entities[i].1
    }
    fn attr(&self, id: &str, key: &str) -> Value {
        self.positions
            .get(id)
            .and_then(|&i| self.ir.entities[i].1.attrs.get(key))
            .map(|v| serde_json::from_str(v.get()).expect("source attribute JSON"))
            .unwrap_or(Value::Null)
    }
    fn flag(&self, id: &str, key: &str) -> bool {
        match self.attr(id, key) {
            Value::Null => false,
            Value::Bool(v) => v,
            Value::String(s) => !s.is_empty(),
            Value::Number(n) => n.as_f64() != Some(0.0),
            Value::Array(v) => !v.is_empty(),
            Value::Object(v) => !v.is_empty(),
        }
    }
    fn set(&mut self, id: &str, key: &str, value: Value) {
        self.entity_mut(id)
            .attrs
            .insert(key.into(), to_raw_value(&value).expect("source attribute"));
    }
    fn extend(&mut self, id: &str, attrs: Value) {
        self.entity_mut(id).attrs.extend(attributes(attrs));
    }
    fn entity(
        &mut self,
        kind: &str,
        name: &str,
        scope: &str,
        node: SyntaxNode<'a>,
        mut attrs: Value,
    ) -> String {
        let mut key = format!("{scope}/{kind}:{name}");
        if matches!(kind, "CALL" | "PARAMETER" | "CALLABLE") {
            key.push_str(&format!("@{}", node.start_byte()));
        }
        if kind == "CLASS" && node.kind() == "class" {
            key.push_str(&format!("@{}", node.start_byte()));
        }
        if matches!(kind, "CALL" | "VALUE") {
            key.push_str(&format!(":{}", node.end_byte()));
        }
        if !self.positions.contains_key(&key) {
            if matches!(
                self.language,
                Language::TypeScript
                    | Language::Java
                    | Language::CSharp
                    | Language::Cpp
                    | Language::Go
                    | Language::Rust
            ) && matches!(kind, "CLASS" | "INTERFACE" | "CALLABLE")
            {
                let parameters = self.bound_type_parameters(node);
                attrs["type_parameters"] = json!(parameters);
                for parameter in parameters {
                    self.add(
                        &key,
                        "BINDS_TYPE_PARAMETER",
                        &parameter,
                        &self.evidence(node),
                        json!({}),
                    );
                }
            }
            let mut metadata = attrs.clone();
            metadata["native_kind"] = node.kind().into();
            metadata["language"] = self.language.as_str().into();
            metadata["start_byte"] = node.start_byte().into();
            metadata["end_byte"] = node.end_byte().into();
            self.insert(Entity {
                id: key.clone(),
                kind: kind.into(),
                name: name.into(),
                path: self.ir.path.clone(),
                line: (node.start_point()[0] + 1) as i64,
                end_line: (node.end_point()[0] + 1) as i64,
                attrs: attributes(metadata),
            });
            self.add(&key, "IS", kind, &self.evidence(node), attrs);
        }
        key
    }
    fn resolve(&self, name: &str, scope: &str) -> Option<String> {
        let mut current = scope;
        while !current.is_empty() {
            if let Some(id) = self.bindings.names.get(&(current.into(), name.into())) {
                return Some(id.clone());
            }
            if current == self.module {
                break;
            }
            let Some((outer, _)) = current.rsplit_once('/') else {
                break;
            };
            current = outer;
        }
        self.bindings
            .names
            .get(&(self.module.clone(), name.into()))
            .cloned()
    }
    fn annotate(&mut self, subject: &str, node: SyntaxNode<'a>, evidence: &str) {
        self.declarations.annotations.push((
            subject.into(),
            self.text(Some(node)),
            evidence.into(),
        ));
        if self.language != Language::Rust {
            return;
        }
        let mut head = node;
        for _ in 0..32 {
            if !matches!(
                head.kind(),
                "reference_type" | "pointer_type" | "generic_type"
            ) {
                break;
            }
            let Some(nested) = head.field("type") else {
                return;
            };
            head = nested;
        }
        if head.kind() == "type_identifier" {
            self.add(
                subject,
                "TYPE_HEAD",
                &self.text(Some(head)),
                evidence,
                json!({"basis":"annotation-syntax"}),
            );
        }
    }
    fn enclosing(&self, node: SyntaxNode<'a>, kinds: &BTreeSet<String>) -> Option<SyntaxNode<'a>> {
        let mut parent = node.parent();
        while let Some(p) = parent {
            if vocabulary().functions.contains(p.kind()) {
                break;
            }
            if kinds.contains(p.kind()) {
                return Some(p);
            }
            parent = p.parent();
        }
        None
    }
    fn unwrap(&self, mut node: SyntaxNode<'a>) -> SyntaxNode<'a> {
        while matches!(
            node.kind(),
            "expression_list"
                | "parenthesized_expression"
                | "type"
                | "type_annotation"
                | "argument"
                | "expression_statement"
                | "reference_expression"
                | "pointer_expression"
                | "condition_clause"
        ) {
            let parts = node.named_children();
            if parts.len() != 1 {
                break;
            }
            node = parts[0];
        }
        node
    }
    fn branch_region(&self, mut node: SyntaxNode<'a>) -> SyntaxNode<'a> {
        while node.kind() == "else_clause" {
            let children = node.named_children();
            if children.len() != 1 {
                break;
            }
            node = children[0];
        }
        node
    }
    fn finish(mut self) -> Result<StructuralIr, LoweringError> {
        self.collect_declarations();
        self.undefined_shadowed = self.ir.entities.iter().any(|(_, e)| e.name == "undefined");
        let nodes = source::descendants_with_roles(self.root);
        if matches!(self.language, Language::JavaScript | Language::TypeScript) {
            for &(node, _) in &nodes {
                if vocabulary().assignments.contains(node.kind()) {
                    self.undefined_shadowed |=
                        self.text(source::declaration_parts(node).0) == "undefined";
                } else if matches!(node.kind(), "import_statement" | "import_clause") {
                    self.undefined_shadowed |=
                        ken_text::unicode::contains_word(&self.text(Some(node)), "undefined");
                } else if node.kind() == "with_statement"
                    || (node.kind() == "call_expression"
                        && self.text(node.field("function")) == "eval")
                {
                    self.undefined_shadowed = true;
                }
            }
        }
        for &(node, role) in &nodes {
            super::operations::project(
                &mut self.ir,
                node,
                role,
                &self.owners,
                self.source,
                self.language,
            );
        }
        self.operation_by_id = self
            .ir
            .operations
            .iter()
            .enumerate()
            .map(|(i, o)| (o.id.clone(), i))
            .collect();
        let execution = lexical_execution(&mut self.ir, self.root.has_error())?;
        for &(node, _) in &nodes {
            let first = self.ir.facts.len();
            self.semantics(node);
            let oid = source::operation_id(&self.ir.path, node);
            let state = &execution[&oid];
            let calls = self.ir.facts[first..]
                .iter()
                .filter(|f| f.relation == "HAS_CALL")
                .map(|f| f.object.clone())
                .collect::<Vec<_>>();
            for fact in &mut self.ir.facts[first..] {
                if inventories::behavior_relation(&fact.relation) {
                    fact.attrs
                        .insert("execution".into(), to_raw_value(state).expect("execution"));
                }
            }
            for call in calls {
                self.set(&call, "execution", state.clone().into());
            }
        }
        for (subject, name, evidence) in std::mem::take(&mut self.declarations.bases) {
            self.add(&subject, "BASE_NAME", &name, &evidence, json!({}));
        }
        for (subject, base, scope) in std::mem::take(&mut self.declarations.base_values) {
            let name = self.text(Some(base));
            if let Some(binding) = self.resolve(&name, &scope) {
                self.add(
                    &subject,
                    "BASE_VALUE",
                    &binding,
                    &self.evidence(base),
                    json!({"name":name,"basis":"lexical-base-syntax"}),
                );
            }
        }
        for (subject, name, evidence) in std::mem::take(&mut self.declarations.annotations) {
            let name = name.trim_matches([':', ' ']);
            if self.positions.contains_key(&subject) {
                self.set(&subject, "native_type", name.into());
            }
            self.add(&subject, "TYPE_NAME", name, &evidence, json!({}));
        }
        if self.root.has_error() {
            self.ir
                .diagnostics
                .push("parse errors: semantic absence is unknown".into());
            self.ir.capabilities.remove("declarations");
        }
        self.cpp_initializer_values();
        self.constructor_inventory();
        self.syntax_effects();
        let receivers = self
            .ir
            .facts
            .iter()
            .filter(|f| f.relation == "INSTANCE_RECEIVER")
            .map(|f| f.subject.clone())
            .collect::<BTreeSet<_>>();
        let types = self
            .ir
            .entities
            .iter()
            .filter(|(_, e)| {
                matches!(e.kind.as_str(), "CLASS" | "INTERFACE") && !receivers.contains(&e.id)
            })
            .map(|(_, e)| e.id.clone())
            .collect::<Vec<_>>();
        for id in types {
            self.add(
                &id,
                "INSTANCE_RECEIVER",
                &format!("{id}/THIS"),
                "",
                json!({"basis":"instance-relative"}),
            );
        }
        Ok(self.ir)
    }
}
pub(super) fn lower(
    catalog: &GrammarCatalog,
    language: Language,
    source: &[u8],
    path: &str,
) -> Result<StructuralIr, LoweringError> {
    super::admit(language)?;
    let tree = catalog.syntax(language, source, path)?;
    Unit::new(tree.root(), source, language, path).finish()
}
pub(super) fn syntax_view(
    catalog: &GrammarCatalog,
    language: Language,
    source: &[u8],
    path: &str,
) -> Result<StructuralIr, LoweringError> {
    super::admit(language)?;
    let tree = catalog.syntax(language, source, path)?;
    let mut unit = Unit::new(tree.root(), source, language, path);
    unit.collect_declarations();
    let used = unit.owners.nodes.values().collect::<BTreeSet<_>>();
    unit.ir.entities.retain(|(id, _)| used.contains(id));
    for (_, entity) in &mut unit.ir.entities {
        entity.attrs.retain(|key, _| {
            matches!(
                key.as_str(),
                "language" | "native_kind" | "start_byte" | "end_byte"
            )
        });
    }
    unit.ir.facts.clear();
    unit.ir.relations.clear();
    unit.ir.capabilities = ["syntax".into()].into_iter().collect();
    for (node, role) in source::descendants_with_roles(tree.root()) {
        super::operations::project(&mut unit.ir, node, role, &unit.owners, source, language);
    }
    if tree.root().has_error() {
        unit.ir
            .diagnostics
            .push("parse errors: semantic absence is unknown".into());
    }
    lexical_execution(&mut unit.ir, tree.root().has_error())?;
    Ok(unit.ir)
}

#[cfg(test)]
mod declaration_contract {
    use super::*;
    use flate2::read::GzDecoder;
    use std::{io::Read, path::PathBuf};
    #[test]
    fn original_declaration_phase_preserves_complete_metadata_and_fact_order() {
        let bytes = include_bytes!("../../../tests/fixtures/source-frontend-reference.json.gz");
        let mut text = String::new();
        GzDecoder::new(&bytes[..])
            .read_to_string(&mut text)
            .unwrap();
        let corpus: Value = serde_json::from_str(&text).unwrap();
        let catalog = GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap();
        let mut errors = Vec::new();
        for case in corpus["cases"].as_array().unwrap() {
            let language: Language = serde_json::from_value(case["language"].clone()).unwrap();
            let source: Vec<u8> = serde_json::from_value(case["source"].clone()).unwrap();
            let path = case["path"].as_str().unwrap();
            let tree = catalog.syntax(language, &source, path).unwrap();
            let mut unit = Unit::new(tree.root(), &source, language, path);
            unit.collect_declarations();
            let actual = serde_json::to_value(unit.ir).unwrap();
            if actual != case["declared"] {
                errors.push(case["name"].as_str().unwrap().to_owned());
            }
        }
        assert!(errors.is_empty(), "declaration mismatches: {errors:?}");
    }
}
