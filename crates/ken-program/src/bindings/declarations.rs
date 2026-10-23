//! Declaration syntax owns scope, visibility and initialization policy.
use super::{Bindings, Declaration};
use crate::{ProgramError, Symbol, attributes as attr, kinds, parse_type};
use std::collections::BTreeSet;
impl Bindings<'_, '_> {
    pub(super) fn add(&mut self, request: Declaration) -> Result<(), ProgramError> {
        let Declaration {
            name,
            target,
            mut scope,
            kind,
            container,
            hoisted,
            unique,
            implicit,
        } = request;
        if name.is_empty() || name.starts_with("anonymous@") || name == "_" {
            return Ok(());
        }
        if self.ir.language == "python" {
            match self
                .overrides
                .get(&(self.local_scope(scope), name.clone()))
                .map(String::as_str)
            {
                Some("global") => scope = 0,
                Some("nonlocal") => return Ok(()),
                _ => {}
            }
        }
        let key = (scope, name.clone());
        if unique && self.by_name.get(&key).is_some_and(|v| !v.is_empty()) {
            return Ok(());
        }
        self.declarations.insert(target);
        let node = self.program.nodes[target].clone();
        let outer = &self.program.nodes[container];
        let mut tokens: BTreeSet<_> = attr::tokens(&self.raw[outer.source_id.as_str()].attrs)?
            .into_iter()
            .collect();
        for i in self.ancestry(container) {
            let parent = &self.program.nodes[i];
            if parent.scope != outer.scope
                || !matches!(
                    parent.kind.as_str(),
                    "variable_declaration" | "assignment" | "expression_statement"
                )
            {
                break;
            }
            tokens.extend(attr::tokens(&self.raw[parent.source_id.as_str()].attrs)?);
        }
        let mutable = (kind == "variable").then(|| {
            if self.ir.language == "rust" {
                tokens.contains("mut")
            } else {
                !["const", "final", "readonly"]
                    .iter()
                    .any(|t| tokens.contains(*t))
            }
        });
        let mut initializer_end = self.children[container]
            .iter()
            .map(|&i| &self.program.nodes[i])
            .filter(|n| matches!(n.native_role.as_str(), "right" | "value"))
            .map(|n| n.end)
            .max();
        if kind == "variable" && matches!(self.ir.language.as_str(), "javascript" | "typescript") {
            initializer_end = Some(if hoisted {
                0
            } else {
                initializer_end.unwrap_or(outer.end)
            });
        }
        if matches!(
            kind,
            "parameter" | "callable" | "type" | "import" | "namespace"
        ) {
            initializer_end = Some(if hoisted || kind == "parameter" {
                0
            } else {
                outer.end
            });
        }
        let mut flags = BTreeSet::new();
        if self.ancestry(container).into_iter().any(|i| {
            let p = &self.program.nodes[i];
            matches!(
                p.kind.as_str(),
                "if" | "for" | "while" | "loop" | "try" | "catch" | "match" | "conditional"
            ) && (p.scope == outer.scope || p.kind != "callable")
        }) {
            flags.insert("conditional_init".into());
        }
        if implicit {
            flags.insert("implicit".into());
        }
        if kind == "import" {
            flags.insert("external".into());
        }
        if hoisted {
            flags.insert("hoisted".into());
        }
        if matches!(self.ir.language.as_str(), "javascript" | "typescript")
            && kind == "variable"
            && !hoisted
        {
            flags.insert("tdz".into());
        }
        let entity = self
            .entities
            .get(&(node.start, node.end))
            .or_else(|| self.entities.get(&(outer.start, outer.end)))
            .copied();
        let mut annotation = String::new();
        if let Some(entity) = entity {
            annotation = attr::text(&entity.attrs, "native_type", "")?;
            if attr::truth(&entity.attrs, "receiver")? {
                flags.insert("receiver".into());
            }
        }
        if annotation.is_empty()
            && let Some(&i) = self.children[container]
                .iter()
                .find(|&&i| self.program.nodes[i].native_role == "type")
        {
            annotation = self.program.nodes[i].text.clone();
            if annotation.is_empty() {
                annotation = self
                    .descendants(i)
                    .map(|i| self.program.nodes[i].text.as_str())
                    .collect();
            }
        }
        let type_kind = if annotation.is_empty() {
            "unknown".into()
        } else {
            parse_type(&annotation, &self.ir.language).kind
        };
        let mut visible = if hoisted || self.ir.language == "python" {
            0
        } else {
            node.start
        };
        if self.ir.language == "rust" && kind == "variable" {
            visible = outer.end;
        }
        if flags.contains("tdz") {
            visible = 0;
        }
        let parameter_kind = if let Some(entity) = entity.filter(|_| kind == "parameter") {
            attr::text(
                &entity.attrs,
                if entity.attrs.contains_key("parameter_kind") {
                    "parameter_kind"
                } else {
                    "kind_"
                },
                "",
            )?
        } else {
            String::new()
        };
        let native_position = if let Some(entity) = entity.filter(|_| kind == "parameter") {
            attr::get(&entity.attrs, "position")?.and_then(|v| v.as_i64())
        } else {
            None
        };
        let symbol = Symbol {
            id: self.program.symbols.len(),
            name: name.clone(),
            scope,
            declaration: target,
            kind: kind.into(),
            source_id: entity.map_or_else(|| node.source_id.clone(), |e| e.id.clone()),
            visible_from: visible,
            initialized_from: initializer_end,
            type_kind: type_kind.clone(),
            native_type: annotation,
            mutable,
            flags: flags.into_iter().collect(),
            position: None,
            parameter_kind,
            native_position,
        };
        self.by_name.entry(key).or_default().push(symbol.id);
        self.program.symbols.push(symbol);
        if node.kind == "identifier" {
            let node = &mut self.program.nodes[target];
            node.kind = "binding_declaration".into();
            node.category = "declaration".into();
            node.name = name;
            node.type_kind = type_kind;
        }
        Ok(())
    }
    pub(super) fn declare(&mut self) -> Result<(), ProgramError> {
        for node in self.program.nodes.clone() {
            match node.kind.as_str() {
                "callable" | "type_declaration" | "namespace" => {
                    if node.flags.iter().any(|f| f == "closure") && node.name.is_empty() {
                        continue;
                    }
                    let scope = if matches!(
                        node.native_kind.as_str(),
                        "function_expression" | "generator_function"
                    ) {
                        self.introduced.get(&node.id).copied().unwrap_or(node.scope)
                    } else {
                        node.scope
                    };
                    self.declarations.extend(
                        self.children[node.id]
                            .iter()
                            .copied()
                            .filter(|&i| self.program.nodes[i].native_role == "name"),
                    );
                    let kind = match node.kind.as_str() {
                        "callable" => "callable",
                        "type_declaration" => "type",
                        _ => "namespace",
                    };
                    let mut declaration =
                        Declaration::new(node.name, node.id, scope, kind, node.id);
                    declaration.hoisted = self.hoisted_language();
                    declaration.unique = false;
                    self.add(declaration)?;
                }
                "parameter" => {
                    let first = self.children[node.id].iter().copied().find(|&i| {
                        matches!(
                            self.program.nodes[i].native_role.as_str(),
                            "name" | "pattern"
                        )
                    });
                    let mut targets = self.targets(first.unwrap_or(node.id));
                    if !node.name.is_empty() && targets.is_empty() {
                        targets.push(node.id);
                    }
                    for target in targets {
                        let mut declaration = Declaration::new(
                            if node.name.is_empty() {
                                self.program.nodes[target].text.clone()
                            } else {
                                node.name.clone()
                            },
                            target,
                            node.scope,
                            "parameter",
                            node.id,
                        );
                        declaration.hoisted = true;
                        self.add(declaration)?;
                    }
                    self.declarations.insert(node.id);
                }
                "alias_pattern" if self.ir.language == "python" => {
                    let children: Vec<_> = self.children[node.id]
                        .iter()
                        .copied()
                        .filter(|&i| self.program.nodes[i].native_role == "alias")
                        .collect();
                    for child in children {
                        for target in self.targets(child) {
                            let mut d = Declaration::new(
                                self.program.nodes[target].text.clone(),
                                target,
                                self.local_scope(node.scope),
                                "variable",
                                node.id,
                            );
                            d.implicit = true;
                            self.add(d)?;
                        }
                    }
                }
                "variable_declaration"
                    if kinds::declarator(&node.native_kind)
                        || !self
                            .descendants(node.id)
                            .any(|i| kinds::declarator(&self.program.nodes[i].native_kind)) =>
                {
                    let candidates: Vec<_> = self.children[node.id]
                        .iter()
                        .copied()
                        .filter(|&i| {
                            matches!(
                                self.program.nodes[i].native_role.as_str(),
                                "name" | "pattern" | "declarator" | "left"
                            )
                        })
                        .collect();
                    for child in candidates {
                        for target in self.targets(child) {
                            let mut scope = node.scope;
                            let mut tokens: BTreeSet<_> =
                                attr::tokens(&self.raw[node.source_id.as_str()].attrs)?
                                    .into_iter()
                                    .collect();
                            for i in self.ancestry(node.id) {
                                let parent = &self.program.nodes[i];
                                if !matches!(
                                    parent.kind.as_str(),
                                    "variable_declaration" | "expression_statement"
                                ) {
                                    break;
                                }
                                tokens.extend(attr::tokens(
                                    &self.raw[parent.source_id.as_str()].attrs,
                                )?);
                            }
                            let hoisted =
                                matches!(self.ir.language.as_str(), "javascript" | "typescript")
                                    && tokens.contains("var");
                            if hoisted {
                                scope = self.local_scope(scope);
                            }
                            let mut d = Declaration::new(
                                self.program.nodes[target].text.clone(),
                                target,
                                scope,
                                "variable",
                                node.id,
                            );
                            d.hoisted = hoisted;
                            d.unique = self.ir.language != "rust";
                            self.add(d)?;
                        }
                    }
                }
                "assignment" if matches!(self.ir.language.as_str(), "python" | "ruby") => {
                    let children: Vec<_> = self.children[node.id]
                        .iter()
                        .copied()
                        .filter(|&i| {
                            matches!(self.program.nodes[i].native_role.as_str(), "left" | "name")
                        })
                        .collect();
                    for child in children {
                        for target in self.targets(child) {
                            let mut d = Declaration::new(
                                self.program.nodes[target].text.clone(),
                                target,
                                self.local_scope(node.scope),
                                "variable",
                                node.id,
                            );
                            d.implicit = true;
                            self.add(d)?;
                        }
                    }
                }
                "for" | "comprehension_clause" => {
                    let children: Vec<_> = self.children[node.id]
                        .iter()
                        .copied()
                        .filter(|&i| {
                            matches!(
                                self.program.nodes[i].native_role.as_str(),
                                "left" | "name" | "pattern" | "declarator"
                            )
                        })
                        .collect();
                    for child in children {
                        for target in self.targets(child) {
                            let mut scope =
                                self.introduced.get(&node.id).copied().unwrap_or(node.scope);
                            if matches!(self.ir.language.as_str(), "python" | "ruby")
                                && self.program.scopes[scope].kind != "comprehension"
                            {
                                scope = self.local_scope(scope);
                            }
                            let mut d = Declaration::new(
                                self.program.nodes[target].text.clone(),
                                target,
                                scope,
                                "variable",
                                node.id,
                            );
                            d.implicit = matches!(self.ir.language.as_str(), "python" | "ruby");
                            self.add(d)?;
                        }
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }
}
