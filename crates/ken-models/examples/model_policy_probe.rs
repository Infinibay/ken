//! Observe pure native decisions from explicit facts, without model artifacts.
use ken_models::model_policy::{ModelPolicy, ProjectModelFacts, is_asymmetric, prompts_for};
use serde::{Deserialize, Deserializer};
use serde_json::{Value, json};
use std::{collections::HashSet, io::Read};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    cases: Vec<Case>,
    prompts: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    input: Input,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    user_config: Value,
    #[serde(deserialize_with = "nullable_string")]
    environment: Option<String>,
    project_visible: bool,
    facts: Facts,
    forced_variants: Vec<Option<String>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Facts {
    #[serde(deserialize_with = "nullable_string")]
    recorded_model: Option<String>,
    file_vectors_present: bool,
}

// A nullable field must still be present in the explicit input contract.
fn nullable_string<'de, D: Deserializer<'de>>(value: D) -> Result<Option<String>, D::Error> {
    Option::<String>::deserialize(value)
}

fn run(input: &str) -> Result<Value, Box<dyn std::error::Error>> {
    let request: Request = serde_json::from_str(input)?;
    let unique: HashSet<_> = request.cases.iter().map(|case| case.id.as_str()).collect();
    if request.cases.is_empty()
        || unique.len() != request.cases.len()
        || request.cases.iter().any(|case| case.id.is_empty())
    {
        return Err("distinct nonempty case IDs required".into());
    }
    let mut results = Vec::with_capacity(request.cases.len());
    for case in request.cases {
        let input = case.input;
        let policy = ModelPolicy::new(
            input
                .user_config
                .get("default_model")
                .and_then(Value::as_str),
        );
        let facts = ProjectModelFacts {
            recorded_model: input.facts.recorded_model,
            file_vectors_present: input.facts.file_vectors_present,
        };
        let environment = input.environment.as_deref();
        let project = policy.resolve_project(&facts, environment);
        let pin = project
            .initial_pin
            .map(|pin| json!({"model":pin.model,"document_space":pin.document_space}));
        let active: Vec<_> = input
            .forced_variants
            .iter()
            .map(|forced| {
                policy.active_model(
                    input.project_visible.then_some(&facts),
                    environment,
                    forced.as_deref(),
                )
            })
            .collect();
        let upgrade = policy
            .pending_upgrade(&facts, environment)
            .map(|upgrade| json!({"current":upgrade.current,"recommended":upgrade.recommended}));
        results.push(
            json!({"id":case.id,"recommended":policy.recommended_model(),
            "project":{"model":project.model,"initial_pin":pin},"active":active,"upgrade":upgrade}),
        );
    }
    let prompts: Vec<_> = request
        .prompts
        .iter()
        .map(|model| {
            let prompts = prompts_for(model);
            json!({"model":model,"query":prompts.query,"passage":prompts.passage,
            "asymmetric":is_asymmetric(model)})
        })
        .collect();
    Ok(json!({"format":"ken-model-policy-native/1",
        "runtime":{"engine":"rust","ken_models":env!("CARGO_PKG_VERSION"),
            "unicode":"15.0.0","model_runtime_needed":false},
        "results":results,"prompts":prompts}))
}

fn main() {
    let result = (|| {
        let mut input = String::new();
        std::io::stdin().read_to_string(&mut input)?;
        Ok::<_, Box<dyn std::error::Error>>(serde_json::to_string(&run(&input)?)?)
    })();
    match result {
        Ok(output) => println!("{output}"),
        Err(error) => {
            eprintln!("model_policy_probe: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
#[path = "../tests/support/fixture_json.rs"]
mod fixture_json;

#[cfg(test)]
mod tests {
    use serde_json::{Value, json};

    #[test]
    fn probe_executes_every_frozen_history_without_expected_values_in_request() {
        let input: Value = serde_json::from_slice(&super::fixture_json::decode(include_bytes!(
            "../tests/fixtures/portable/model-policy-cases.json.gz"
        )))
        .unwrap();
        let oracle: Value = serde_json::from_slice(&super::fixture_json::decode(include_bytes!(
            "../tests/fixtures/portable/model-policy-reference.json.gz"
        )))
        .unwrap();
        let cases: Vec<_> = input["cases"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| json!({"id":row["id"],"input":row["input"]}))
            .collect();
        let result =
            super::run(&json!({"cases":cases,"prompts":input["prompts"]}).to_string()).unwrap();
        assert_eq!(result["results"], oracle["oracles"][0]["results"]);
        assert_eq!(result["prompts"], oracle["oracles"][0]["prompts"]);
        assert_eq!(result["format"], "ken-model-policy-native/1");
        assert_eq!(
            result["runtime"],
            json!({"engine":"rust","ken_models":"0.18.0",
            "unicode":"15.0.0","model_runtime_needed":false})
        );
    }

    #[test]
    fn probe_rejects_missing_fields_wrong_types_duplicate_ids_and_expected_injection() {
        let valid = json!({"cases":[{"id":"one","input":{
            "user_config":null,"environment":null,"project_visible":true,
            "facts":{"recorded_model":null,"file_vectors_present":false},
            "forced_variants":[null,"","\0"]}}],"prompts":["intfloat/e5-base"]});
        let mut damaged = Vec::new();
        for key in ["cases", "prompts"] {
            let mut request = valid.clone();
            request.as_object_mut().unwrap().remove(key);
            damaged.push(request);
        }
        for key in [
            "user_config",
            "environment",
            "project_visible",
            "facts",
            "forced_variants",
        ] {
            let mut request = valid.clone();
            request["cases"][0]["input"]
                .as_object_mut()
                .unwrap()
                .remove(key);
            damaged.push(request);
        }
        for key in ["recorded_model", "file_vectors_present"] {
            let mut request = valid.clone();
            request["cases"][0]["input"]["facts"]
                .as_object_mut()
                .unwrap()
                .remove(key);
            damaged.push(request);
        }
        for (path, value) in [
            ("/cases/0/input/environment", json!(false)),
            ("/cases/0/input/project_visible", json!(1)),
            ("/cases/0/input/facts/recorded_model", json!(7)),
            ("/cases/0/input/facts/file_vectors_present", json!(null)),
            ("/cases/0/input/forced_variants/0", json!(false)),
            ("/cases/0/id", json!("")),
            ("/prompts/0", json!(1)),
            ("/cases", json!([])),
        ] {
            let mut request = valid.clone();
            *request.pointer_mut(path).unwrap() = value;
            damaged.push(request);
        }
        let mut duplicate = valid.clone();
        let case = duplicate["cases"][0].clone();
        duplicate["cases"].as_array_mut().unwrap().push(case);
        damaged.push(duplicate);
        for path in ["", "/cases/0", "/cases/0/input", "/cases/0/input/facts"] {
            let mut request = valid.clone();
            request
                .pointer_mut(path)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .insert("expected".into(), json!({"model":"forged"}));
            damaged.push(request);
        }
        for request in damaged {
            assert!(
                super::run(&request.to_string()).is_err(),
                "accepted {request}"
            );
        }
        assert!(super::run(&valid.to_string()).is_ok());
        assert!(super::run("{").is_err());
    }
}
