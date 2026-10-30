use ken_query::relational::{
    PlanValue, QuotedTerm, RelationalEdge, RelationalNode, RelationalQuery, Term,
};
use serde_json::Value;
use std::sync::Arc;
fn term(v: &Value) -> Term {
    if let Some(literal) = v.get("literal") {
        Term::Literal(QuotedTerm {
            token: literal.to_string(),
            literal: literal.as_str().unwrap().into(),
        })
    } else {
        Term::Text(v.as_str().unwrap().into())
    }
}
fn value(v: &Value) -> PlanValue {
    match v {
        Value::Null => PlanValue::None,
        Value::String(s) => PlanValue::Term(Term::Text(s.clone())),
        Value::Number(n) => PlanValue::Term(Term::Text(n.to_string())),
        Value::Array(a) => PlanValue::Tuple(a.iter().map(value).collect()),
        Value::Object(o) if o.contains_key("subject") => PlanValue::Edge(RelationalEdge {
            mode: "require".into(),
            subject: term(&v["subject"]),
            relation: v["relation"].as_str().unwrap().into(),
            object: term(&v["object"]),
            attrs: serde_json::from_value(v["attrs"].clone()).unwrap(),
        }),
        Value::Object(o) if o.contains_key("literal") => PlanValue::Term(term(v)),
        Value::Object(o) if o.get("__class__").and_then(Value::as_str) == Some("Expr") => {
            PlanValue::Expression(ken_query::ast::Expression::Query(
                serde_json::from_value(v.clone()).unwrap(),
            ))
        }
        Value::Object(o) => PlanValue::Map(o.iter().map(|(k, v)| (k.clone(), value(v))).collect()),
        _ => panic!("plan value"),
    }
}
fn node(v: &Value) -> RelationalNode {
    RelationalNode {
        kind: v["kind"].as_str().unwrap().into(),
        value: value(&v["value"]),
        children: v["children"]
            .as_array()
            .unwrap()
            .iter()
            .map(|b| b.as_array().unwrap().iter().map(node).collect())
            .collect(),
    }
}
pub fn query(v: &Value) -> RelationalQuery {
    RelationalQuery {
        name: v["name"].as_str().unwrap().into(),
        nodes: Arc::new(v["nodes"].as_array().unwrap().iter().map(node).collect()),
        exports: v["exports"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap().into()))
            .collect(),
        definitions: v["definitions"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), Arc::new(query(v))))
            .collect(),
    }
}

/// Intentional cardinality safety differences are authored separately. Never
/// rewrite the original observations to pretend that Python already did this.
pub fn expected(case: &Value) -> Value {
    static DATA: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    let data = DATA.get_or_init(|| {
        serde_json::from_str(include_str!(
            "../fixtures/execution-safety-expectations.json"
        ))
        .unwrap()
    });
    data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == case["name"])
        .map_or_else(|| case["expected"].clone(), |c| c["expected"].clone())
}
