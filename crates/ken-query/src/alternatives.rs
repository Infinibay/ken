//! Bounded indexed-backend alternatives, kept separate from relational lowering.
use crate::{ParseError, Result, ast::*};
use std::collections::BTreeMap;
pub fn expand_indexed_alternatives(tree: &File, query: Option<&str>) -> Result<Vec<File>> {
    crate::validation::tree(tree)?;
    let declarations: BTreeMap<_, _> = tree
        .declarations
        .iter()
        .map(|d| (d.name.clone(), d))
        .collect();
    if declarations.len() != tree.declarations.len() {
        return Err(ParseError::new("duplicate declaration", tree.span.clone()));
    }
    let queries: Vec<_> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "query" && query.is_none_or(|q| q == d.name))
        .collect();
    if queries.len() != 1 {
        return Err(ParseError::new(
            "choose exactly one query",
            tree.span.clone(),
        ));
    }
    let mut expander = Expansion {
        tree,
        declarations,
        definitions: vec![],
        variants: BTreeMap::new(),
    };
    let selected = queries[0];
    let variants = expander.clauses(&selected.clauses, &[], 0)?;
    let mut result = vec![];
    for clauses in variants {
        let mut declarations: Vec<_> = tree
            .declarations
            .iter()
            .filter(|d| !matches!(d.kind.as_str(), "query" | "pattern"))
            .cloned()
            .collect();
        declarations.extend(expander.definitions.iter().cloned());
        declarations.push(Declaration {
            kind: selected.kind.clone(),
            name: selected.name.clone(),
            span: selected.span.clone(),
            parameters: selected.parameters.clone(),
            generics: selected.generics.clone(),
            clauses,
            formula: selected.formula.clone(),
            members: selected.members.clone(),
            values: selected.values.clone(),
            implements: selected.implements.clone(),
        });
        result.push(File {
            language: tree.language.clone(),
            module: tree.module.clone(),
            imports: tree.imports.clone(),
            declarations,
            span: tree.span.clone(),
        });
    }
    Ok(result)
}
struct Expansion<'a> {
    tree: &'a File,
    declarations: BTreeMap<String, &'a Declaration>,
    definitions: Vec<Declaration>,
    variants: BTreeMap<String, Vec<String>>,
}
impl Expansion<'_> {
    fn bound(&self, size: usize) -> Result<()> {
        if size > 128 {
            return Err(ParseError::resource(
                "alternative expansion limit exceeded",
                self.tree.span.clone(),
            ));
        }
        Ok(())
    }
    fn variants_for(&mut self, name: &str, stack: &[String], depth: usize) -> Result<Vec<String>> {
        if stack.iter().any(|s| s == name) {
            return Err(ParseError::new(
                "recursive pattern expansion is not supported",
                self.tree.span.clone(),
            ));
        }
        if let Some(variants) = self.variants.get(name) {
            return Ok(variants.clone());
        }
        let Some(decl) = self
            .declarations
            .get(name)
            .copied()
            .filter(|d| d.kind == "pattern")
        else {
            return Ok(vec![name.into()]);
        };
        let mut stack = stack.to_vec();
        stack.push(name.into());
        let variants = self.clauses(&decl.clauses, &stack, depth + 1)?;
        let names: Vec<_> = (0..variants.len())
            .map(|i| format!("@variant:{name}:{i}"))
            .collect();
        for (name, clauses) in names.iter().cloned().zip(variants) {
            self.definitions.push(Declaration {
                kind: decl.kind.clone(),
                name,
                span: decl.span.clone(),
                parameters: decl.parameters.clone(),
                generics: decl.generics.clone(),
                clauses,
                formula: decl.formula.clone(),
                members: decl.members.clone(),
                values: decl.values.clone(),
                implements: decl.implements.clone(),
            });
        }
        self.variants.insert(name.into(), names.clone());
        Ok(names)
    }
    fn clauses(
        &mut self,
        items: &[Clause],
        stack: &[String],
        depth: usize,
    ) -> Result<Vec<Vec<Clause>>> {
        crate::with_stack(|| {
            if depth > 512 {
                return Err(ParseError::resource(
                    "alternative nesting limit exceeded",
                    self.tree.span.clone(),
                ));
            }
            let mut variants = vec![vec![]];
            for item in items {
                let mut choices = vec![];
                match item.kind.as_str() {
                    "when" => {
                        let Some(Expression::Query(condition)) = item.expressions.first() else {
                            return Err(ParseError::new(
                                "when requires a query condition",
                                item.span.clone(),
                            ));
                        };
                        let mut positive = Clause::new("where", item.span.clone());
                        positive
                            .expressions
                            .push(Expression::Query(condition.clone()));
                        let mut negative = Clause::new("where", item.span.clone());
                        negative.expressions.push(Expression::Query(Expr::checked(
                            "unary".into(),
                            condition.span.clone(),
                            "not".into(),
                            vec![condition.clone()],
                            vec![],
                        )?));
                        for (i, guard) in [positive, negative].into_iter().enumerate() {
                            let branch = item.blocks.get(i).map_or(&[][..], Vec::as_slice);
                            for rest in self.clauses(branch, stack, depth + 1)? {
                                let mut chosen = vec![guard.clone()];
                                chosen.extend(rest);
                                choices.push(chosen);
                                self.bound(choices.len())?;
                            }
                        }
                    }
                    "either" => {
                        for branch in &item.blocks {
                            choices.extend(self.clauses(branch, stack, depth + 1)?);
                            self.bound(choices.len())?;
                        }
                    }
                    "selector" | "fields" | "parameters" => {
                        let Some(block) = item.blocks.first() else {
                            return Err(ParseError::new(
                                "selector requires a block",
                                item.span.clone(),
                            ));
                        };
                        for branch in self.clauses(block, stack, depth + 1)? {
                            let mut c = clone_clause_without_blocks(item);
                            c.blocks = vec![branch];
                            choices.push(vec![c]);
                        }
                    }
                    "use" => {
                        for name in self.variants_for(&item.name, stack, depth + 1)? {
                            let mut c = item.clone();
                            c.name = name;
                            choices.push(vec![c]);
                        }
                    }
                    _ => choices.push(vec![item.clone()]),
                }
                self.bound(variants.len().saturating_mul(choices.len()))?;
                if choices.len() == 1 {
                    let choice = choices.pop().unwrap();
                    if let Some((last, rest)) = variants.split_last_mut() {
                        for prefix in rest {
                            prefix.extend(choice.iter().cloned());
                        }
                        last.extend(choice);
                    }
                    continue;
                }
                let mut next = Vec::with_capacity(variants.len() * choices.len());
                if let Some((last, rest)) = choices.split_last() {
                    for mut prefix in variants {
                        // Only a real fork copies a prefix; the last branch owns it.
                        for choice in rest {
                            let mut merged = prefix.clone();
                            merged.extend(choice.iter().cloned());
                            next.push(merged);
                        }
                        prefix.extend(last.iter().cloned());
                        next.push(prefix);
                    }
                }
                variants = next;
            }
            Ok(variants)
        })
    }
}
fn clone_clause_without_blocks(c: &Clause) -> Clause {
    Clause {
        kind: c.kind.clone(),
        span: c.span.clone(),
        name: c.name.clone(),
        role: c.role.clone(),
        expressions: c.expressions.clone(),
        parameters: c.parameters.clone(),
        blocks: vec![],
        alias: c.alias.clone(),
        flags: c.flags.clone(),
    }
}
