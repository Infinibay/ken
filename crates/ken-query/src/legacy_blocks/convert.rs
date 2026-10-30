//! Existing line/selector searches become named positive relations without rerendering source.
use super::*;
use crate::{
    legacy::Clause,
    relational::{OrderedMap, RelationalQuery},
};
use std::{collections::BTreeSet, sync::Arc};
fn convert(clauses: &[Clause]) -> Result<Vec<RelationalNode>> {
    crate::with_stack(|| {
        let mut nodes = vec![];
        for c in clauses {
            let fact = edge(
                Term::Text(c.subject.clone()),
                &c.relation,
                Term::Text(c.object.clone()),
                c.attrs.clone(),
            );
            match c.mode.as_str() {
                "require" => nodes.push(fact),
                "optional" => nodes.push(node("optional", PlanValue::None, vec![vec![fact]])),
                "count" => {
                    let mut child = vec![fact];
                    child.extend(convert(&c.r#where)?);
                    let role = if c.distinct.is_empty() {
                        &c.object
                    } else {
                        &c.distinct
                    };
                    nodes.push(node(
                        "count",
                        PlanValue::Tuple(vec![
                            text(role),
                            text(&c.count_op),
                            PlanValue::Integer(crate::IntegerLiteral::from_digits(
                                &c.count.to_string(),
                            )),
                        ]),
                        vec![child],
                    ));
                }
                "forbid" => {
                    return Err(invalid(
                        "legacy negation cannot be imported without an explicit scope",
                    ));
                }
                _ => (),
            }
        }
        Ok(nodes)
    })
}
fn bound(nodes: &[RelationalNode]) -> BTreeSet<String> {
    crate::with_stack(|| {
        let mut result = BTreeSet::new();
        for n in nodes {
            if let PlanValue::Edge(e) = &n.value {
                if n.kind == "fact" {
                    for t in [&e.subject, &e.object] {
                        if t.token().starts_with('$') {
                            result.insert(t.token().into());
                        }
                    }
                }
            } else if n.kind == "any" {
                let mut branches = n.children.iter().map(|b| bound(b));
                if let Some(mut common) = branches.next() {
                    for b in branches {
                        common.retain(|r| b.contains(r));
                    }
                    result.extend(common);
                }
            }
        }
        result
    })
}
pub fn legacy_query(source: &str, name: &str) -> Result<RelationalQuery> {
    let pattern = crate::legacy::parse_query(source)?;
    let mut nodes = convert(&pattern.clauses)?;
    if !pattern.variants.is_empty() {
        nodes.push(node(
            "any",
            PlanValue::None,
            pattern
                .variant_order
                .iter()
                .map(|id| convert(&pattern.variants[id]))
                .collect::<Result<_>>()?,
        ));
    }
    nodes.extend(pattern.different.iter().map(|(a, b)| {
        node(
            "different",
            PlanValue::Tuple(vec![text(a), text(b)]),
            vec![],
        )
    }));
    let mut exports: OrderedMap<_> = bound(&nodes)
        .into_iter()
        .map(|v| (v[1..].into(), v))
        .collect();
    if matches!(name, "factory-method" | "gof.factory-method") {
        exports.insert("creator".into(), "$unit".into());
    }
    Ok(RelationalQuery {
        name: name.into(),
        nodes: Arc::new(nodes),
        exports,
        definitions: Default::default(),
    })
}
