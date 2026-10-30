use flate2::read::GzDecoder;
use ken_program::{StructuralIr, value::GraphValue};
use ken_query::{
    BodyPattern,
    ast::Expr,
    execution::{
        ExecutionError, MemoryGraph, Result,
        body_runtime::{BodyCursor, BodyServices, validate},
        values::{Bindings, SourceNode, Value},
    },
};
use serde_json::Value as Json;
use sha2::Digest;
use std::{collections::BTreeMap, io::Read, sync::Arc};

struct Services {
    checks: usize,
    limit: Option<usize>,
}
impl BodyServices for Services {
    fn check(&mut self) -> Result<()> {
        self.checks += 1;
        if self.limit.is_some_and(|n| self.checks > n) {
            Err(ExecutionError::Exhausted("body_test"))
        } else {
            Ok(())
        }
    }
    fn evaluate(&mut self, e: &Expr, b: &Bindings) -> Result<Value> {
        self.check()?;
        match e.kind.as_str() {
            "role" => Ok(b
                .get(&e.value)
                .cloned()
                .unwrap_or_else(|| Value::unknown("unbound_source_role"))),
            "literal" => Value::literal(&e.value),
            _ => Ok(Value::unknown("source_condition_unsupported")),
        }
    }
    fn regex(&mut self, text: &str, e: &Expr) -> Result<bool> {
        self.check()?;
        let at = e.value.rfind('/').unwrap();
        regex::RegexBuilder::new(&e.value[1..at])
            .case_insensitive(e.value[at + 1..].contains('i'))
            .build()
            .map(|re| re.is_match(text))
            .map_err(|e| ExecutionError::Invalid(e.to_string()))
    }
}
fn fixture() -> Json {
    let bytes = include_bytes!("fixtures/body-runtime-reference.json.gz");
    assert_eq!(bytes.len(), 624390);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "81b9293501b53ffc8f9437d9c4a901b988ddc70a9a7e2bd1f23872e487801a46"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    serde_json::from_str(&text).unwrap()
}
fn scalar(value: &Json) -> GraphValue {
    GraphValue::parse(&serde_json::value::RawValue::from_string(value.to_string()).unwrap())
        .unwrap()
}
fn graph(record: &Json) -> MemoryGraph {
    let ir = StructuralIr::from_json(&record["graph"].to_string()).unwrap();
    let nodes: Vec<SourceNode> = serde_json::from_value(record["nodes"].clone()).unwrap();
    let properties = record["properties"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(id, p)| {
            (
                id.clone(),
                p.as_object()
                    .unwrap()
                    .iter()
                    .map(|(k, v)| (k.clone(), scalar(v)))
                    .collect(),
            )
        })
        .collect();
    MemoryGraph::new(&ir)
        .unwrap()
        .with_source_nodes(nodes, properties, BTreeMap::new(), true)
        .with_source_snapshot_id(0)
}
fn bindings(case: &Json) -> Bindings {
    case["bindings"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(role, v)| {
            let value = match v["kind"].as_str().unwrap() {
                "node" => Value::Node(Arc::new(
                    serde_json::from_value(v["value"].clone()).unwrap(),
                )),
                "unknown" => Value::unknown(v["value"]["reason"].as_str().unwrap()),
                "scalar" => Value::Scalar(scalar(&v["value"])),
                _ => panic!("fixture binding kind"),
            };
            (role.clone(), value)
        })
        .collect()
}
#[test]
fn original_body_runtime_matches_prepared_patterns_on_fresh_graphs() {
    let fixture = fixture();
    let graphs: Vec<_> = fixture["graphs"]
        .as_array()
        .unwrap()
        .iter()
        .map(graph)
        .collect();
    let mut errors = vec![];
    for case in fixture["cases"].as_array().unwrap() {
        let pattern: BodyPattern = serde_json::from_value(case["pattern"].clone()).unwrap();
        let mut services = Services {
            checks: 0,
            limit: Some(2_000_000),
        };
        if let Err(e) = validate(&pattern, &mut || services.check()) {
            errors.push(format!("{} validation: {e}", case["name"]));
            continue;
        }
        let mut cursor = BodyCursor::new(
            &graphs[case["graph"].as_u64().unwrap() as usize],
            Arc::new(pattern),
            bindings(case),
        );
        let mut got = vec![];
        let result = (|| -> Result<()> {
            while let Some(matched) = cursor.next(&mut services)? {
                got.push(serde_json::to_value(matched).unwrap());
                if got.len() > 2000 {
                    return Err(ExecutionError::Invalid("unexpected match explosion".into()));
                }
            }
            Ok(())
        })();
        match result {
            Ok(()) => {
                let got = Json::Array(got);
                if got != case["matches"] {
                    errors.push(format!(
                        "{} matches: {} != {}",
                        case["name"], got, case["matches"]
                    ));
                }
            }
            Err(e) => errors.push(format!("{} execution: {e}", case["name"])),
        }
    }
    assert!(
        errors.is_empty(),
        "{} failing cases:\n{}",
        errors.len(),
        errors
            .iter()
            .take(20)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}
#[test]
fn body_cursor_releases_services_and_propagates_interruptions() {
    let f = fixture();
    let case = f["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "straight/body-direct/7/0/0")
        .unwrap();
    let graph = graph(&f["graphs"][0]);
    let pattern: BodyPattern = serde_json::from_value(case["pattern"].clone()).unwrap();
    let mut input = bindings(case);
    input.remove("f");
    let mut cursor = BodyCursor::new(&graph, Arc::new(pattern), input);
    let mut services = Services {
        checks: 0,
        limit: None,
    };
    assert!(cursor.next(&mut services).unwrap().is_some());
    // Downstream work can borrow the same services after each yielded row.
    services.check().unwrap();
    let checks_at_first = services.checks;
    services.limit = Some(checks_at_first);
    assert!(matches!(
        cursor.next(&mut services),
        Err(ExecutionError::Exhausted("body_test"))
    ));
}
#[test]
fn malformed_caller_built_body_patterns_fail_validation() {
    let f = fixture();
    let mut pattern: BodyPattern =
        serde_json::from_value(f["cases"][0]["pattern"].clone()).unwrap();
    pattern.clauses[0].kind = "unrecognized-body-step".into();
    assert!(matches!(
        validate(&pattern, &mut || Ok(())),
        Err(ExecutionError::Invalid(_))
    ));
    let mut pattern: BodyPattern =
        serde_json::from_value(f["cases"][0]["pattern"].clone()).unwrap();
    pattern.clauses[0].expressions.clear();
    pattern.clauses[0].kind = "assign".into();
    assert!(validate(&pattern, &mut || Ok(())).is_err());
    let mut malformed = f["cases"][0]["pattern"].clone();
    malformed["clauses"][0]["expressions"][0]["kind"] =
        Json::String("unrecognized-source-operand".into());
    let malformed: BodyPattern = serde_json::from_value(malformed).unwrap();
    assert!(validate(&malformed, &mut || Ok(())).is_err());
    let binary = f["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "straight/body-direct/44/0/0")
        .unwrap();
    let mut malformed = binary["pattern"].clone();
    malformed["clauses"][0]["expressions"][0]["args"][1]["value"] = Json::String("left".into());
    let malformed: BodyPattern = serde_json::from_value(malformed).unwrap();
    assert!(validate(&malformed, &mut || Ok(())).is_err());
}
