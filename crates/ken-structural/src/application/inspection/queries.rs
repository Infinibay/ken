use std::collections::BTreeSet;
pub fn query(body: &str) -> String {
    format!("language \"kql/2\"; module ken.inspection; query inspect {{ {body} }}")
}
pub fn quoted(value: &str) -> String {
    serde_json::to_string(value).unwrap()
}
fn alternatives(clauses: &[String]) -> String {
    if clauses.len() == 1 {
        clauses[0].clone()
    } else {
        format!("either {{ {} }}", clauses.join(" } or { "))
    }
}
fn endpoints(relation: &str, values: &[String], subject: bool, role: &str) -> String {
    let values = values.iter().cloned().collect::<BTreeSet<_>>();
    if values.iter().any(|v| v.contains('|')) {
        return alternatives(
            &values
                .iter()
                .map(|v| {
                    if subject {
                        format!("edge {relation}({},{role});", quoted(v))
                    } else {
                        format!("edge {relation}({role},{});", quoted(v))
                    }
                })
                .collect::<Vec<_>>(),
        );
    }
    let values = format!(
        "[{}]",
        values
            .iter()
            .map(|v| quoted(v))
            .collect::<Vec<_>>()
            .join(", ")
    );
    if subject {
        format!("edge {relation}({values},{role});")
    } else {
        format!("edge {relation}({role},{values});")
    }
}
pub fn definitions(name: Option<&str>) -> String {
    let selector = name
        .map(|name| format!("name:{};", quoted(name)))
        .unwrap_or_default();
    query(&format!("callable $f {{{selector}}} select $f;"))
}
pub fn neighbors(ids: &[String], incoming: bool, outgoing: bool) -> String {
    let mut clauses = Vec::new();
    if incoming {
        for relation in ["TARGET", "MAY_TARGET"] {
            clauses.push(endpoints(relation, ids, false, "$site"));
        }
    }
    if outgoing {
        clauses.push(endpoints("HAS_CALL", ids, true, "$site"));
    }
    query(&format!(
        "{} edge HAS_CALL($owner,$site); select $owner,$site;",
        alternatives(&clauses)
    ))
}
pub fn targets(sites: &[String], possible: bool) -> String {
    let relation = if possible { "MAY_TARGET" } else { "TARGET" };
    let selected = endpoints(relation, sites, true, "$target");
    let clauses = sites
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .iter()
        .map(|site| format!("where $site == {};", quoted(site)))
        .collect::<Vec<_>>();
    query(&format!(
        "{selected} edge {relation}($site,$target); {} select $site,$target;",
        alternatives(&clauses)
    ))
}
pub fn usages(sites: &[String]) -> String {
    let selected = endpoints("TARGET", sites, true, "$target");
    let clauses = sites
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .iter()
        .map(|site| format!("where $call == {};", quoted(site)))
        .collect::<Vec<_>>();
    query(&format!(
        "{selected} edge TARGET($call,$target); edge HAS_CALL($owner,$call); {} callable $target {{}} callable $owner {{body {{let $value=call $target {{}} as $site;}}}} usages of $value as $use {{}} select $owner,$target,$site,$use;",
        alternatives(&clauses)
    ))
}
