#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "support/oracle_profiles.rs"]
mod profiles;
fn repo() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
#[test]
fn actual_context_profile_selects_a_complete_preserved_original() {
    let reference =
        profiles::registered("context", &profiles::context_descriptor(), &repo()).unwrap();
    let original: serde_json::Value = serde_json::from_slice(&reference.bytes).unwrap();
    assert_eq!(original["cases"].as_array().unwrap().len(), 20);
    assert_eq!(original["results"].as_array().unwrap().len(), 20);
}
#[test]
fn unknown_and_ambiguous_descriptors_cannot_fall_back() {
    let mut descriptor = profiles::context_descriptor();
    descriptor["features"]["unsupported"] = true.into();
    assert!(profiles::registered("context", &descriptor, &repo()).is_err());
    let mut index: serde_json::Value = serde_json::from_str(profiles::INDEX).unwrap();
    let row = index["families"]["context"][0].clone();
    index["families"]["context"]
        .as_array_mut()
        .unwrap()
        .push(row.clone());
    assert!(profiles::select(&index, "context", &row["descriptor"], &repo()).is_err());
}
#[test]
fn changed_reference_bytes_are_rejected_before_parsing() {
    let mut index: serde_json::Value = serde_json::from_str(profiles::INDEX).unwrap();
    let descriptor = index["families"]["context"][0]["descriptor"].clone();
    index["families"]["context"][0]["reference"]["sha256"] = "0".repeat(64).into();
    assert!(profiles::select(&index, "context", &descriptor, &repo()).is_err());
}

#[test]
fn changed_runtime_registration_cannot_keep_the_old_context_profile() {
    let mut registration: serde_json::Value =
        serde_json::from_str(include_str!("../resources/onnx-runtime-libraries.json")).unwrap();
    let core = registration["libraries"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r["os"] == "linux" && r["arch"] == "x86_64")
        .unwrap();
    core["sha256"] = "0".repeat(64).into();
    let descriptor = profiles::context_descriptor_for_registration(&registration).unwrap();
    assert!(profiles::registered("context", &descriptor, &repo()).is_err());
}
