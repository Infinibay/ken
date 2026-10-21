//! Literal original identities, captured without running any native model.
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use serde_json::{Value, json};

fn originals() -> Vec<Value> {
    [
        include_str!("fixtures/profile-identity/macos.json"),
        include_str!("fixtures/profile-identity/linux.json"),
        include_str!("fixtures/profile-identity/macos-torch.json"),
        include_str!("fixtures/profile-identity/macos-mlx.json"),
    ]
    .into_iter()
    .map(|raw| serde_json::from_str(raw).unwrap())
    .collect()
}

#[test]
fn captured_original_encoder_keys_tokenizers_and_defaults_match_on_both_platforms() {
    for original in originals() {
        let runtime =
            LegacyRuntimeIdentity::from_json(&original["legacy_runtime"].to_string()).unwrap();
        for row in original["encoders"].as_array().unwrap() {
            let encoder = EncoderSpec::from_json(&row["input"].to_string()).unwrap();
            assert_eq!(
                serde_json::to_value(&encoder).unwrap(),
                row["config"],
                "{}",
                row["label"]
            );
            assert_eq!(encoder.key(&runtime).unwrap(), row["key"]);
            assert_eq!(
                encoder.tokenizer_revision(&runtime).unwrap(),
                row["tokenizer_revision"]
            );
        }
    }
}

#[test]
fn captured_nested_profiles_keep_exact_python_serialization_and_all_revisions() {
    for original in originals() {
        let runtime =
            LegacyRuntimeIdentity::from_json(&original["legacy_runtime"].to_string()).unwrap();
        for row in original["profiles"].as_array().unwrap() {
            let profile = RetrievalProfile::from_json(&row["input"].to_string()).unwrap();
            assert_eq!(profile.to_json().unwrap(), row["serialized_python"]);
            assert_eq!(serde_json::to_value(&profile).unwrap(), row["config"]);
            assert_eq!(
                profile.fingerprint(&runtime).unwrap(),
                row["fingerprint"],
                "{}",
                row["label"]
            );
            for view in ["identity", "behavior"] {
                assert_eq!(
                    profile.vector_revision(view, &runtime).unwrap(),
                    row["vector_revisions"][view]
                );
            }
            assert!(profile.vector_revision("unknown", &runtime).is_err());
            let roundtrip = RetrievalProfile::from_json(&profile.to_json().unwrap()).unwrap();
            assert_eq!(roundtrip, profile);
        }
    }
}

#[test]
fn original_invalid_specs_and_nested_relationships_fail_without_loading_a_model() {
    for original in originals() {
        for row in original["invalid_encoders"].as_array().unwrap() {
            assert!(
                EncoderSpec::from_json(&row["input"].to_string()).is_err(),
                "{row}"
            );
        }
        for row in original["invalid_profiles"].as_array().unwrap() {
            assert!(
                RetrievalProfile::from_json(&row["input"].to_string()).is_err(),
                "{row}"
            );
        }
        let upgrade = &original["representation_upgrade"];
        assert!(RetrievalProfile::from_json(&upgrade["input"].to_string()).is_err());
        let profile =
            RetrievalProfile::from_json_with_upgrade(&upgrade["input"].to_string(), true).unwrap();
        assert_eq!(serde_json::to_value(profile).unwrap(), upgrade["config"]);
    }
}

#[test]
fn runtime_declarations_require_all_original_ordered_packages_and_no_duplicates() {
    let original = &originals()[0];
    let base = &original["legacy_runtime"];
    let mut mutations = Vec::new();
    let mut value = base.clone();
    value["backends"].as_object_mut().unwrap().remove("static");
    mutations.push(value);
    let mut value = base.clone();
    value["backends"]["static"].as_array_mut().unwrap().pop();
    mutations.push(value);
    let mut value = base.clone();
    let duplicate = value["backends"]["static"][0].clone();
    value["backends"]["static"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    mutations.push(value);
    let mut value = base.clone();
    value["contextual"][0][0] = json!("unknown");
    mutations.push(value);
    let mut value = base.clone();
    value["evidence"][0][1] = json!("");
    mutations.push(value);
    let mut value = base.clone();
    value["format"] = json!("native-installed-python");
    mutations.push(value);
    for value in mutations {
        assert!(
            LegacyRuntimeIdentity::from_json(&value.to_string()).is_err(),
            "{value}"
        );
    }
    let mut value = base.clone();
    value["backends"]["static"][0][1] = json!("unavailable");
    LegacyRuntimeIdentity::from_json(&value.to_string()).unwrap();
}

#[test]
fn declared_runtime_and_nested_configuration_changes_invalidate_compatible_identity() {
    let original = &originals()[0];
    let runtime =
        LegacyRuntimeIdentity::from_json(&original["legacy_runtime"].to_string()).unwrap();
    let input = &original["profiles"][0]["config"];
    let profile = RetrievalProfile::from_json(&input.to_string()).unwrap();
    let old = profile.fingerprint(&runtime).unwrap();
    for (pointer, replacement) in [
        ("/behavior/dtype", json!("float16")),
        ("/behavior/batch_size", json!(8)),
        ("/behavior/sequence_length", json!(384)),
        ("/max_tokens", json!(128)),
    ] {
        let mut changed = input.clone();
        *changed.pointer_mut(pointer).unwrap() = replacement;
        assert_ne!(
            RetrievalProfile::from_json(&changed.to_string())
                .unwrap()
                .fingerprint(&runtime)
                .unwrap(),
            old
        );
    }
    let mut declaration = original["legacy_runtime"].clone();
    declaration["backends"]["static"][1][1] = json!("changed-tokenizer-version");
    let changed = LegacyRuntimeIdentity::from_json(&declaration.to_string()).unwrap();
    assert_ne!(profile.fingerprint(&changed).unwrap(), old);
    assert_ne!(
        profile.identity.key(&changed).unwrap(),
        profile.identity.key(&runtime).unwrap()
    );
    assert_ne!(
        profile.identity.tokenizer_revision(&changed).unwrap(),
        profile.identity.tokenizer_revision(&runtime).unwrap()
    );
    assert_ne!(
        profile.vector_revision("identity", &changed).unwrap(),
        profile.vector_revision("identity", &runtime).unwrap()
    );
}
