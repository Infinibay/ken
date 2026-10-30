use flate2::read::GzDecoder;
use ken_program::StructuralIr;
use ken_query::{
    BodyPattern,
    execution::{Execution, MemoryGraph},
    relational::{PlanValue, QuotedTerm, RelationalEdge, RelationalNode, RelationalQuery, Term},
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, io::Read, sync::Arc};
fn text(v: impl Into<String>) -> PlanValue {
    PlanValue::Term(Term::Text(v.into()))
}
#[test]
fn relational_body_projects_original_witnesses_and_keeps_outer_evidence() {
    let mut raw = String::new();
    GzDecoder::new(&include_bytes!("fixtures/body-runtime-reference.json.gz")[..])
        .read_to_string(&mut raw)
        .unwrap();
    let fixture: Value = serde_json::from_str(&raw).unwrap();
    let mut checked = 0;
    for case in fixture["cases"].as_array().unwrap() {
        let input = case["bindings"].as_object().unwrap();
        if input.values().any(|v| v["kind"] != "node")
            || case["matches"].as_array().unwrap().is_empty()
        {
            continue;
        }
        let pattern: BodyPattern = serde_json::from_value(case["pattern"].clone()).unwrap();
        if pattern.outputs.is_empty() {
            continue;
        }
        let record = &fixture["graphs"][case["graph"].as_u64().unwrap() as usize];
        let ir = StructuralIr::from_json(&record["graph"].to_string()).unwrap();
        let graph = MemoryGraph::new(&ir).unwrap();
        if input.values().any(|v| {
            !ir.entities
                .iter()
                .any(|(key, _)| Some(key.as_str()) == v["value"]["local_id"].as_str())
        }) {
            continue;
        }
        let id = input[&pattern.owner]["value"]["local_id"].as_str().unwrap();
        let mut nodes = vec![];
        for (role, record) in input {
            let node = &record["value"];
            let edge = RelationalEdge {
                mode: "require".into(),
                subject: Term::Text(format!("${role}")),
                relation: "ENTITY".into(),
                object: Term::Literal(QuotedTerm {
                    token: node["kind"].to_string(),
                    literal: node["kind"].as_str().unwrap().into(),
                }),
                attrs: vec![],
            };
            nodes.push(RelationalNode {
                kind: "fact".into(),
                value: PlanValue::Edge(edge),
                children: vec![],
            });
            nodes.push(RelationalNode {
                kind: "where".into(),
                value: PlanValue::Tuple(vec![
                    text(format!("${role}")),
                    text("literal"),
                    text(node["local_id"].to_string()),
                ]),
                children: vec![],
            });
        }
        nodes.push(RelationalNode {
            kind: "source_body".into(),
            value: PlanValue::Body(pattern.clone()),
            children: vec![],
        });
        let query = RelationalQuery {
            name: "body".into(),
            nodes: Arc::new(nodes),
            exports: pattern
                .outputs
                .iter()
                .map(|r| (r.clone(), format!("${r}")))
                .collect(),
            definitions: Default::default(),
        };
        let outcome = Execution::new(ken_query::execution::ExecutionOptions {
            evidence_mode: ken_query::execution::EvidenceMode::Possible,
            ..Default::default()
        })
        .unwrap()
        .execute(&graph, &query)
        .unwrap_or_else(|e| panic!("{}: {e}", case["name"]));
        assert!(outcome.complete, "{}", case["name"]);
        let expected: BTreeMap<_, _> = case["matches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| {
                let bindings: BTreeMap<_, _> = pattern
                    .outputs
                    .iter()
                    .map(|r| {
                        let v = &m["bindings"][r];
                        let v = if let Some(id) = v.get("local_id") {
                            id.as_str().unwrap().to_owned()
                        } else if v.get("reason").is_some() {
                            format!("@unknown:{r}")
                        } else if let Some(s) = v.as_str() {
                            s.into()
                        } else {
                            match v {
                                Value::Bool(true) => "True".into(),
                                Value::Bool(false) => "False".into(),
                                Value::Null => "None".into(),
                                _ => v.to_string(),
                            }
                        };
                        (format!("${r}"), v)
                    })
                    .collect();
                (serde_json::to_string(&bindings).unwrap(), bindings)
            })
            .collect();
        let actual: BTreeMap<_, _> = outcome
            .matches
            .iter()
            .map(|m| {
                (
                    serde_json::to_string(&m.bindings).unwrap(),
                    m.bindings.clone(),
                )
            })
            .collect();
        assert_eq!(actual, expected, "{}", case["name"]);
        for m in &outcome.matches {
            assert!(
                m.evidence.contains(&json!({"body_owner":id})),
                "{} evidence {:?}",
                case["name"],
                m.evidence
            );
            assert!(m.evidence.iter().any(|e| e["relation"] == "ENTITY"));
        }
        checked += 1;
        if checked == 32 {
            break;
        }
    }
    assert_eq!(checked, 32);
}
