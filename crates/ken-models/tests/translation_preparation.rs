use ken_models::{FrozenTranslationRuntime, ModelError, TranslationModel};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};

const FILES: [&str; 5] = [
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
];

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/translation/tiny")
}
fn definition() -> Value {
    serde_json::from_str::<Value>(include_str!("fixtures/translation/tiny/manifest.json")).unwrap()
        ["definition"]
        .clone()
}
fn record(bytes: &[u8]) -> Value {
    json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))})
}
fn source_copy(root: &Path) -> PathBuf {
    let source = root.join("a".repeat(40));
    fs::create_dir(&source).unwrap();
    for name in FILES {
        fs::copy(
            fixtures().join("a".repeat(40)).join(name),
            source.join(name),
        )
        .unwrap();
    }
    source
}
fn destination(root: &Path) -> PathBuf {
    root.join("b".repeat(40))
}

#[test]
fn original_full_recipe_and_both_runtime_compatibility_revisions_are_exact() {
    let raw = include_str!("../../../src/ken/embedder/data/es-en-ct2-int8.json");
    let model = TranslationModel::from_json(raw).unwrap();
    assert_eq!(
        model.recipe_key(),
        "1af342f7677e9f51477171000e5aa6e6527590a715f064bd64679c1aa491a9f0"
    );
    let reference: Value = serde_json::from_str(include_str!(
        "../../../docs/validation/rust-migration-2026-10-19/m2-translation/reference.json"
    ))
    .unwrap();
    for oracle in reference["oracles"].as_array().unwrap() {
        let profile = match oracle["platform"].as_str().unwrap() {
            "Darwin" => FrozenTranslationRuntime::MacOS483,
            "Linux" => FrozenTranslationRuntime::Linux482,
            _ => panic!(),
        };
        assert_eq!(
            model.compatible_identity(profile),
            oracle["results"][0]["identity"]
        );
        assert_eq!(
            model.compatible_revision(profile),
            oracle["results"][0]["revision"].as_str().unwrap()
        );
    }
    assert_eq!(
        model.cache_path(Path::new("base")),
        Path::new(
            "base/models/translation/1af342f7677e9f51477171000e5aa6e6527590a715f064bd64679c1aa491a9f0/c96e2c5399ebfae4fc43d9669556b9afa74bb69d"
        )
    );
}

#[test]
fn nested_non_ascii_array_metadata_keeps_the_original_python_recipe_hash() {
    let mut declaration = definition();
    declaration["attribution"] = json!(["á", "🦀"]);
    let model = TranslationModel::from_json(&declaration.to_string()).unwrap();
    assert_eq!(
        model.recipe_key(),
        "2614c9f5d191aee0d29a3cfe2f4b0780a906427e7150c5b4cfa7043d06a8e73a"
    );
}

#[test]
fn registration_rejects_ambiguous_keys_and_enforces_the_explicit_json_byte_limit() {
    let declaration = definition();
    let duplicate = format!(
        "{{\"source\":{},\"source\":{},\"derived\":{}}}",
        declaration["source"], declaration["source"], declaration["derived"]
    );
    assert!(TranslationModel::from_json(&duplicate).is_err());
    let raw = declaration.to_string();
    let padded = format!("{}{raw}", " ".repeat(4 * 1024 * 1024 - raw.len()));
    assert!(TranslationModel::from_json(&padded).is_ok());
    assert!(TranslationModel::from_json(&(padded + " ")).is_err());
}

#[test]
fn tiny_preparation_matches_original_bytes_and_keeps_verified_owned_snapshots() {
    let model = TranslationModel::from_json(&definition().to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let source = source_copy(temp.path());
    let target = destination(temp.path());
    let prepared = model.prepare(Some(&source), &target).unwrap();
    for name in FILES {
        assert_eq!(
            prepared.artifact(name).unwrap(),
            fs::read(fixtures().join("prepared").join("b".repeat(40)).join(name)).unwrap()
        );
    }
    fs::remove_dir_all(&source).unwrap();
    assert_eq!(
        model
            .prepare(Some(&source), &target)
            .unwrap()
            .artifact("model.bin")
            .unwrap(),
        b"weights"
    );
    fs::write(target.join("model.bin"), b"changed").unwrap();
    assert_eq!(prepared.artifact("model.bin").unwrap(), b"weights");
    assert!(model.prepare(None, &target).is_err());
    assert!(prepared.artifact("unregistered").is_err());
}

#[test]
fn ordered_nested_json_uses_python_ascii_escaping_without_sorting() {
    let temp = tempfile::tempdir().unwrap();
    let source = source_copy(temp.path());
    let raw = "{\"z\":\"Ω\",\"a\":[{\"last\":null,\"first\":true}],\"n\":0,\"min\":-9223372036854775808,\"max\":18446744073709551615}".as_bytes();
    let want = b"{\n  \"z\": \"\\u03a9\",\n  \"a\": [\n    {\n      \"last\": null,\n      \"first\": true\n    }\n  ],\n  \"n\": 0,\n  \"min\": -9223372036854775808,\n  \"max\": 18446744073709551615\n}\n";
    fs::write(source.join("config.json"), raw).unwrap();
    let mut declaration = definition();
    declaration["source"]["artifacts"]["config.json"] = record(raw);
    declaration["derived"]["artifacts"]["config.json"] = record(want);
    let model = TranslationModel::from_json(&declaration.to_string()).unwrap();
    assert_eq!(
        model
            .prepare(Some(&source), &destination(temp.path()))
            .unwrap()
            .artifact("config.json")
            .unwrap(),
        want
    );
}

#[test]
fn wrong_revision_is_rejected_even_for_an_otherwise_valid_existing_cache() {
    let model = TranslationModel::from_json(&definition().to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let wrong = temp.path().join("wrong-name");
    fs::create_dir(&wrong).unwrap();
    for name in FILES {
        fs::copy(
            fixtures().join("prepared").join("b".repeat(40)).join(name),
            wrong.join(name),
        )
        .unwrap();
    }
    assert!(model.prepare(None, &wrong).is_err());
    assert!(model.verify_prepared(&wrong).is_err());
}

#[test]
fn missing_extra_or_unknown_recipe_declarations_fail_before_use() {
    for owner in ["source", "derived"] {
        let mut missing = definition();
        missing[owner]["artifacts"]
            .as_object_mut()
            .unwrap()
            .remove("source.spm");
        assert!(TranslationModel::from_json(&missing.to_string()).is_err());
        let mut extra = definition();
        extra[owner]["artifacts"]["extra"] = record(b"extra");
        assert!(TranslationModel::from_json(&extra.to_string()).is_err());
    }
    let mut wrong = definition();
    wrong["recipe"] = json!("unmeasured");
    assert!(TranslationModel::from_json(&wrong.to_string()).is_err());
}

#[test]
fn failed_derivation_does_not_publish_a_partial_directory_or_leave_stages() {
    let temp = tempfile::tempdir().unwrap();
    let source = source_copy(temp.path());
    let mut wrong = definition();
    wrong["derived"]["artifacts"]["config.json"]["sha256"] = json!("c".repeat(64));
    let model = TranslationModel::from_json(&wrong.to_string()).unwrap();
    assert!(
        model
            .prepare(Some(&source), &destination(temp.path()))
            .is_err()
    );
    assert!(!destination(temp.path()).exists());
    assert_eq!(fs::read_dir(temp.path()).unwrap().count(), 1);
}

#[test]
fn unsupported_json_is_rejected_for_its_content_before_derived_hash_check() {
    let nested = format!("{}0{}", "[".repeat(129), "]".repeat(129));
    for (raw, needle) in [
        (b"{\"x\":1e-5}".as_slice(), "number"),
        (b"{\"x\":1,\"x\":1}", "duplicate"),
        (b"{\"x\":\"\\ud800\"}", "surrogate"),
        (b"{\"x\":18446744073709551616}", "out-of-range number"),
        (nested.as_bytes(), "recursion"),
    ] {
        let temp = tempfile::tempdir().unwrap();
        let source = source_copy(temp.path());
        fs::write(source.join("config.json"), raw).unwrap();
        let mut declaration = definition();
        declaration["source"]["artifacts"]["config.json"] = record(raw);
        let model = TranslationModel::from_json(&declaration.to_string()).unwrap();
        let error = model
            .prepare(Some(&source), &destination(temp.path()))
            .unwrap_err();
        assert!(matches!(error, ModelError::Json(_)), "{needle}: {error}");
        assert!(!destination(temp.path()).exists());
    }
}

#[cfg(unix)]
#[test]
fn published_files_and_revision_directory_keep_the_ordinary_umask() {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempfile::tempdir().unwrap();
    let source = source_copy(temp.path());
    let model = TranslationModel::from_json(&definition().to_string()).unwrap();
    let ordinary_dir = temp.path().join("ordinary-dir");
    let ordinary_file = temp.path().join("ordinary-file");
    fs::create_dir(&ordinary_dir).unwrap();
    fs::write(&ordinary_file, b"reference").unwrap();
    let target = destination(temp.path());
    model.prepare(Some(&source), &target).unwrap();
    let mode = |path: &Path| fs::metadata(path).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(&target), mode(&ordinary_dir));
    for name in FILES {
        assert_eq!(mode(&target.join(name)), mode(&ordinary_file));
    }
}

#[test]
fn concurrent_publishers_return_the_same_verified_cache() {
    let temp = tempfile::tempdir().unwrap();
    let source = source_copy(temp.path());
    let model = TranslationModel::from_json(&definition().to_string()).unwrap();
    let target = destination(temp.path());
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = (0..2)
        .map(|_| {
            let (source, model, target, barrier) = (
                source.clone(),
                model.clone(),
                target.clone(),
                barrier.clone(),
            );
            std::thread::spawn(move || {
                barrier.wait();
                model.prepare(Some(&source), &target).unwrap()
            })
        })
        .collect();
    for worker in workers {
        assert_eq!(
            worker.join().unwrap().artifact("model.bin").unwrap(),
            b"weights"
        );
    }
    assert_eq!(fs::read_dir(temp.path()).unwrap().count(), 2);
}

#[cfg(unix)]
#[test]
fn declared_empty_device_is_rejected_instead_of_published_as_model_data() {
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let source = source_copy(temp.path());
    fs::remove_file(source.join("model.bin")).unwrap();
    symlink("/dev/null", source.join("model.bin")).unwrap();
    let mut declaration = definition();
    for owner in ["source", "derived"] {
        declaration[owner]["artifacts"]["model.bin"] = record(b"");
    }
    let model = TranslationModel::from_json(&declaration.to_string()).unwrap();
    assert!(
        model
            .prepare(Some(&source), &destination(temp.path()))
            .is_err()
    );
    assert!(!destination(temp.path()).exists());
}

#[test]
fn registered_real_source_prepares_all_five_exact_derived_artifacts() {
    let source = PathBuf::from(
        std::env::var_os("KEN_TRANSLATION_SOURCE")
            .expect("prepare KEN_TRANSLATION_SOURCE for real translation preparation"),
    );
    assert!(source.is_absolute());
    let model = TranslationModel::from_json(include_str!(
        "../../../src/ken/embedder/data/es-en-ct2-int8.json"
    ))
    .unwrap();
    let temp = tempfile::tempdir().unwrap();
    let target = temp.path().join("c96e2c5399ebfae4fc43d9669556b9afa74bb69d");
    let prepared = model.prepare(Some(&source), &target).unwrap();
    let derived = model.prepared_assets().verify(&target).unwrap();
    for name in FILES {
        assert_eq!(
            prepared.artifact(name).unwrap(),
            derived.artifact(name).unwrap()
        );
    }
}
