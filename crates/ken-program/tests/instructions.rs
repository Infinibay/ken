use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    instructions::{Program, lower},
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::Read;
#[derive(Deserialize)]
struct Case {
    name: String,
    graph: StructuralIr,
    program: Program,
    assembly: String,
}
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
fn cases() -> Vec<Case> {
    let mut raw = String::new();
    GzDecoder::new(&include_bytes!("fixtures/instructions-reference.json.gz")[..])
        .read_to_string(&mut raw)
        .unwrap();
    serde_json::from_str::<Corpus>(&raw).unwrap().cases
}
#[test]
fn native_instruction_values_places_regions_effects_and_assembly_match_106_frozen_observations() {
    for case in cases() {
        let program = lower(&case.graph).unwrap();
        program.verify().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&program.to_json().unwrap()).unwrap(),
            serde_json::from_str::<Value>(&case.program.to_json().unwrap()).unwrap(),
            "{}",
            case.name
        );
        assert_eq!(program.format().unwrap(), case.assembly, "{}", case.name);
        let reopened = Program::from_json(&program.to_json().unwrap()).unwrap();
        assert_eq!(reopened.format().unwrap(), program.format().unwrap());
    }
}
#[test]
fn invalid_instruction_schema_operands_regions_and_value_visibility_are_rejected() {
    let base: Value = serde_json::from_str(&cases()[0].program.to_json().unwrap()).unwrap();
    let mut invalid = Vec::new();
    let mut x = base.clone();
    x["schema"] = json!("foreign/1");
    invalid.push(x);
    let mut x = base.clone();
    x["functions"][0]["parameters"]
        .as_array_mut()
        .unwrap()
        .push(json!("missing-place"));
    invalid.push(x);
    let mut x = base.clone();
    x["functions"][0]["body"]["instructions"][0]["opcode"] = json!("foreign");
    invalid.push(x);
    let mut x = base.clone();
    x["functions"][0]["body"]["instructions"][0]["operands"] =
        json!([{"kind":"value","ref":"not-defined","role":""}]);
    invalid.push(x);
    let mut x = base.clone();
    x["functions"][0]["body"]["outputs"] = json!(["outside-region"]);
    invalid.push(x);
    let mut x = base.clone();
    let f = x["functions"][0].clone();
    x["functions"].as_array_mut().unwrap().push(f);
    invalid.push(x);
    for data in invalid {
        assert!(Program::from_json(&data.to_string()).is_err(), "{data}");
    }
    let mut graph = cases().remove(0).graph;
    graph.view = "query".into();
    assert!(lower(&graph).is_err());
}
