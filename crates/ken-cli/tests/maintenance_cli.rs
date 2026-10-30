use clap::Parser;
use ken_cli::maintenance::{BenchEngine, MaintenanceCommand, RetrievalCommand, VectorOperation};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    process::{Command, Output},
};
#[derive(Parser)]
struct ParserFixture {
    #[command(subcommand)]
    command: MaintenanceCommand,
}
fn args(values: &[&str]) -> MaintenanceCommand {
    ParserFixture::try_parse_from(std::iter::once("ken-rs").chain(values.iter().copied()))
        .unwrap()
        .command
}
fn run(root: &Path, resources: &Path, values: &[&str]) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_ken-rs"));
    command
        .arg("--resources")
        .arg(resources)
        .args(values)
        .current_dir(root)
        .env_clear()
        .env("HOME", root)
        .env("KEN_CONFIG_DIR", root.join("config"))
        .env("PATH", "")
        .env("KEN_EMBED_DEVICE", "cpu")
        .env("KEN_EMBED_MAX_SEQ", "ignored-for-static");
    if let Some(runtime) = std::env::var_os("KEN_DENSE_BLAS_DIR") {
        command.env("KEN_DENSE_BLAS_DIR", runtime);
    }
    command.output().unwrap()
}
fn json_output(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn resources(root: &Path, grammar: bool) -> PathBuf {
    let profile: Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/linux.json"
    ))
    .unwrap();
    let directory = root.join(".ken/native-resources");
    std::fs::create_dir_all(&directory).unwrap();
    let path = directory.join("installation.json");
    let npz = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../src/ken/embedder/data/ken__static-qwen3-r512-v2.npz")
        .canonicalize()
        .unwrap();
    std::fs::write(&path,json!({"format":"ken-search-installation/1","grammar_manifest":if grammar{PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap())}else{root.join("deliberately-missing-grammar.json")},"ranking_directory":"deliberately-missing-ranks","private_parent":"models-private","cache_parent":"models-cache","bundled_npz":npz,"sources":{},"acquisition":"offline","legacy_runtime":profile["legacy_runtime"],"onnx_library":null,"translation":null}).to_string()).unwrap();
    path
}
fn seed(root: &Path) -> ken_core::project::ProjectPaths {
    use ken_core::project::{DiscoveryContext, ProjectPaths};
    let paths = ProjectPaths::at(
        root,
        &DiscoveryContext {
            cwd: root.into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let mut store = ken_store::ProjectStore::open(&paths).unwrap();
    store.initialize().unwrap();
    store
        .database()
        .set_meta("embed_model", "ken/static-qwen3-r512-v2")
        .unwrap();
    store.database().connection().execute("INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at,embedding)VALUES('a.py','python',x'',0,0,?1)",[vec![0u8;8]]).unwrap();
    paths
}
#[test]
fn command_trees_parse_original_defaults_and_compatible_flags() {
    assert!(matches!(
        args(&["models", "--json"]),
        MaintenanceCommand::Models { json: true }
    ));
    assert!(matches!(
        args(&["default-model", "custom/model"]),
        MaintenanceCommand::DefaultModel {
            model: Some(_),
            clear: false
        }
    ));
    assert!(matches!(
        args(&["vectors"]),
        MaintenanceCommand::Vectors {
            action: VectorOperation::Status,
            ..
        }
    ));
    assert!(matches!(
        args(&["reembed", "--model", "x", "--check", "--json"]),
        MaintenanceCommand::Reembed {
            model: Some(_),
            check: true,
            json: true,
            ..
        }
    ));
    assert!(matches!(
        args(&["retrieval", "index", "--profile", "p.json"]),
        MaintenanceCommand::Retrieval {
            command: RetrievalCommand::Index {
                profile: Some(_),
                ..
            }
        }
    ));
    assert!(matches!(
        args(&[
            "bench",
            "cases.jsonl",
            "--engine",
            "retrieval",
            "--responses",
            "r.jsonl",
            "--roots",
            "roots.json",
            "--gate",
            "gate.json"
        ]),
        MaintenanceCommand::Bench {
            engine: BenchEngine::Retrieval,
            responses: Some(_),
            roots: Some(_),
            gate: Some(_),
            ..
        }
    ));
    assert!(
        ParserFixture::try_parse_from(["ken-rs", "bench", "cases.jsonl", "--top", "0"]).is_err()
    );
}
#[test]
fn models_and_default_model_are_native_cold_and_preserve_unrelated_configuration() {
    let root = tempfile::tempdir().unwrap();
    let missing = root.path().join("missing.json");
    let rows = json_output(run(root.path(), &missing, &["models", "--json"]));
    assert_eq!(rows["default"], ken_models::model_policy::POTION_MODEL);
    assert!(
        rows["models"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["model"] == "ken/static-qwen3-r512-v2")
    );
    assert!(!root.path().join(".ken").exists());
    std::fs::create_dir(root.path().join("config")).unwrap();
    std::fs::write(
        root.path().join("config/config.json"),
        r#"{"unrelated":true}"#,
    )
    .unwrap();
    let saved = run(root.path(), &missing, &["default-model", "custom/model"]);
    assert!(saved.status.success());
    assert!(String::from_utf8_lossy(&saved.stdout).contains("existing projects are unaffected"));
    let shown = run(root.path(), &missing, &["default-model"]);
    assert!(String::from_utf8_lossy(&shown.stdout).contains("custom/model"));
    let cleared = run(root.path(), &missing, &["default-model", "--clear"]);
    assert!(cleared.status.success());
    let value: Value =
        serde_json::from_slice(&std::fs::read(root.path().join("config/config.json")).unwrap())
            .unwrap();
    assert_eq!(value, json!({"unrelated":true}));
}
#[test]
fn reembed_probe_and_vector_commands_reach_actual_owners_without_search_resources() {
    let root = tempfile::tempdir().unwrap();
    let paths = seed(root.path());
    let manifest = resources(root.path(), false);
    let before = run(root.path(), &manifest, &["reembed", "--check", "--json"]);
    assert_eq!(before.status.code(), Some(1));
    let report: Value = serde_json::from_slice(&before.stdout).unwrap();
    assert_eq!(report["ok"], false);
    assert!(report["reason"].as_str().unwrap().contains("no probe"));
    let report = json_output(run(root.path(), &manifest, &["reembed", "--json"]));
    assert_eq!(report["ok"], true);
    assert_eq!(report["model"], "ken/static-qwen3-r512-v2");
    assert_eq!(report["files"], 1);
    assert_eq!(report["dim"], 1024);
    let checked = json_output(run(
        root.path(),
        &manifest,
        &["reembed", "--check", "--json"],
    ));
    assert_eq!(checked["ok"], true);
    let status = json_output(run(root.path(), &manifest, &["vectors", "--json"]));
    assert_eq!(status["dim"], 1024);
    let verified = json_output(run(
        root.path(),
        &manifest,
        &["vectors", "verify", "--json"],
    ));
    assert_eq!(verified["spaces"]["ci_files"]["referenced"], 1);
    let migrated = json_output(run(
        root.path(),
        &manifest,
        &["vectors", "migrate", "--json"],
    ));
    assert_eq!(migrated["moved"]["ci_files"], 0);
    let compacted = json_output(run(
        root.path(),
        &manifest,
        &["vectors", "compact", "--json"],
    ));
    assert_eq!(compacted["compacted"]["ci_files"]["after"], 1);
    let project = ken_store::ProjectStore::open(&paths).unwrap();
    assert_eq!(
        project
            .database()
            .get_meta("embed_model")
            .unwrap()
            .as_deref(),
        Some("ken/static-qwen3-r512-v2")
    );
    assert!(
        !manifest
            .parent()
            .unwrap()
            .join("deliberately-missing-ranks")
            .exists()
    );
}
#[test]
fn invalid_model_does_not_publish_a_new_project_pin_or_interruption_marker() {
    let root = tempfile::tempdir().unwrap();
    let paths = seed(root.path());
    let manifest = resources(root.path(), false);
    let output = run(
        root.path(),
        &manifest,
        &["reembed", "--model", "unknown/foreign-model", "--json"],
    );
    assert_eq!(output.status.code(), Some(1));
    let store = ken_store::ProjectStore::open(&paths).unwrap();
    assert_eq!(
        store.database().get_meta("embed_model").unwrap().as_deref(),
        Some("ken/static-qwen3-r512-v2")
    );
    assert!(
        store
            .database()
            .get_meta("reembed_in_progress")
            .unwrap()
            .is_none()
    );
}
#[test]
fn empty_retrieval_prepare_is_complete_cold_and_preserves_existing_project_metadata() {
    let root = tempfile::tempdir().unwrap();
    let manifest = resources(root.path(), true);
    let report = json_output(run(
        root.path(),
        &manifest,
        &["retrieval", "prepare", "--json"],
    ));
    assert_eq!(report["indexed_files"], 0);
    assert_eq!(report["owners"], 0);
    std::fs::write(root.path().join(".ken/meta.json"), "{\"keep\":42}\n").unwrap();
    let report = json_output(run(
        root.path(),
        &manifest,
        &["retrieval", "prepare", "--json"],
    ));
    assert_eq!(report["owners"], 0);
    assert_eq!(
        std::fs::read_to_string(root.path().join(".ken/meta.json")).unwrap(),
        "{\"keep\":42}\n"
    );
    assert!(
        !manifest
            .parent()
            .unwrap()
            .join("deliberately-missing-ranks")
            .exists()
    );
}
#[test]
fn retrieval_index_uses_registered_static_profile_and_reuses_it_on_second_call() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(
        root.path().join("code.py"),
        "def normalize(value):\n    return value.lower()\n",
    )
    .unwrap();
    let manifest = resources(root.path(), true);
    let report = json_output(run(
        root.path(),
        &manifest,
        &["retrieval", "index", "--json"],
    ));
    assert!(report["passages"].as_u64().unwrap() > 0);
    let again = json_output(run(
        root.path(),
        &manifest,
        &["retrieval", "index", "--json"],
    ));
    assert_eq!(again["profile_version"], report["profile_version"]);
    assert_eq!(again["profile"]["representation_version"], 3);
}
#[test]
fn context_benchmark_rejects_copied_stale_index_before_loading_missing_models() {
    let root = tempfile::tempdir().unwrap();
    seed(root.path());
    std::fs::write(root.path().join("a.py"), "changed content\n").unwrap();
    let dataset = root.path().join("cases.jsonl");
    std::fs::write(
        &dataset,
        "{\"prompt\":\"where is a.py\",\"expected_files\":[\"a.py\"]}\n",
    )
    .unwrap();
    let output = run(
        root.path(),
        &root.path().join("missing.json"),
        &["bench", dataset.to_str().unwrap(), "--json"],
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("indexed files do not belong"));
}
#[test]
fn missing_index_and_retrieval_bench_required_inputs_are_actionable_errors() {
    let root = tempfile::tempdir().unwrap();
    let missing = root.path().join("missing.json");
    for command in [vec!["vectors", "--json"], vec!["reembed", "--json"]] {
        let output = run(root.path(), &missing, &command);
        assert_eq!(output.status.code(), Some(1));
        assert!(String::from_utf8_lossy(&output.stderr).contains("no ken index"));
    }
    let output = run(
        root.path(),
        &missing,
        &["bench", "cases.jsonl", "--engine", "retrieval"],
    );
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("--responses and --roots"));
}
#[test]
fn context_benchmark_runs_native_rank_and_reports_real_render_exposure() {
    use ken_core::project::{DiscoveryContext, ProjectPaths};
    use ken_index::{IndexOptions, Indexer};
    let root = tempfile::tempdir().unwrap();
    std::fs::write(
        root.path().join("a.py"),
        "def normalize(value):\n    return value.lower()\n",
    )
    .unwrap();
    let paths = ProjectPaths::at(
        root.path(),
        &DiscoveryContext {
            cwd: root.path().into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let mut store = ken_store::ProjectStore::open(&paths).unwrap();
    store.initialize().unwrap();
    store
        .database()
        .set_meta("embed_model", "ken/static-qwen3-r512-v2")
        .unwrap();
    let parsers = ken_syntax::ParserRegistry::new(
        ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    Indexer::new(&parsers)
        .index_files(
            store.database_mut(),
            &paths,
            &["a.py".into()],
            &IndexOptions {
                retrieval_policy: Some(ken_retrieval::PassagePolicy::default()),
                ..Default::default()
            },
            &mut |_: &str, _: &str| {},
        )
        .unwrap();
    drop(store);
    let dataset = root.path().join("cases.jsonl");
    std::fs::write(
        &dataset,
        "{\"prompt\":\"a.py\",\"expected_files\":[\"a.py\"]}\n",
    )
    .unwrap();
    let manifest = resources(root.path(), false);
    let report = json_output(run(
        root.path(),
        &manifest,
        &[
            "bench",
            dataset.to_str().unwrap(),
            "--top",
            "1",
            "--max-chars",
            "500",
            "--fail-under-case-recall",
            "1",
            "--json",
        ],
    ));
    assert_eq!(report["ok"], true);
    assert_eq!(report["cases"], 1);
    assert_eq!(report["case_recall"], 1.);
    assert_eq!(report["results"][0]["ranked_files"][0], "a.py");
    assert!(report["avg_timings_ms"]["embed"].as_f64().unwrap() > 0.);
}
#[test]
fn models_lists_authenticated_extension_selectors_and_refuses_present_invalid_declarations() {
    use sha2::{Digest, Sha256};
    let root = tempfile::tempdir().unwrap();
    let manifest = resources(root.path(), false);
    let mut recipe = serde_json::from_str::<Value>(include_str!(
        "../../ken-models/resources/fastembed-catalog.json"
    ))
    .unwrap()["models"][0]
        .clone();
    recipe["name"] = json!("fixture/cli-extension");
    let raw=json!({"format":"ken-model-catalog-extensions/1","models":[{"backend":"fastembed","recipe":recipe,"prompts":{"query":"","passage":""}}]}).to_string();
    let digest = format!("{:x}", Sha256::digest(raw.as_bytes()));
    let source = manifest.parent().unwrap().join("catalogue.json");
    std::fs::write(&source, &raw).unwrap();
    let mut metadata: Value = serde_json::from_slice(&std::fs::read(&manifest).unwrap()).unwrap();
    metadata["catalogue_extensions"] =
        json!({"path":"catalogue.json","bytes":raw.len(),"sha256":digest});
    std::fs::write(&manifest, metadata.to_string()).unwrap();
    let report = json_output(run(root.path(), &manifest, &["models", "--json"]));
    let selector = format!("ken-catalogue:{digest}:fixture/cli-extension");
    let row = report["models"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["model"] == selector)
        .unwrap();
    assert_eq!(row["native_inference_accepted"], false);
    assert!(!manifest.parent().unwrap().join("models-private").exists());
    assert!(!manifest.parent().unwrap().join("models-cache").exists());
    std::fs::write(source, "changed").unwrap();
    let failed = run(root.path(), &manifest, &["models", "--json"]);
    assert_eq!(failed.status.code(), Some(1));
    assert!(failed.stdout.is_empty());
    assert!(String::from_utf8_lossy(&failed.stderr).contains("catalogue"));
}
