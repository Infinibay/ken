use flate2::read::GzDecoder;
use ken_program::StructuralIr;
use ken_query::execution::{Execution, ExecutionOptions, MemoryGraph};
use serde_json::Value;
use std::io::Read;
#[path = "support/execution_fixture.rs"]
#[allow(dead_code)]
mod fixture;

#[test]
fn frozen_source_semantics_filters_inventories_and_fields_match() {
    pin(
        include_bytes!("fixtures/source-runtime-reference.json.gz"),
        10736,
        "520edd028c3fae3ef5077d7e6161241daa386ae15768308ca3af71e6828a4053",
    );
    check(include_bytes!("fixtures/source-runtime-reference.json.gz"));
}
#[test]
fn frozen_receiver_initializers_and_occurrence_usages_match() {
    pin(
        include_bytes!("fixtures/source-operations-reference.json.gz"),
        13483,
        "23e1e5a133cd8c7492fd408bb322e717ef54f638b8311726d4692fc4c092f00c",
    );
    check(include_bytes!(
        "fixtures/source-operations-reference.json.gz"
    ));
}
fn pin(bytes: &[u8], length: usize, sha: &str) {
    use sha2::Digest;
    assert_eq!(bytes.len(), length);
    assert_eq!(format!("{:x}", sha2::Sha256::digest(bytes)), sha);
}
fn records(bytes: &[u8]) -> Value {
    let mut text = String::new();
    GzDecoder::new(bytes).read_to_string(&mut text).unwrap();
    serde_json::from_str(&text).unwrap()
}
fn execute_case(case: &Value) -> Value {
    let graph =
        MemoryGraph::new(&StructuralIr::from_json(&case["graph"].to_string()).unwrap()).unwrap();
    let result = Execution::new(serde_json::from_value(case["options"].clone()).unwrap())
        .unwrap()
        .execute(&graph, &fixture::query(&case["query"]))
        .unwrap();
    let mut result = serde_json::to_value(result).unwrap();
    result.as_object_mut().unwrap().remove("stats");
    result
}
#[test]
fn constructor_inventory_cardinality_uses_typed_numeric_equality() {
    let data = records(include_bytes!("fixtures/source-runtime-reference.json.gz"));
    let mut errors = vec![];
    for nonempty in [false, true] {
        for quantifier in ["every", "exists"] {
            let name = format!(
                "quantifier/{quantifier}/True/{}/possible",
                if nonempty { "['private']" } else { "[]" }
            );
            let mut case = data["cases"]
                .as_array()
                .unwrap()
                .iter()
                .find(|c| c["name"] == name)
                .unwrap()
                .clone();
            for fact in case["graph"]["facts"].as_array_mut().unwrap() {
                if fact["relation"] == "CONSTRUCTOR_INVENTORY" {
                    fact["attrs"]["explicit"] = serde_json::json!(if nonempty { "1" } else { "0" });
                }
            }
            // The identical inventory with no supporting status is the same open-world outcome.
            let mut open = case.clone();
            open["graph"]["facts"]
                .as_array_mut()
                .unwrap()
                .retain(|f| f["relation"] != "CONSTRUCTOR_INVENTORY");
            let got = execute_case(&case);
            let want = execute_case(&open);
            if got != want {
                errors.push(format!("{name}: {got} != {want}"));
            }
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn storage_write_counts_preserve_exact_float_integer_and_null_semantics() {
    let data = records(include_bytes!("fixtures/source-runtime-reference.json.gz"));
    let mut errors = vec![];
    for (label, source, actual, target, want_count, unknown) in [
        (
            "float equality",
            "supported",
            serde_json::json!(9007199254740992.0),
            "9007199254740993",
            0,
            false,
        ),
        (
            "float integer conversion reject",
            "unsupported",
            serde_json::json!(1e23),
            "100000000000000000000000",
            0,
            false,
        ),
        (
            "float integer conversion accept",
            "unsupported",
            serde_json::json!(1e23),
            "99999999999999991611392",
            1,
            false,
        ),
        ("explicit null", "unsupported", Value::Null, "1", 1, true),
    ] {
        let name = format!(
            "writes/{source}/{}/possible",
            if source == "supported" { "None" } else { "1" }
        );
        let mut case = data["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == name)
            .unwrap()
            .clone();
        let relation = if source == "supported" {
            "BINDING_WRITE_COUNT"
        } else {
            "STORAGE_WRITE_COUNT"
        };
        for fact in case["graph"]["facts"].as_array_mut().unwrap() {
            if fact["relation"] == relation {
                fact["attrs"]["count"] = actual.clone();
            }
        }
        case["query"]["nodes"]
            .as_array_mut()
            .unwrap()
            .last_mut()
            .unwrap()["value"][2]["args"][1]["args"][0]["value"] = serde_json::json!(target);
        let got = execute_case(&case);
        let matches = got["matches"].as_array().unwrap();
        if matches.len() != want_count
            || unknown
                && (matches[0]["status"] != "unknown"
                    || matches[0]["unknown"] != serde_json::json!(["source_storage:unknown"]))
        {
            errors.push(format!("{label}: {got}"));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn compiled_exactly_storage_contract_consumes_selected_binding() {
    let data = records(include_bytes!("fixtures/source-runtime-reference.json.gz"));
    let mut case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "writes/supported/None/possible")
        .unwrap()["graph"]
        .clone();
    case["entities"]["x"]["kind"] = serde_json::json!("CALLABLE");
    case["entities"]["binding"]["kind"] = serde_json::json!("STORAGE");
    for fact in case["facts"].as_array_mut().unwrap() {
        if fact["relation"] == "ENTITY" {
            if fact["subject"] == "x" {
                fact["object"] = serde_json::json!("CALLABLE");
            } else if fact["subject"] == "binding" {
                fact["object"] = serde_json::json!("STORAGE");
            }
        }
    }
    let source = "language \"kql/2\";module source;query q{var $binding{name: \"binding\";}callable $x{name: \"x\";writes: exactly($binding,1);}select $x;}";
    let tree = ken_query::parse(source, "source", Default::default()).unwrap();
    let plan = ken_query::compile_relational(&tree, None).unwrap();
    let graph = MemoryGraph::new(&StructuralIr::from_json(&case.to_string()).unwrap()).unwrap();
    let result = Execution::new(Default::default())
        .unwrap()
        .execute(&graph, plan.relational.as_ref().unwrap())
        .unwrap();
    assert_eq!(result.matches.len(), 1);
}
#[test]
fn descriptor_expansion_and_query_work_are_bounded() {
    let data = records(include_bytes!("fixtures/source-runtime-reference.json.gz"));
    let case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "type/int/\"integer\"0/possible")
        .unwrap();
    let mut graph = case["graph"].clone();
    let facts = graph["facts"].as_array_mut().unwrap();
    facts.retain(|f| !f["relation"].as_str().unwrap().starts_with("TYPE_"));
    facts.push(serde_json::json!({"subject":"x","relation":"TYPE_REF","object":"t0","attrs":{},"evidence":[]}));
    for i in 0..18 {
        for (r, o) in [("TYPE_KIND", "list"), ("TYPE_NATIVE", "list")] {
            facts.push(serde_json::json!({"subject":format!("t{i}"),"relation":r,"object":o,"attrs":{},"evidence":[]}));
        }
        if i < 17 {
            for pos in 0..2 {
                facts.push(serde_json::json!({"subject":format!("t{i}"),"relation":"TYPE_ARGUMENT","object":format!("t{}",i+1),"attrs":{"position":pos},"evidence":[]}));
            }
        }
    }
    let graph = MemoryGraph::new(&StructuralIr::from_json(&graph.to_string()).unwrap()).unwrap();
    let plan = fixture::query(&case["query"]);
    let result = Execution::new(Default::default())
        .unwrap()
        .execute(&graph, &plan)
        .unwrap();
    assert!(!result.complete);
    assert_eq!(result.unknown, ["budget:source_types"]);
    let mut options = ExecutionOptions::default();
    options.budget.max_states = Some(10);
    let result = Execution::new(options)
        .unwrap()
        .execute(&graph, &plan)
        .unwrap();
    assert!(!result.complete);
    assert_eq!(result.unknown, ["budget:max_states"]);
}
#[test]
fn compiled_source_status_and_storage_match_public_usage() {
    let raw = r#"{"path":"fixture.py","language":"python","view":"query","version":"1.88.0","entities":{},"operations":[],"facts":[{"subject":"x","relation":"ENTITY","object":"STORAGE","attrs":{"name":"x"},"evidence":[]},{"subject":"x","relation":"TYPE_REF","object":"t","attrs":{},"evidence":[]},{"subject":"t","relation":"TYPE_KIND","object":"int","attrs":{},"evidence":[]},{"subject":"t","relation":"TYPE_NATIVE","object":"int","attrs":{},"evidence":[]}],"capabilities":[],"diagnostics":[],"relations":["ENTITY","TYPE_REF","TYPE_KIND","TYPE_NATIVE"]}"#;
    let graph = MemoryGraph::new(&StructuralIr::from_json(raw).unwrap()).unwrap();
    for property in [
        "type: int;",
        "type_status: known;",
        "type_status: \"known\";",
    ] {
        let source =
            format!("language \"kql/2\";module source;query q{{var $x{{{property}}}select $x;}}");
        let tree = ken_query::parse(&source, "source", Default::default()).unwrap();
        let compiled = ken_query::compile_relational(&tree, None).unwrap();
        let result = Execution::new(Default::default())
            .unwrap()
            .execute(&graph, compiled.relational.as_ref().unwrap())
            .unwrap();
        assert_eq!(result.matches.len(), 1, "{property}");
    }
}
fn check(bytes: &[u8]) {
    let mut text = String::new();
    GzDecoder::new(bytes).read_to_string(&mut text).unwrap();
    let data: Value = serde_json::from_str(&text).unwrap();
    let mut errors = vec![];
    for c in data["cases"].as_array().unwrap() {
        assert!(c.get("error").is_none(), "{}", c["name"]);
        let ir = StructuralIr::from_json(&c["graph"].to_string()).unwrap();
        let graph = MemoryGraph::new(&ir).unwrap();
        let options: ExecutionOptions = serde_json::from_value(c["options"].clone()).unwrap();
        match Execution::new(options)
            .unwrap()
            .execute(&graph, &fixture::query(&c["query"]))
        {
            Ok(result) => {
                let mut got = serde_json::to_value(result).unwrap();
                got.as_object_mut().unwrap().remove("stats");
                if got != c["expected"] {
                    errors.push(format!("{}: {got} != {}", c["name"], c["expected"]));
                }
            }
            Err(e) => errors.push(format!("{}: {e}", c["name"])),
        }
    }
    assert!(
        errors.is_empty(),
        "{} failures: {}",
        errors.len(),
        errors
            .iter()
            .take(12)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}

#[test]
fn captured_usage_columns_have_detached_metadata_without_changing_graph_json() {
    let data = records(include_bytes!(
        "fixtures/source-operations-reference.json.gz"
    ));
    let case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "usage/argument/[]/possible")
        .unwrap();
    let graph =
        MemoryGraph::new(&StructuralIr::from_json(&case["graph"].to_string()).unwrap()).unwrap();
    let result = Execution::new(serde_json::from_value(case["options"].clone()).unwrap())
        .unwrap()
        .execute(&graph, &fixture::query(&case["query"]))
        .unwrap();
    assert_eq!(result.matches.len(), 2);
    for row in &result.matches {
        let id = &row.bindings["$use"];
        let metadata = result
            .usage_metadata
            .get(id)
            .expect("captured usage metadata is detached from optional proof encoding");
        if id.starts_with("@unknown:") {
            assert!(metadata.is_empty());
            continue;
        }
        assert_eq!(metadata["kind"].string().as_deref(), Some("argument"));
        assert_eq!(metadata["path"].string().as_deref(), Some("fixture.py"));
        assert_eq!(metadata["consumer_name"].string().as_deref(), Some("call"));
    }
    assert!(
        serde_json::to_value(&result)
            .unwrap()
            .get("usage_metadata")
            .is_none()
    );
}
