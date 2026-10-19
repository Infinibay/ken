use ken_models::model_policy::{
    InitialModelPin, LEGACY_MODEL, ModelPolicy, ModelUpgrade, POTION_MODEL, ProjectModelFacts,
    is_asymmetric, prompts_for,
};
use serde_json::{Value, json};

fn fixtures() -> (Value, Value) {
    (
        serde_json::from_str(include_str!(
            "../../../docs/validation/rust-migration-2026-10-19/m2-policy/cases.json"
        ))
        .unwrap(),
        serde_json::from_str(include_str!(
            "../../../docs/validation/rust-migration-2026-10-19/m2-policy/reference.json"
        ))
        .unwrap(),
    )
}

// A precedence change, trimming raw overrides, or confusing absent and empty
// metadata must disagree with decisions captured from the real original.
#[test]
fn frozen_original_histories_match_model_and_initial_pin_decisions() {
    let (cases, reference) = fixtures();
    for oracle in reference["oracles"].as_array().unwrap() {
        let expected = oracle["results"].as_array().unwrap();
        assert_eq!(expected.len(), 1292);
        for (case, expected) in cases["cases"].as_array().unwrap().iter().zip(expected) {
            let input = &case["input"];
            let policy = ModelPolicy::new(input["user_config"]["default_model"].as_str());
            let facts = ProjectModelFacts {
                recorded_model: input["facts"]["recorded_model"].as_str().map(str::to_owned),
                file_vectors_present: input["facts"]["file_vectors_present"].as_bool().unwrap(),
            };
            let environment = input["environment"].as_str();
            let project = policy.resolve_project(&facts, environment);
            let pin = project
                .initial_pin
                .map(|p| json!({"model":p.model,"document_space":p.document_space}));
            let active: Vec<_> = input["forced_variants"]
                .as_array()
                .unwrap()
                .iter()
                .map(|forced| {
                    policy.active_model(
                        input["project_visible"]
                            .as_bool()
                            .unwrap()
                            .then_some(&facts),
                        environment,
                        forced.as_str(),
                    )
                })
                .collect();
            let upgrade = policy
                .pending_upgrade(&facts, environment)
                .map(|u| json!({"current":u.current,"recommended":u.recommended}));
            assert_eq!(
                json!({"id":case["id"],"recommended":policy.recommended_model(),
                    "project":{"model":project.model,"initial_pin":pin},
                    "active":active,"upgrade":upgrade}),
                *expected,
                "{} on {}",
                case["id"],
                oracle["platform"]
            );
        }
    }
}

#[test]
fn exact_original_prompts_preserve_prefixes_case_and_whitespace() {
    let (_, reference) = fixtures();
    for oracle in reference["oracles"].as_array().unwrap() {
        for expected in oracle["prompts"].as_array().unwrap() {
            let model = expected["model"].as_str().unwrap();
            let prompts = prompts_for(model);
            assert_eq!(
                prompts.query,
                expected["query"].as_str().unwrap(),
                "{model:?}"
            );
            assert_eq!(
                prompts.passage,
                expected["passage"].as_str().unwrap(),
                "{model:?}"
            );
            assert_eq!(is_asymmetric(model), expected["asymmetric"], "{model:?}");
        }
    }
}

#[test]
fn policy_snapshots_and_results_are_owned_and_independent() {
    let mut configured = String::from(" user/default ");
    let policy = ModelPolicy::new(Some(&configured));
    configured.clear();
    let mut facts = ProjectModelFacts {
        recorded_model: None,
        file_vectors_present: false,
    };
    let mut selected = policy.resolve_project(&facts, None);
    assert_eq!(selected.model, " user/default ");
    assert_eq!(
        selected.initial_pin,
        Some(InitialModelPin {
            model: " user/default ".into(),
            document_space: 2,
        })
    );
    selected.model.clear();
    selected.initial_pin.as_mut().unwrap().model.clear();
    facts.recorded_model = Some("another/project".into());
    assert_eq!(policy.recommended_model(), " user/default ");
    assert_eq!(
        policy.resolve_project(&facts, None).model,
        "another/project"
    );
    assert_eq!(policy.active_model(None, None, None), " user/default ");
    assert_eq!(
        ModelPolicy::new(None).active_model(None, None, None),
        POTION_MODEL
    );
    for absent in ["", "\u{1c}\u{85}\u{a0}", "\t\n "] {
        assert_eq!(
            ModelPolicy::new(Some(absent)).recommended_model(),
            POTION_MODEL
        );
    }
    for raw in ["\0", "\u{200b}", "\u{a0}model/default\u{a0}"] {
        assert_eq!(ModelPolicy::new(Some(raw)).recommended_model(), raw);
    }
    let legacy = ModelPolicy::new(Some(LEGACY_MODEL));
    facts.recorded_model = Some(LEGACY_MODEL.into());
    assert_eq!(
        legacy.pending_upgrade(&facts, None),
        Some(ModelUpgrade {
            current: LEGACY_MODEL.into(),
            recommended: LEGACY_MODEL.into(),
        })
    );
}

#[test]
fn forced_and_environment_overrides_do_not_leak_between_threads() {
    let workers: Vec<_> = (0..8)
        .map(|index| {
            std::thread::spawn(move || {
                let default = format!("default/{index}");
                let forced = format!("forced/{index}");
                let policy = ModelPolicy::new(Some(&default));
                let facts = ProjectModelFacts {
                    recorded_model: Some("stored/model".into()),
                    file_vectors_present: true,
                };
                for _ in 0..100 {
                    assert_eq!(
                        policy.active_model(Some(&facts), Some("environment"), Some(&forced)),
                        forced
                    );
                    assert_eq!(
                        policy.resolve_project(&facts, Some("environment")).model,
                        "environment"
                    );
                    assert_eq!(
                        policy.active_model(Some(&facts), Some("\0"), Some("")),
                        "\0"
                    );
                    assert_eq!(
                        policy.active_model(Some(&facts), Some(""), Some("")),
                        "stored/model"
                    );
                    assert_eq!(policy.active_model(None, None, None), default);
                    assert!(policy.pending_upgrade(&facts, Some(" ")).is_none());
                }
            })
        })
        .collect();
    for worker in workers {
        worker.join().unwrap();
    }
}

#[test]
fn known_vector_presence_never_gets_a_fresh_pin() {
    let policy = ModelPolicy::new(None);
    for recorded in [None, Some(""), Some("stored/model"), Some(LEGACY_MODEL)] {
        for environment in [None, Some(""), Some(" "), Some("\0")] {
            let facts = ProjectModelFacts {
                recorded_model: recorded.map(str::to_owned),
                file_vectors_present: true,
            };
            assert!(
                policy
                    .resolve_project(&facts, environment)
                    .initial_pin
                    .is_none()
            );
        }
    }
    let empty = ProjectModelFacts {
        recorded_model: Some("".into()),
        file_vectors_present: false,
    };
    let selected = policy.resolve_project(&empty, None);
    assert_eq!(selected.model, POTION_MODEL);
    assert!(selected.initial_pin.is_none());
    let inferred = ProjectModelFacts {
        recorded_model: None,
        file_vectors_present: true,
    };
    assert_eq!(policy.resolve_project(&inferred, None).model, LEGACY_MODEL);
}
