//! Existential witness roles stay private while incoming bindings correlate.
use crate::{ast::*, expression_check::Roles};
use std::collections::BTreeSet;
pub(crate) fn private_witnesses(
    items: &[Clause],
    bound: &BTreeSet<String>,
    scope: usize,
) -> Vec<Clause> {
    fn name(n: &str, bound: &BTreeSet<String>, scope: usize) -> String {
        if n.is_empty() || bound.contains(n) {
            n.into()
        } else {
            format!("@scope{scope}:{n}")
        }
    }
    fn visit(c: &Clause, bound: &BTreeSet<String>, scope: usize) -> Clause {
        crate::with_stack(|| {
            let mut v = crate::rewrite::clause_shell(c);
            v.role = name(&c.role, bound, scope);
            v.alias = name(&c.alias, bound, scope);
            if c.kind == "source_usages" {
                v.name = name(&c.name, bound, scope);
            }
            v.expressions = c
                .expressions
                .iter()
                .map(|e| {
                    crate::rewrite::expression(
                        e,
                        &|kind, value| {
                            if matches!(kind, "role" | "from") {
                                name(value, bound, scope)
                            } else {
                                value.into()
                            }
                        },
                        &Clone::clone,
                    )
                })
                .collect();
            v.blocks = c
                .blocks
                .iter()
                .map(|b| b.iter().map(|c| visit(c, bound, scope)).collect())
                .collect();
            v
        })
    }
    items.iter().map(|c| visit(c, bound, scope)).collect()
}
pub(crate) fn common_types(
    outer: &mut Roles,
    branches: &[(BTreeSet<String>, Roles)],
    bound: &mut BTreeSet<String>,
) {
    if branches.is_empty() {
        return;
    }
    let mut common = branches[0].0.clone();
    for (b, _) in &branches[1..] {
        common.retain(|r| b.contains(r));
    }
    for role in &common {
        let kinds: BTreeSet<_> = branches
            .iter()
            .map(|(_, t)| t.get(role).map_or("", String::as_str))
            .collect();
        let kind = if kinds.len() == 1 {
            kinds.first().unwrap().to_string()
        } else if kinds
            .iter()
            .all(|k| matches!(*k, "type" | "class" | "interface" | "trait"))
        {
            "type".into()
        } else if kinds
            .iter()
            .all(|k| matches!(*k, "callable" | "method" | "constructor"))
        {
            "callable".into()
        } else if kinds
            .iter()
            .all(|k| matches!(*k, "field" | "var" | "param" | "receiver" | "value"))
        {
            "var".into()
        } else {
            String::new()
        };
        outer.insert(role.clone(), kind);
    }
    bound.extend(common);
}
