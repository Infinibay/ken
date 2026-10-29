//! Finite predicate dependency components and stratification checks.
use crate::{
    ParseError, PythonRepr, Result,
    ast::{Expr, Parameter},
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt::{self, Write},
};
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(tag = "__class__")]
pub struct Predicate {
    pub name: String,
    pub parameters: Vec<Parameter>,
    pub formula: Expr,
}
impl PythonRepr for Predicate {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        crate::repr::record(
            out,
            "Predicate",
            &[
                ("name", &self.name),
                ("parameters", &self.parameters),
                ("formula", &self.formula),
            ],
        )
    }
}
pub fn predicate_components(predicates: &[Predicate]) -> Result<Vec<Vec<String>>> {
    let names: BTreeSet<_> = predicates.iter().map(|p| p.name.clone()).collect();
    let mut edges: BTreeMap<String, Vec<(String, bool)>> =
        names.iter().map(|n| (n.clone(), vec![])).collect();
    for predicate in predicates {
        let mut pending = vec![(&predicate.formula, false)];
        let mut found = vec![];
        while let Some((expr, restricted)) = pending.pop() {
            let restricted = restricted
                || expr.kind == "unary" && expr.value == "not"
                || expr.kind == "binary" && !matches!(expr.value.as_str(), "and" | "or")
                || expr.kind == "aggregate"
                || expr.kind == "quantifier" && expr.value == "forall";
            if expr.kind == "call" && names.contains(&expr.value) {
                found.push((expr.value.clone(), restricted));
            }
            pending.extend(expr.args.iter().rev().map(|a| (a, restricted)));
        }
        edges.insert(predicate.name.clone(), found);
    }
    let mut reverse: BTreeMap<_, Vec<String>> = names.iter().map(|n| (n.clone(), vec![])).collect();
    for (parent, children) in &edges {
        for (child, _) in children {
            reverse.get_mut(child).unwrap().push(parent.clone());
        }
    }
    let mut seen = BTreeSet::new();
    let mut finished = vec![];
    for name in &names {
        if seen.contains(name) {
            continue;
        }
        let mut todo = vec![(name.clone(), false)];
        while let Some((current, exiting)) = todo.pop() {
            if exiting {
                finished.push(current);
            } else if seen.insert(current.clone()) {
                todo.push((current.clone(), true));
                todo.extend(
                    edges[&current]
                        .iter()
                        .filter(|(child, _)| !seen.contains(child))
                        .map(|(child, _)| (child.clone(), false)),
                );
            }
        }
    }
    let mut groups = vec![];
    let mut assigned = BTreeMap::new();
    for name in finished.into_iter().rev() {
        if assigned.contains_key(&name) {
            continue;
        }
        let mut members = vec![];
        let mut pending = vec![name];
        while let Some(current) = pending.pop() {
            if !assigned.contains_key(&current) {
                assigned.insert(current.clone(), groups.len());
                members.push(current.clone());
                pending.extend(reverse[&current].iter().cloned());
            }
        }
        members.sort();
        groups.push(members);
    }
    for pred in predicates {
        for (target, restricted) in &edges[&pred.name] {
            if *restricted && assigned[&pred.name] == assigned[target] {
                return Err(ParseError::new(
                    "recursion through negation, forall or aggregation is not stratified",
                    pred.formula.span.clone(),
                ));
            }
        }
    }
    Ok(groups)
}
