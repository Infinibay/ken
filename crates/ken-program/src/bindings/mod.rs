//! Declaration collection, import syntax and occurrence resolution share one model.
mod declarations;
mod imports;
use crate::{
    Entity, Environment, Operation, Program, ProgramError, Reference, StructuralIr,
    attributes as attr,
};
use std::collections::{BTreeMap, BTreeSet};
struct Bindings<'ir, 'p> {
    ir: &'ir StructuralIr,
    program: &'p mut Program,
    raw: BTreeMap<&'ir str, &'ir Operation>,
    children: Vec<Vec<usize>>,
    introduced: BTreeMap<usize, usize>,
    entities: BTreeMap<(i64, i64), &'ir Entity>,
    declarations: BTreeSet<usize>,
    by_name: BTreeMap<(usize, String), Vec<usize>>,
    overrides: BTreeMap<(usize, String), String>,
}
struct Declaration {
    name: String,
    target: usize,
    scope: usize,
    kind: &'static str,
    container: usize,
    hoisted: bool,
    unique: bool,
    implicit: bool,
}
impl Declaration {
    fn new(
        name: String,
        target: usize,
        scope: usize,
        kind: &'static str,
        container: usize,
    ) -> Self {
        Self {
            name,
            target,
            scope,
            kind,
            container,
            hoisted: false,
            unique: true,
            implicit: false,
        }
    }
}
pub(crate) fn bind(ir: &StructuralIr, program: &mut Program) -> Result<(), ProgramError> {
    let mut children = vec![vec![]; program.nodes.len()];
    for node in &program.nodes {
        if let Some(parent) = node.parent {
            children[parent].push(node.id);
        }
    }
    let raw = ir.operations.iter().map(|o| (o.id.as_str(), o)).collect();
    let introduced = program.scopes.iter().map(|s| (s.node, s.id)).collect();
    let mut entities = BTreeMap::new();
    for (_, entity) in &ir.entities {
        if matches!(
            entity.kind.as_str(),
            "STORAGE" | "PARAMETER" | "CALLABLE" | "CLASS" | "INTERFACE" | "TRAIT"
        ) && let (Some(start), Some(end)) = (
            attr::get(&entity.attrs, "start_byte")?.and_then(|v| v.as_i64()),
            attr::get(&entity.attrs, "end_byte")?.and_then(|v| v.as_i64()),
        ) {
            entities.insert((start, end), entity);
        }
    }
    let mut bindings = Bindings {
        ir,
        program,
        raw,
        children,
        introduced,
        entities,
        declarations: BTreeSet::new(),
        by_name: BTreeMap::new(),
        overrides: BTreeMap::new(),
    };
    bindings.directives();
    bindings.declare()?;
    bindings.imports()?;
    bindings.parameter_positions();
    bindings.uncertain_lifetimes();
    bindings.references()?;
    Ok(())
}
impl Bindings<'_, '_> {
    fn descendants(&self, i: usize) -> std::ops::Range<usize> {
        i + 1..self.program.nodes[i].subtree_end
    }
    fn ancestry(&self, i: usize) -> Vec<usize> {
        let mut result = vec![];
        let mut parent = self.program.nodes[i].parent;
        while let Some(i) = parent {
            result.push(i);
            parent = self.program.nodes[i].parent;
        }
        result
    }
    fn local_scope(&self, mut scope: usize) -> usize {
        while let Some(parent) = self.program.scopes[scope].parent {
            if matches!(
                self.program.scopes[scope].kind.as_str(),
                "callable" | "module" | "type"
            ) {
                break;
            }
            scope = parent;
        }
        scope
    }
    fn hoisted_language(&self) -> bool {
        matches!(
            self.ir.language.as_str(),
            "javascript" | "typescript" | "java" | "csharp" | "go" | "rust"
        )
    }
    fn targets(&self, i: usize) -> Vec<usize> {
        let mut result = vec![];
        let mut pending = vec![i];
        while let Some(i) = pending.pop() {
            let node = &self.program.nodes[i];
            if matches!(
                node.native_kind.as_str(),
                "identifier"
                    | "name"
                    | "field_identifier"
                    | "property_identifier"
                    | "shorthand_property_identifier_pattern"
                    | "constant"
                    | "instance_variable"
                    | "global_variable"
                    | "class_variable"
            ) {
                result.push(i);
                continue;
            }
            if matches!(
                node.kind.as_str(),
                "member" | "index" | "call" | "literal" | "type_name"
            ) {
                continue;
            }
            let mut candidates: Vec<_> = self.children[i]
                .iter()
                .copied()
                .filter(|&c| {
                    matches!(
                        self.program.nodes[c].native_role.as_str(),
                        "name" | "pattern" | "declarator" | "left"
                    )
                })
                .collect();
            if candidates.is_empty() {
                candidates = self.children[i]
                    .iter()
                    .copied()
                    .filter(|&c| {
                        let n = &self.program.nodes[c];
                        !matches!(n.kind.as_str(), "type_name" | "modifier")
                            && !matches!(n.native_role.as_str(), "type" | "value" | "right")
                    })
                    .collect();
            }
            pending.extend(candidates.into_iter().rev());
        }
        result
    }
    fn directives(&mut self) {
        for node in &self.program.nodes {
            if matches!(node.kind.as_str(), "global" | "nonlocal") {
                for i in self.descendants(node.id) {
                    let child = &self.program.nodes[i];
                    if child.kind == "identifier" {
                        self.overrides.insert(
                            (self.local_scope(node.scope), child.text.clone()),
                            node.kind.clone(),
                        );
                        self.declarations.insert(i);
                    }
                }
            }
        }
        for scope in &mut self.program.scopes {
            scope.global_names = self
                .overrides
                .iter()
                .filter(|((id, _), kind)| *id == scope.id && *kind == "global")
                .map(|((_, name), _)| name.clone())
                .collect();
            scope.nonlocal_names = self
                .overrides
                .iter()
                .filter(|((id, _), kind)| *id == scope.id && *kind == "nonlocal")
                .map(|((_, name), _)| name.clone())
                .collect();
        }
    }
    fn parameter_positions(&mut self) {
        let mut positions = BTreeMap::new();
        for symbol in &mut self.program.symbols {
            if symbol.kind != "parameter" {
                continue;
            }
            let count = positions.entry(symbol.scope).or_insert(0);
            symbol.position = (!symbol.flags.iter().any(|f| f == "receiver")).then_some(*count);
            if symbol.position.is_some() {
                *count += 1;
            }
        }
    }
    fn uncertain_lifetimes(&mut self) {
        let mut uncertain = BTreeSet::new();
        let mut deleted = BTreeSet::new();
        for node in &self.program.nodes {
            if node.kind == "delete" {
                deleted.extend(
                    self.descendants(node.id)
                        .filter(|&i| self.program.nodes[i].kind == "identifier")
                        .map(|i| self.program.nodes[i].text.clone()),
                );
            }
            if node.kind == "call"
                && self.children[node.id]
                    .iter()
                    .any(|&i| matches!(self.program.nodes[i].text.as_str(), "exec" | "eval"))
            {
                uncertain.insert(self.local_scope(node.scope));
            }
        }
        let flags: Vec<_> = self
            .program
            .symbols
            .iter()
            .map(|s| deleted.contains(&s.name) || uncertain.contains(&self.local_scope(s.scope)))
            .collect();
        for (symbol, uncertain) in self.program.symbols.iter_mut().zip(flags) {
            if uncertain {
                symbol.flags.push("uncertain_lifetime".into());
                symbol.flags.sort();
                symbol.flags.dedup();
            }
        }
    }
    fn references(&mut self) -> Result<(), ProgramError> {
        let env = Environment::new(self.program);
        let mut references = vec![];
        for node in &self.program.nodes {
            if node.kind != "identifier" || self.declarations.contains(&node.id) {
                continue;
            }
            let parent = node.parent.map(|i| &self.program.nodes[i]);
            if parent.is_some_and(|p| {
                p.kind == "package" || p.argument_kind == "named" && node.native_role == "name"
            }) {
                continue;
            }
            if node.text.is_empty()
                || matches!(node.native_role.as_str(), "type" | "label")
                || parent.is_some_and(|p| {
                    matches!(
                        p.kind.as_str(),
                        "type_name" | "modifier" | "import" | "export"
                    )
                })
            {
                continue;
            }
            if parent.is_some_and(|p| matches!(p.kind.as_str(), "member" | "qualified_reference"))
                && matches!(
                    node.native_role.as_str(),
                    "attribute" | "field" | "property" | "name"
                )
            {
                references.push(Reference {
                    node: node.id,
                    name: node.text.clone(),
                    scope: node.scope,
                    mode: "member".into(),
                    symbol: None,
                    status: "unknown".into(),
                    reason: "member_dispatch_required".into(),
                    availability: "unknown".into(),
                });
                continue;
            }
            let mut mode = "read";
            if let Some(parent) = parent {
                if matches!(parent.kind.as_str(), "assignment" | "variable_declaration")
                    && node.role == "target"
                {
                    mode = if matches!(parent.operator.as_str(), "" | "=") {
                        "write"
                    } else {
                        "read_write"
                    };
                }
                if parent.kind == "update" {
                    mode = "read_write";
                }
            }
            let resolved = env.resolve(&node.text, node.scope as i64, node.start)?;
            references.push(Reference {
                node: node.id,
                name: node.text.clone(),
                scope: node.scope,
                mode: mode.into(),
                symbol: resolved.symbol,
                status: resolved.status,
                reason: resolved.reason,
                availability: resolved.availability,
            });
        }
        self.program.references = references;
        Ok(())
    }
}
