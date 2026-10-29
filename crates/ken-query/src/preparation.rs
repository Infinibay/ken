//! Pure explicit module snapshots and hygienic model specialization.
use crate::rewrite;
use crate::{ParseError, Result, ast::*};
use std::collections::{BTreeMap, BTreeSet};
pub fn resolve_libraries(entry: &File, libraries: &BTreeMap<String, File>) -> Result<File> {
    enum Work<'a> {
        Enter(&'a File, bool),
        Dependency(&'a File, &'a str),
        Exit(&'a File, bool),
    }
    let mut output = vec![];
    let mut seen = BTreeSet::new();
    let mut pending = vec![Work::Enter(entry, true)];
    while let Some(work) = pending.pop() {
        match work {
            Work::Enter(tree, main) => {
                if !seen.insert(tree.module.clone()) {
                    continue;
                }
                crate::validation::tree(tree)?;
                pending.push(Work::Exit(tree, main));
                pending.extend(
                    tree.imports
                        .iter()
                        .rev()
                        .filter(|d| d.as_str() != "ken.core")
                        .map(|d| Work::Dependency(tree, d)),
                );
            }
            Work::Dependency(tree, dependency) => {
                let imported = if dependency == entry.module {
                    Some(entry)
                } else {
                    libraries.get(dependency)
                };
                let Some(imported) = imported.filter(|m| m.module == dependency) else {
                    return Err(ParseError::new(
                        format!("missing or mismatched library module: {dependency}"),
                        tree.span.clone(),
                    ));
                };
                pending.push(Work::Enter(imported, std::ptr::eq(imported, entry)));
            }
            Work::Exit(tree, main) => {
                let prefix = if main {
                    String::new()
                } else {
                    format!("{}.", tree.module)
                };
                let names = tree
                    .declarations
                    .iter()
                    .map(|d| (d.name.clone(), format!("{prefix}{}", d.name)))
                    .collect();
                for d in &tree.declarations {
                    if main || d.kind != "query" {
                        output.push(qualify_declaration(d, &names, false, &BTreeSet::new()));
                    }
                }
            }
        }
    }
    let mut names = BTreeSet::new();
    if output.iter().any(|d| !names.insert(d.name.clone())) {
        return Err(ParseError::new(
            "library declaration collision",
            entry.span.clone(),
        ));
    }
    Ok(rewrite::file(entry, output, vec![]))
}
fn rename(name: &str, map: &BTreeMap<String, String>) -> String {
    let head = name.split('.').next().unwrap_or("");
    format!(
        "{}{}",
        map.get(head).map_or(head, String::as_str),
        &name[head.len()..]
    )
}
fn qualify_type(t: &TypeName, names: &BTreeMap<String, String>) -> TypeName {
    crate::with_stack(|| TypeName {
        name: rename(&t.name, names),
        arguments: t.arguments.iter().map(|t| qualify_type(t, names)).collect(),
    })
}
fn qualify_parameter(p: &Parameter, names: &BTreeMap<String, String>) -> Parameter {
    Parameter {
        r#type: qualify_type(&p.r#type, names),
        role: p.role.clone(),
        direction: p.direction.clone(),
    }
}
fn qualify_expression(
    e: &Expression,
    names: &BTreeMap<String, String>,
    local: &BTreeSet<String>,
) -> Expression {
    rewrite::expression(
        e,
        &|kind, value| {
            if matches!(kind, "call" | "name")
                && !local.contains(value.split('.').next().unwrap_or(""))
            {
                rename(value, names)
            } else {
                value.into()
            }
        },
        &|p| qualify_parameter(p, names),
    )
}
fn qualify_clause(
    c: &Clause,
    names: &BTreeMap<String, String>,
    local: &BTreeSet<String>,
) -> Clause {
    crate::with_stack(|| {
        let mut result = rewrite::clause_shell(c);
        if c.kind == "use" {
            result.name = rename(&c.name, names);
            result.flags = c
                .flags
                .iter()
                .map(|f| {
                    if local.contains(f) {
                        f.clone()
                    } else {
                        rename(f, names)
                    }
                })
                .collect();
        }
        result.parameters = c
            .parameters
            .iter()
            .map(|p| qualify_parameter(p, names))
            .collect();
        result.expressions = c
            .expressions
            .iter()
            .map(|e| qualify_expression(e, names, local))
            .collect();
        result.blocks = c
            .blocks
            .iter()
            .map(|b| b.iter().map(|c| qualify_clause(c, names, local)).collect())
            .collect();
        result
    })
}
fn qualify_declaration(
    d: &Declaration,
    names: &BTreeMap<String, String>,
    member: bool,
    local: &BTreeSet<String>,
) -> Declaration {
    crate::with_stack(|| {
        let mut local = local.clone();
        local.extend(d.generics.iter().map(|(n, _)| n.clone()));
        let mut member_local = local.clone();
        member_local.extend(d.members.iter().map(|m| m.name.clone()));
        let mut result = rewrite::declaration_shell(d);
        if !member {
            result.name = names[&d.name].clone();
        }
        result.formula = d.formula.as_ref().map(|e| {
            rewrite::query(
                e,
                &|kind, value| {
                    if matches!(kind, "call" | "name")
                        && !local.contains(value.split('.').next().unwrap_or(""))
                    {
                        rename(value, names)
                    } else {
                        value.into()
                    }
                },
                &|p| qualify_parameter(p, names),
            )
        });
        result.parameters = d
            .parameters
            .iter()
            .map(|p| qualify_parameter(p, names))
            .collect();
        result.generics = d
            .generics
            .iter()
            .map(|(name, signature)| (name.clone(), rename(signature, names)))
            .collect();
        result.implements = rename(&d.implements, names);
        result.clauses = d
            .clauses
            .iter()
            .map(|c| qualify_clause(c, names, &local))
            .collect();
        result.members = d
            .members
            .iter()
            .map(|m| qualify_declaration(m, names, true, &member_local))
            .collect();
        result
    })
}
pub fn specialize_models(tree: &File) -> Result<File> {
    crate::validation::tree(tree)?;
    let mut names = BTreeSet::new();
    if tree
        .declarations
        .iter()
        .any(|d| !names.insert(d.name.clone()))
    {
        return Err(ParseError::new("duplicate declaration", tree.span.clone()));
    }
    let declarations: BTreeMap<_, _> = tree
        .declarations
        .iter()
        .map(|d| (d.name.clone(), d))
        .collect();
    let models: BTreeMap<_, _> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "model")
        .map(|d| (d.name.clone(), d))
        .collect();
    let mut output = vec![];
    for model in tree.declarations.iter().filter(|d| d.kind == "model") {
        let Some(signature) = declarations
            .get(&model.implements)
            .filter(|d| d.kind == "signature")
        else {
            return Err(ParseError::new(
                "model implements an unknown signature",
                model.span.clone(),
            ));
        };
        let members: BTreeMap<_, _> = model.members.iter().map(|m| (m.name.clone(), m)).collect();
        let unique_signature: BTreeSet<_> = signature.members.iter().map(|m| &m.name).collect();
        if members.len() != model.members.len() || unique_signature.len() != signature.members.len()
        {
            return Err(ParseError::new(
                "duplicate model/signature predicate",
                model.span.clone(),
            ));
        }
        for expected in &signature.members {
            if members.get(&expected.name).is_none_or(|actual| {
                actual
                    .parameters
                    .iter()
                    .map(|p| &p.r#type)
                    .ne(expected.parameters.iter().map(|p| &p.r#type))
            }) {
                return Err(ParseError::new(
                    format!("model predicate signature mismatch: {}", expected.name),
                    model.span.clone(),
                ));
            }
        }
        let local = model
            .members
            .iter()
            .map(|m| (m.name.clone(), format!("{}.{}", model.name, m.name)))
            .collect();
        for member in &model.members {
            let Some(formula) = &member.formula else {
                return Err(ParseError::new(
                    "model member requires a formula",
                    member.span.clone(),
                ));
            };
            let formula = rewrite::query(
                formula,
                &|kind, value| {
                    if matches!(kind, "call" | "name") {
                        rename(value, &local)
                    } else {
                        value.into()
                    }
                },
                &Clone::clone,
            );
            let mut item = rewrite::declaration_shell(member);
            item.name = local[&member.name].clone();
            item.formula = Some(formula);
            item.clauses = member.clauses.clone();
            item.members = member.members.clone();
            output.push(item);
        }
    }
    let mut specialization = Specialization {
        declarations: &declarations,
        models: &models,
        output,
        instances: BTreeMap::new(),
    };
    for declaration in &tree.declarations {
        if matches!(declaration.kind.as_str(), "signature" | "model")
            || !declaration.generics.is_empty()
        {
            continue;
        }
        let clauses = specialization.clauses(&declaration.clauses, &BTreeMap::new(), 0)?;
        let mut item = rewrite::declaration_shell(declaration);
        item.clauses = clauses;
        item.formula = declaration.formula.clone();
        item.members = declaration.members.clone();
        specialization.output.push(item);
    }
    let unique: BTreeSet<_> = specialization.output.iter().map(|d| &d.name).collect();
    if unique.len() != specialization.output.len() {
        return Err(ParseError::new(
            "model predicate name collides with declaration",
            tree.span.clone(),
        ));
    }
    Ok(rewrite::file(
        tree,
        specialization.output,
        tree.imports.clone(),
    ))
}
fn map_expression(e: &Expression, map: &BTreeMap<String, String>) -> Expression {
    rewrite::expression(
        e,
        &|kind, value| {
            if matches!(kind, "call" | "name") {
                rename(value, map)
            } else {
                value.into()
            }
        },
        &Clone::clone,
    )
}
struct Specialization<'a> {
    declarations: &'a BTreeMap<String, &'a Declaration>,
    models: &'a BTreeMap<String, &'a Declaration>,
    output: Vec<Declaration>,
    instances: BTreeMap<(String, Vec<String>), String>,
}
impl Specialization<'_> {
    fn clauses(
        &mut self,
        items: &[Clause],
        map: &BTreeMap<String, String>,
        depth: usize,
    ) -> Result<Vec<Clause>> {
        crate::with_stack(|| {
            if depth > 512 {
                return Err(ParseError::resource(
                    "model nesting limit exceeded",
                    items.first().map(|c| c.span.clone()).unwrap_or(Span {
                        source: "<query>".into(),
                        start: 0,
                        end: 0,
                    }),
                ));
            }
            let mut result = vec![];
            for item in items {
                let mut updated = rewrite::clause_shell(item);
                updated.expressions = item
                    .expressions
                    .iter()
                    .map(|e| map_expression(e, map))
                    .collect();
                updated.blocks = item
                    .blocks
                    .iter()
                    .map(|block| self.clauses(block, map, depth + 1))
                    .collect::<Result<_>>()?;
                let mut item = updated;
                if item.kind == "use" {
                    let arguments: Vec<_> = item.flags.iter().map(|n| rename(n, map)).collect();
                    if let Some(target) = self
                        .declarations
                        .get(&item.name)
                        .filter(|t| t.kind == "pattern" && !t.generics.is_empty())
                    {
                        if arguments.len() != target.generics.len() {
                            return Err(ParseError::new(
                                "wrong number of model arguments",
                                item.span,
                            ));
                        }
                        let mut substitutions = BTreeMap::new();
                        for ((parameter, signature), argument) in
                            target.generics.iter().zip(&arguments)
                        {
                            if self
                                .models
                                .get(argument)
                                .is_none_or(|m| m.implements != *signature)
                            {
                                return Err(ParseError::new(
                                    format!("model argument does not implement {signature}"),
                                    item.span,
                                ));
                            }
                            substitutions.insert(parameter.clone(), argument.clone());
                        }
                        let key = (target.name.clone(), arguments);
                        if !self.instances.contains_key(&key) {
                            if self.instances.len() >= 128 {
                                return Err(ParseError::new(
                                    "model specialization limit",
                                    item.span,
                                ));
                            }
                            let generated =
                                format!("@model:{}:{}", self.instances.len(), target.name);
                            self.instances.insert(key.clone(), generated.clone());
                            let body = self.clauses(&target.clauses, &substitutions, depth + 1)?;
                            let mut output = rewrite::declaration_shell(target);
                            output.name = generated;
                            output.generics.clear();
                            output.clauses = body;
                            output.formula = target.formula.clone();
                            output.members = target.members.clone();
                            self.output.push(output);
                        }
                        item.name = self.instances[&key].clone();
                        item.flags.clear();
                    } else if !arguments.is_empty() {
                        return Err(ParseError::new(
                            "model arguments require a generic pattern",
                            item.span,
                        ));
                    }
                }
                result.push(item);
            }
            Ok(result)
        })
    }
}
