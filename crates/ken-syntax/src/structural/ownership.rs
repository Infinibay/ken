//! Declaration identity and lexical ownership, independent of semantic projection.
use super::{
    attributes,
    source::{self, field, text},
    vocabulary::vocabulary,
};
use crate::{Language, SyntaxNode};
use ken_program::Entity;
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};

pub(super) struct Ownership {
    pub nodes: BTreeMap<usize, String>,
    pub entities: Vec<(String, Entity)>,
    pub prototypes: BTreeSet<usize>,
    pub functions: BTreeSet<usize>,
    names: BTreeMap<(String, String), String>,
    positions: BTreeMap<String, usize>,
}
impl Ownership {
    pub fn collect(root: SyntaxNode<'_>, language: Language, source: &[u8], path: &str) -> Self {
        let module = format!("{path}::module");
        let mut index = Self {
            nodes: BTreeMap::new(),
            entities: vec![(
                module.clone(),
                Entity {
                    id: module.clone(),
                    kind: "MODULE".into(),
                    name: path.into(),
                    path: path.into(),
                    line: 1,
                    end_line: (root.end_point()[0] + 1) as i64,
                    attrs: Default::default(),
                },
            )],
            prototypes: BTreeSet::new(),
            functions: BTreeSet::new(),
            names: BTreeMap::new(),
            positions: BTreeMap::from([(module.clone(), 0)]),
        };
        let v = vocabulary();
        let mut pending = vec![(root, module.clone(), String::new())];
        while let Some((node, mut scope, mut cls)) = pending.pop() {
            let kind = node.kind();
            let prototype = (language == Language::Cpp && !cls.is_empty() && scope == cls)
                .then(|| source::prototype_origin(node))
                .flatten();
            if let Some(origin) = prototype {
                index.prototypes.insert(origin.id());
            }
            if v.types.contains(kind) && !(kind == "enum_specifier" && node.field("body").is_none())
            {
                let type_node = node.field("type");
                if !(kind == "type_spec"
                    && type_node
                        .is_some_and(|n| !matches!(n.kind(), "struct_type" | "interface_type")))
                {
                    let name = source::name(node, source);
                    let type_kind = if kind.contains("interface")
                        || kind == "trait_item"
                        || type_node.is_some_and(|n| n.kind() == "interface_type")
                    {
                        "INTERFACE"
                    } else {
                        "CLASS"
                    };
                    let expression = kind == "class"
                        && matches!(language, Language::JavaScript | Language::TypeScript);
                    let declared = index.entity(type_kind, &name, &scope, node, language, path);
                    index.names.insert(
                        (
                            if expression {
                                declared.clone()
                            } else {
                                scope.clone()
                            },
                            name,
                        ),
                        declared.clone(),
                    );
                    cls = declared.clone();
                    scope = declared;
                }
            } else if v.file_declarations.contains(kind) && scope == module {
                let specs = if let Some(spec) = v.spec_declarations.get(kind) {
                    node.named_children()
                        .into_iter()
                        .filter(|c| c.kind() == spec)
                        .collect()
                } else {
                    vec![node]
                };
                for spec in specs {
                    for name in source::declared_names(spec) {
                        if matches!(name.kind(), "identifier" | "field_identifier") {
                            index.storage(&text(Some(name), source), &scope, name, language, path);
                        }
                    }
                }
            } else if kind == "impl_item" {
                let mut target = node.field("type");
                if target.is_some_and(|n| n.kind() == "generic_type") {
                    target = target.and_then(|n| n.field("type"));
                }
                cls = target
                    .filter(|n| n.kind() == "type_identifier")
                    .and_then(|n| {
                        index
                            .names
                            .get(&(scope.clone(), text(Some(n), source)))
                            .cloned()
                    })
                    .unwrap_or_default();
                if !cls.is_empty() {
                    scope = cls.clone();
                }
            } else if v.functions.contains(kind) || prototype.is_some() {
                if let Some(receiver) = node.field("receiver") {
                    let parameter = receiver.named_children().first().copied();
                    let mut target = text(field(parameter, &["type"]), source)
                        .trim_end()
                        .to_owned();
                    if target.ends_with(']')
                        && let Some(open) = target.rfind('[')
                    {
                        target.truncate(open);
                    }
                    let target = target.trim_start_matches('*').trim().to_owned();
                    cls = index
                        .names
                        .get(&(module.clone(), target))
                        .cloned()
                        .unwrap_or_default();
                    if !cls.is_empty() {
                        scope = cls.clone();
                    }
                }
                let mut name = source::name(node, source);
                if language == Language::Cpp
                    && let Some((_, named)) = source::function_parts(node)
                {
                    name = text(Some(named), source);
                }
                index.functions.insert(node.id());
                let function = index.entity("CALLABLE", &name, &scope, node, language, path);
                index.names.insert((scope.clone(), name), function.clone());
                // Rust impl ownership consults lexical names, including parameters.
                // Preserve those bindings even though full parameter metadata belongs
                // to the later declaration projection.
                if language == Language::Rust {
                    for parameter in source::parameters(node)
                        .into_iter()
                        .flat_map(|p| p.named_children())
                    {
                        let name = source::parameter_name(parameter, source);
                        let id =
                            index.entity("PARAMETER", &name, &function, parameter, language, path);
                        index.names.insert((function.clone(), name), id);
                    }
                }
                scope = function;
            }
            index.nodes.insert(node.id(), scope.clone());
            let mut children = node.named_children();
            children.sort_by_key(|c| {
                usize::from(!v.types.contains(c.kind()) && c.kind() != "type_declaration")
            });
            pending.extend(
                children
                    .into_iter()
                    .rev()
                    .map(|child| (child, scope.clone(), cls.clone())),
            );
        }
        index
    }
    fn entity(
        &mut self,
        kind: &str,
        name: &str,
        scope: &str,
        node: SyntaxNode<'_>,
        language: Language,
        path: &str,
    ) -> String {
        let mut key = format!("{scope}/{kind}:{name}");
        if matches!(kind, "CALLABLE" | "PARAMETER") || (kind == "CLASS" && node.kind() == "class") {
            key.push_str(&format!("@{}", node.start_byte()));
        }
        if !self.positions.contains_key(&key) {
            let entity = Entity {
                id: key.clone(),
                kind: kind.into(),
                name: name.into(),
                path: path.into(),
                line: (node.start_point()[0] + 1) as i64,
                end_line: (node.end_point()[0] + 1) as i64,
                attrs: attributes(
                    json!({"native_kind":node.kind(),"language":language.as_str(),"start_byte":node.start_byte(),"end_byte":node.end_byte()}),
                ),
            };
            self.positions.insert(key.clone(), self.entities.len());
            self.entities.push((key.clone(), entity));
        }
        key
    }
    fn storage(
        &mut self,
        name: &str,
        scope: &str,
        node: SyntaxNode<'_>,
        language: Language,
        path: &str,
    ) {
        let binding = (scope.into(), name.into());
        if !self.names.contains_key(&binding) {
            let id = self.entity("STORAGE", name, scope, node, language, path);
            self.names.insert(binding, id);
        }
    }
    pub fn owner_entities(mut self) -> Vec<(String, Entity)> {
        let used = self.nodes.values().collect::<BTreeSet<_>>();
        self.entities.retain(|(id, _)| used.contains(id));
        self.entities
    }
}
