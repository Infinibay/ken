use ken_models::RerankerModel;
use serde_json::{Value, json};
use std::path::PathBuf;

fn setup() -> (RerankerModel, PathBuf, Vec<u8>, Value) {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/ettin");
    let data: Value =
        serde_json::from_str(&std::fs::read_to_string(root.join("manifest.json")).unwrap())
            .unwrap();
    let definition = data["head"]["definition"].clone();
    (
        RerankerModel::from_json(&definition.to_string()).unwrap(),
        root.join(data["head"]["source"].as_str().unwrap()),
        std::fs::read(root.join("head/reference.onnx")).unwrap(),
        definition,
    )
}

#[test]
fn prepared_cache_is_owned_verified_and_reused_without_source() {
    let (model, source, want, _) = setup();
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join("arbitrary-cache-name");
    let prepared = model.prepare(Some(&source), &cache).unwrap();
    assert_eq!(prepared.graph().unwrap(), want);
    let tokenizer = std::fs::read(source.join("tokenizer.json")).unwrap();
    assert_eq!(prepared.artifact("tokenizer.json").unwrap(), tokenizer);
    assert!(prepared.artifact("not-registered").is_err());
    assert_eq!(model.prepare(None, &cache).unwrap().graph().unwrap(), want);
    std::fs::write(cache.join("model.onnx"), b"corrupt").unwrap();
    std::fs::write(cache.join("tokenizer.json"), b"corrupt").unwrap();
    assert_eq!(prepared.graph().unwrap(), want);
    assert_eq!(prepared.artifact("tokenizer.json").unwrap(), tokenizer);
    assert!(model.verify_prepared(&cache).is_err());
    assert!(model.prepare(None, &cache).is_err());
}

#[test]
fn failed_derivation_never_publishes_partial_cache() {
    let (_, source, _, mut definition) = setup();
    definition["graph"]["sha256"] = json!("0".repeat(64));
    let model = RerankerModel::from_json(&definition.to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join("not-published");
    assert!(model.prepare(Some(&source), &cache).is_err());
    assert!(!cache.exists());
}

#[test]
fn nested_source_duplicate_artifacts_do_not_bypass_shared_validation() {
    let (_, _, _, definition) = setup();
    let source = definition["source"].to_string();
    let entry = source
        .split("\"artifacts\":{")
        .nth(1)
        .unwrap()
        .split("},")
        .next()
        .unwrap()
        .to_string()
        + "}";
    let duplicate = source.replacen("\"artifacts\":{", &format!("\"artifacts\":{{{entry},"), 1);
    let input = format!(
        "{{\"source\":{duplicate},\"graph\":{}}}",
        definition["graph"]
    );
    let error = RerankerModel::from_json(&input).unwrap_err().to_string();
    assert!(error.contains("duplicate"), "{error}");
}

#[test]
fn concurrent_preparers_reverify_the_published_winner() {
    let (model, source, want, _) = setup();
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join("shared-cache");
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = (0..2)
        .map(|_| {
            let (model, source, cache, barrier) = (
                model.clone(),
                source.clone(),
                cache.clone(),
                barrier.clone(),
            );
            std::thread::spawn(move || {
                barrier.wait();
                model.prepare(Some(&source), &cache).unwrap()
            })
        })
        .collect();
    for worker in workers {
        assert_eq!(worker.join().unwrap().graph().unwrap(), want);
    }
    assert_eq!(
        model.verify_prepared(&cache).unwrap().graph().unwrap(),
        want
    );
    assert_eq!(
        std::fs::read_dir(temp.path()).unwrap().count(),
        1,
        "private preparation stages must be cleaned"
    );
}

#[cfg(unix)]
#[test]
fn published_files_and_directory_follow_the_ordinary_umask() {
    use std::os::unix::fs::PermissionsExt;
    let (model, source, _, _) = setup();
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join("readable");
    let reference_dir = temp.path().join("ordinary-dir");
    let reference_file = temp.path().join("ordinary-file");
    std::fs::create_dir(&reference_dir).unwrap();
    std::fs::write(&reference_file, b"reference").unwrap();
    model.prepare(Some(&source), &cache).unwrap();
    let mode =
        |path: &std::path::Path| std::fs::metadata(path).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(&cache), mode(&reference_dir));
    for name in [
        "model.onnx",
        "tokenizer.json",
        "config.json",
        "tokenizer_config.json",
    ] {
        assert_eq!(mode(&cache.join(name)), mode(&reference_file));
    }
}

#[test]
fn nested_graph_layout_is_verified_by_the_same_artifact_owner() {
    let (_, source, want, mut definition) = setup();
    definition["graph"]["path"] = json!("nested/model.onnx");
    let model = RerankerModel::from_json(&definition.to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join("nested-cache");
    let prepared = model.prepare(Some(&source), &cache).unwrap();
    assert_eq!(prepared.graph().unwrap(), want);
    assert!(cache.join("nested/model.onnx").is_file());
    assert_eq!(model.prepare(None, &cache).unwrap().graph().unwrap(), want);
}
