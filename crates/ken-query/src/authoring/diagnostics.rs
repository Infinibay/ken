//! Warnings inspect compiled captures; they never change query meaning or rows.
use crate::{
    Program, Step,
    ast::Expr,
    indexed::{clause_roles as body_roles, free_roles as free},
};
use ken_program::value::GraphValue;
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};
fn label(role: &str) -> String {
    format!("${}", role.rsplit(':').next().unwrap_or(role))
}
struct Warnings {
    items: Vec<serde_json::Value>,
    seen: BTreeSet<(String, String, usize, usize, String)>,
}
impl Warnings {
    fn warn(
        &mut self,
        code: &str,
        message: String,
        hint: &str,
        span: &crate::ast::Span,
        details: serde_json::Value,
    ) {
        let key = (
            code.into(),
            span.source.to_string(),
            span.start,
            span.end,
            message.clone(),
        );
        if !self.seen.insert(key) {
            return;
        }
        let mut warning = json!({"code":code,"severity":"warning","message":message,"hint":hint,"span":{"source":span.source,"start":span.start,"end":span.end}});
        if let Some(details) = details.as_object() {
            for (key, value) in details {
                warning[key] = value.clone();
            }
        }
        self.items.push(warning);
    }
    fn quantifiers(&mut self, e: &Expr, outer: &BTreeSet<String>, negated: bool) {
        if matches!(e.kind.as_str(), "quantifier" | "aggregate") {
            let local = e
                .parameters
                .iter()
                .map(|p| p.role.clone())
                .collect::<BTreeSet<_>>();
            if e.value == "exists" && !outer.is_empty() && free(e).is_disjoint(outer) {
                let kind = if negated { "not exists" } else { "exists" };
                self.warn("uncorrelated_exists",format!("{kind} is global in the selected source scope; it does not test each outer capture."),"If you mean a descendant of a captured node, add where contains($owner, $witness) inside the block. Keep it global only when that is the intended property.",&e.span,json!({"captures":outer.iter().map(|r|label(r)).collect::<Vec<_>>()}));
            }
            let mut scope = outer.clone();
            scope.extend(local);
            for child in &e.args {
                self.quantifiers(child, &scope, false);
            }
            return;
        }
        for child in &e.args {
            self.quantifiers(child, outer, e.kind == "unary" && e.value == "not");
        }
    }
}
pub fn diagnose(program: &Program) -> Vec<serde_json::Value> {
    if !program.branches.is_empty() {
        return program
            .branches
            .iter()
            .enumerate()
            .flat_map(|(i, p)| {
                diagnose(p).into_iter().map(move |mut warning| {
                    warning["branch"] = json!(i + 1);
                    warning
                })
            })
            .collect();
    }
    if !program.graph.is_empty() {
        return vec![];
    }
    let mut warnings = Warnings {
        items: vec![],
        seen: BTreeSet::new(),
    };
    let mut roles = program
        .scans
        .iter()
        .map(|s| s.role.clone())
        .collect::<BTreeSet<_>>();
    let mut links = program
        .scans
        .iter()
        .filter_map(|s| {
            s.owner
                .as_ref()
                .map(|o| BTreeSet::from([s.role.clone(), o.clone()]))
        })
        .collect::<Vec<_>>();
    let mut expressions = program
        .filters
        .iter()
        .chain(&program.optional)
        .collect::<Vec<_>>();
    for step in &program.steps {
        match step {
            Step::Body(body) => {
                roles.extend(body.outputs.iter().cloned());
                let mut link = body_roles(&body.clauses);
                link.insert(body.owner.clone());
                link.extend(body.outputs.iter().cloned());
                links.push(link);
            }
            Step::Action(action) if !action.role.is_empty() => {
                roles.insert(action.role.clone());
                let mut link = free(&action.expression);
                link.insert(action.role.clone());
                links.push(link);
                expressions.push(&action.expression);
            }
            _ => (),
        }
    }
    let syntax = ken_program::syntax_kinds();
    for scan in &program.scans {
        expressions.extend(scan.properties.iter().map(|(_, e)| e));
        if !matches!(scan.selector.as_str(), "node" | "expression" | "statement") {
            continue;
        }
        let properties = scan
            .properties
            .iter()
            .filter_map(|(key, e)| {
                if e.kind == "literal" {
                    serde_json::from_str::<serde_json::Value>(&e.value)
                        .ok()
                        .map(|v| (key.as_str(), v))
                } else {
                    None
                }
            })
            .collect::<BTreeMap<_, _>>();
        for (key, e) in &scan.properties {
            if key == "kind"
                && e.kind == "literal"
                && let Some(kind) = properties.get("kind").and_then(serde_json::Value::as_str)
                && !syntax.contains(kind)
            {
                let repr = GraphValue::String(kind.into()).repr();
                warnings.warn("unknown_syntax_kind",format!("{repr} is not a canonical syntax kind."),"Use kind: \"catch\" for Python except clauses; use native_kind for parser-specific names. See ken kql2 --capabilities.",&e.span,json!({}));
            }
            if key == "name"
                && properties.get("kind").and_then(serde_json::Value::as_str) == Some("identifier")
                && let Some(name) = properties
                    .get("name")
                    .and_then(serde_json::Value::as_str)
                    .filter(|n| ["None", "True", "False", "*"].contains(n))
            {
                let repr = GraphValue::String(name.into()).repr();
                warnings.warn("syntax_spelling_mismatch",format!("An identifier named {repr} does not describe the corresponding Python literal or wildcard import."),"For literals use kind: \"literal\"; text: \"None\"; (or \"True\"/\"False\"). For import * use native_kind: \"wildcard_import\".",&e.span,json!({}));
            }
        }
    }
    for expression in expressions {
        let mut atoms = vec![expression];
        while let Some(atom) = atoms.pop() {
            if atom.kind == "binary" && matches!(atom.value.as_str(), "and" | "or") {
                atoms.extend(atom.args.iter());
            } else {
                links.push(free(atom));
            }
        }
        warnings.quantifiers(expression, &roles, false);
    }
    let mut groups = roles
        .into_iter()
        .map(|r| BTreeSet::from([r]))
        .collect::<Vec<_>>();
    for link in links {
        let mut connected = BTreeSet::new();
        let mut rest = vec![];
        for group in groups {
            if group.is_disjoint(&link) {
                rest.push(group);
            } else {
                connected.extend(group);
            }
        }
        if !connected.is_empty() {
            rest.push(connected);
        }
        groups = rest;
    }
    groups.sort_by(|a, b| a.first().cmp(&b.first()));
    if groups.len() > 1
        && let Some(projection) = program.projection.first()
    {
        warnings.warn("disconnected_captures","Independent capture groups can form a Cartesian product. Their existence does not establish containment or ownership.".into(),"If the question requires a relationship, nest direct children or add where contains($owner, $witness). Project witnesses while checking the query. Independent groups are allowed when intentional.",&projection.span,json!({"groups":groups.iter().map(|g|g.iter().map(|r|label(r)).collect::<Vec<_>>()).collect::<Vec<_>>()}));
    }
    warnings.items
}
