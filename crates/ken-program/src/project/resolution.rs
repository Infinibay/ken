//! Lexical and explicit-import nominal lookup preserves shadowing and ambiguity.
use super::*;
impl Project {
    pub(super) fn index_symbols(&mut self) {
        for (_, e) in &self.graph.entities {
            if matches!(
                e.kind.as_str(),
                "STORAGE" | "PARAMETER" | "CALLABLE" | "CLASS" | "INTERFACE"
            ) {
                let scope = e.id.rsplit_once('/').map_or(e.id.as_str(), |(p, _)| p);
                self.bindings
                    .entry((scope.into(), e.name.clone()))
                    .or_default()
                    .push(e.id.clone());
            }
            if !matches!(e.kind.as_str(), "CLASS" | "INTERFACE") {
                continue;
            }
            self.types.insert(e.id.clone());
            if !self.flag(&e.id, "expression") {
                self.class_names
                    .entry((e.path.clone(), e.name.clone()))
                    .or_default()
                    .push(e.id.clone());
            }
            let module = format!("{}::module", e.path);
            if e.id.rsplit_once('/').is_some_and(|(p, _)| p == module) {
                if let Some(package) = self.imports.java_packages.get(&e.path) {
                    let qualified = if package.is_empty() {
                        e.name.clone()
                    } else {
                        format!("{package}.{}", e.name)
                    };
                    self.java_types
                        .entry(qualified)
                        .or_default()
                        .push(e.id.clone());
                }
                if let Some(package) = self.imports.go_packages.get(&e.path) {
                    self.go_types
                        .entry((package.clone(), e.name.clone()))
                        .or_default()
                        .push(e.id.clone());
                }
            }
        }
    }
    pub(super) fn resolve(&self, name: &str, context: &str) -> Option<String> {
        if !self.positions.contains_key(context) {
            return None;
        }
        let stripped = name.trim_matches([':', ' ', '&', '*', '?', '\'']);
        let stripped = stripped.strip_prefix("mut ").unwrap_or(stripped);
        let name = regex(r"\A(?:dyn|impl)\s+").replace(stripped, "");
        let name = trim(&name);
        let entity = self.entity(context);
        let origin = &entity.path;
        let rust = self.attr(context, "language") == "rust";
        let mut scope = context;
        while !scope.is_empty() {
            if let Some(&position) = self.positions.get(scope) {
                let container = &self.graph.entities[position].1;
                if self.flag(scope, "expression") && container.name == name {
                    return Some(container.id.clone());
                }
                if rust
                    && self
                        .attr(scope, "type_parameters")
                        .as_array()
                        .is_some_and(|v| v.iter().any(|v| v == name))
                {
                    return None;
                }
            }
            if entity.kind == "CALL" && !self.flag(context, "construction") {
                let bindings = self.bindings.get(&(scope.into(), name.into()));
                let shadowed = bindings.into_iter().flatten().any(|id| {
                    matches!(
                        self.entity(id).kind.as_str(),
                        "STORAGE" | "PARAMETER" | "CALLABLE"
                    )
                });
                let constructor = bindings
                    .into_iter()
                    .flatten()
                    .any(|id| self.entity(id).kind == "CALLABLE" && self.flag(id, "constructor"));
                if shadowed && !constructor {
                    return None;
                }
            }
            for kind in ["CLASS", "INTERFACE"] {
                let candidate = format!("{scope}/{kind}:{name}");
                if self.positions.contains_key(&candidate) {
                    return Some(candidate);
                }
            }
            let Some((parent, _)) = scope.rsplit_once('/') else {
                break;
            };
            scope = parent;
        }
        if let Some(package) = self.imports.go_packages.get(origin) {
            let options = self.go_types.get(&(package.clone(), name.into()));
            return options
                .filter(|v| v.len() == 1 && !package.1.is_empty())
                .map(|v| v[0].clone());
        }
        if let Some(package) = self.imports.java_packages.get(origin) {
            let options = if name.contains('.') {
                self.java_types.get(name)
            } else if let Some(imports) = self
                .imports
                .java_imports
                .get(&(origin.clone(), name.into()))
            {
                if imports.len() != 1 {
                    return None;
                }
                self.java_types.get(imports.first().unwrap())
            } else {
                let qualified = if package.is_empty() {
                    name.to_owned()
                } else {
                    format!("{package}.{name}")
                };
                self.java_types.get(&qualified)
            };
            return options.filter(|v| v.len() == 1).map(|v| v[0].clone());
        }
        let key = self
            .imports
            .members
            .get(&(origin.clone(), name.into()))
            .cloned()
            .unwrap_or_else(|| (origin.clone(), name.into()));
        self.class_names
            .get(&key)
            .filter(|v| v.len() == 1)
            .map(|v| v[0].clone())
    }
}
pub(super) fn normalized(annotation: &str) -> String {
    let stripped = annotation.trim_matches([':', ' ', '&', '*', '?', '\'']);
    let text = stripped.strip_prefix("mut ").unwrap_or(stripped);
    match text {
        "string" | "String" | "str" => "str",
        "int" | "Int" | "i32" | "i64" | "int32" | "int64" => "int",
        "number" => "number",
        "float" | "double" => "float",
        "bool" | "boolean" | "Boolean" => "bool",
        "void" => "void",
        "None" | "NoneType" => "none",
        "any" | "Any" | "object" | "" => "unknown",
        _ => text,
    }
    .into()
}
pub(super) fn rust_denoted(spelling: &str) -> String {
    if let Some(m) = full(r"(?:Box|Rc|Arc)\s*<\s*(.+?)\s*>", trim(spelling)) {
        regex(r"\A(?:dyn|impl)\s+")
            .replace(trim(&m[1]), "")
            .into_owned()
    } else {
        spelling.into()
    }
}
