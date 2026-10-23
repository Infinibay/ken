//! Import syntax introduces local names without guessing exported module identity.
use super::{Bindings, Declaration};
use crate::{ProgramError, attributes as attr};
impl Bindings<'_, '_> {
    pub(super) fn imports(&mut self) -> Result<(), ProgramError> {
        for node in self.program.nodes.clone() {
            if node.kind != "import"
                || self
                    .ancestry(node.id)
                    .iter()
                    .any(|&i| self.program.nodes[i].kind == "import")
            {
                continue;
            }
            let ids: Vec<_> = self
                .descendants(node.id)
                .filter(|&i| self.program.nodes[i].kind == "identifier")
                .collect();
            self.declarations.extend(ids.iter().copied());
            let mut targets = vec![];
            match self.ir.language.as_str() {
                "python" => {
                    for &child in &self.children[node.id] {
                        let item = &self.program.nodes[child];
                        if item.native_role != "name" {
                            continue;
                        }
                        let aliases: Vec<_> = self
                            .descendants(child)
                            .filter(|&i| self.program.nodes[i].native_role == "alias")
                            .collect();
                        if !aliases.is_empty() {
                            targets.extend(aliases);
                        } else if let Some(first) = std::iter::once(child)
                            .chain(self.descendants(child))
                            .find(|&i| self.program.nodes[i].kind == "identifier")
                        {
                            targets.push(first);
                        }
                    }
                }
                "javascript" | "typescript" => {
                    for i in self.descendants(node.id) {
                        let item = &self.program.nodes[i];
                        if item.kind == "import_binding" {
                            let aliases: Vec<_> = self.children[i]
                                .iter()
                                .copied()
                                .filter(|&i| self.program.nodes[i].native_role == "alias")
                                .collect();
                            if !aliases.is_empty() {
                                targets.extend(aliases);
                            } else if let Some(&last) = self.children[i]
                                .iter()
                                .rev()
                                .find(|&&i| self.program.nodes[i].kind == "identifier")
                            {
                                targets.push(last);
                            }
                        } else if item.kind == "identifier"
                            && item.parent.is_some_and(|p| {
                                self.program.nodes[p].native_kind == "import_clause"
                            })
                        {
                            targets.push(i);
                        }
                    }
                }
                "java" => {
                    if !attr::tokens(&self.raw[node.source_id.as_str()].attrs)?
                        .iter()
                        .any(|t| t == "*")
                        && let Some(&last) = ids.last()
                    {
                        targets.push(last);
                    }
                }
                "csharp" => targets.extend(self.children[node.id].iter().copied().filter(|&i| {
                    self.program.nodes[i].native_role == "name"
                        && self.program.nodes[i].kind == "identifier"
                })),
                "go" => targets.extend(
                    ids.into_iter()
                        .filter(|&i| self.program.nodes[i].native_role == "name"),
                ),
                "rust" => targets = self.rust_imports(node.id),
                _ => {}
            }
            for target in targets {
                let mut d = Declaration::new(
                    self.program.nodes[target].text.clone(),
                    target,
                    node.scope,
                    "import",
                    node.id,
                );
                d.hoisted = self.hoisted_language();
                self.add(d)?;
            }
        }
        Ok(())
    }
    fn rust_imports(&self, i: usize) -> Vec<usize> {
        let item = &self.program.nodes[i];
        if item.kind == "import_binding" {
            return self.children[i]
                .iter()
                .copied()
                .filter(|&i| self.program.nodes[i].native_role == "alias")
                .collect();
        }
        if item.native_kind == "scoped_use_list" {
            return self.children[i]
                .iter()
                .copied()
                .filter(|&i| self.program.nodes[i].native_role == "list")
                .flat_map(|i| self.rust_imports(i))
                .collect();
        }
        if item.kind == "qualified_reference" {
            return self.children[i]
                .iter()
                .copied()
                .filter(|&i| self.program.nodes[i].native_role == "name")
                .collect();
        }
        if item.kind == "identifier" {
            return vec![i];
        }
        self.children[i]
            .iter()
            .flat_map(|&i| self.rust_imports(i))
            .collect()
    }
}
