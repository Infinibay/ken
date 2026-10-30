use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_maintenance::{
    ConfigEnvironment, DatabaseReclaimer, MaintenanceApplication, ModelSelection, UserConfig,
    VectorAction,
};
use ken_store::{ProjectDatabase, ProjectStore, VectorSpace};
use serde_json::{Value, json};
fn fixture() -> (tempfile::TempDir, ProjectPaths) {
    let root = tempfile::tempdir().unwrap();
    let p = ProjectPaths::at(
        root.path(),
        &DiscoveryContext {
            cwd: root.path().into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let mut store = ProjectStore::open(&p).unwrap();
    store.initialize().unwrap();
    (root, p)
}
#[test]
fn config_precedence_preserves_other_keys_and_does_not_repin_existing_projects() {
    let (root, p) = fixture();
    let env = ConfigEnvironment {
        config_dir: Some(root.path().join("custom")),
        xdg_config_home: Some(root.path().join("xdg")),
        home: root.path().into(),
    };
    let config = UserConfig::new(&env);
    assert_eq!(config.path(), root.path().join("custom/config.json"));
    std::fs::create_dir_all(config.path().parent().unwrap()).unwrap();
    std::fs::write(
        config.path(),
        r#"{"unrelated":{"keep":true},"default_model":"old-user"}"#,
    )
    .unwrap();
    config.set_default_model(Some("new-user")).unwrap();
    let data: Value = serde_json::from_slice(&std::fs::read(config.path()).unwrap()).unwrap();
    assert_eq!(data["unrelated"], json!({"keep":true}));
    let store = ProjectStore::open(&p).unwrap();
    store
        .database()
        .set_meta("embed_model", "project-pin")
        .unwrap();
    let before = std::fs::read(p.db()).unwrap();
    let selection =
        ModelSelection::resolve(store.database().connection(), &config, None, None).unwrap();
    assert_eq!(selection.model, "project-pin");
    assert_eq!(
        ModelSelection::resolve(store.database().connection(), &config, Some("env"), None)
            .unwrap()
            .model,
        "env"
    );
    assert_eq!(
        ModelSelection::resolve(
            store.database().connection(),
            &config,
            Some("env"),
            Some("explicit")
        )
        .unwrap()
        .model,
        "explicit"
    );
    assert_eq!(before, std::fs::read(p.db()).unwrap());
    config.set_default_model(None).unwrap();
    assert_eq!(
        config.recommended_model().unwrap(),
        ken_models::model_policy::POTION_MODEL
    );
    let xdg = UserConfig::new(&ConfigEnvironment {
        config_dir: None,
        ..env.clone()
    });
    assert_eq!(xdg.path(), root.path().join("xdg/ken/config.json"));
    let home = UserConfig::new(&ConfigEnvironment {
        config_dir: None,
        xdg_config_home: None,
        ..env
    });
    assert_eq!(home.path(), root.path().join(".config/ken/config.json"));
}
#[test]
fn bad_config_is_tolerated_and_foreign_catalogue_models_are_not_claimed_executable() {
    let root = tempfile::tempdir().unwrap();
    let config = UserConfig::new(&ConfigEnvironment {
        config_dir: Some(root.path().into()),
        xdg_config_home: None,
        home: root.path().into(),
    });
    for raw in [
        "bad-json",
        "[]",
        r#"{"default_model":42}"#,
        r#"{"default_model":"  "}"#,
    ] {
        std::fs::write(config.path(), raw).unwrap();
        assert_eq!(config.default_model().unwrap(), None);
    }
    let report =
        ken_maintenance::models(&config, &ken_models::ModelCatalog::built_in().unwrap()).unwrap();
    assert_eq!(report["default"], ken_models::model_policy::POTION_MODEL);
    let rows = report["models"].as_array().unwrap();
    assert!(
        rows.iter()
            .any(|r| r["model"] == ken_models::model_policy::POTION_MODEL)
    );
    assert!(rows.iter().all(|r| r["registration"].is_object()));
    assert!(
        rows.iter()
            .filter(|r| r["model"] == "Qwen/Qwen3-Embedding-0.6B")
            .all(|r| r["native_inference_accepted"] == false)
    );
}
struct FailingVacuum;
impl DatabaseReclaimer for FailingVacuum {
    fn reclaim(&mut self, _: &mut ProjectDatabase) -> ken_maintenance::Result<(u64, u64)> {
        Err(ken_maintenance::Error::Invalid(
            "injected vacuum unavailable".into(),
        ))
    }
}
#[test]
fn vector_migration_restart_verify_compact_and_advisory_vacuum_use_existing_storage_owner() {
    let (root, p) = fixture();
    let store = ProjectStore::open(&p).unwrap();
    let blob = |v: &[f32]| v.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>();
    for (id, data) in [(1, blob(&[3., 4.])), (2, blob(&[1., 2., 3.]))] {
        store.database().connection().execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,embedding)VALUES(?1,?2,x'',0,0,?3)",rusqlite::params![id,format!("file{id}.py"),data]).unwrap();
    }
    drop(store);
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let result = app
        .vectors_with_reclaimer(
            VectorAction::Migrate,
            2,
            Some("model"),
            &mut FailingVacuum,
            &mut |_| {},
        )
        .unwrap();
    assert_eq!(result["moved"]["ci_files"], 1);
    assert!(
        result["vacuum_error"]
            .as_str()
            .unwrap()
            .contains("injected")
    );
    let again = app
        .vectors(VectorAction::Migrate, 2, Some("model"), &mut |_| {})
        .unwrap();
    assert_eq!(again["moved"]["ci_files"], 0);
    let verify = app
        .vectors(VectorAction::Verify, 2, Some("model"), &mut |_| {})
        .unwrap();
    assert_eq!(verify["spaces"]["ci_files"]["referenced"], 1);
    assert_eq!(verify["spaces"]["ci_files"]["inline_pending"], 1);
    drop(app);
    let store = ProjectStore::open(&p).unwrap();
    assert_eq!(
        store
            .vectors(VectorSpace::Files, 2, Some("model"))
            .unwrap()
            .read(&[0])
            .unwrap()[0],
        vec![0.6, 0.8]
    );
    store
        .database()
        .connection()
        .execute("DELETE FROM ci_files WHERE id=1", [])
        .unwrap();
    drop(store);
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let compact = app
        .vectors(VectorAction::Compact, 2, Some("model"), &mut |_| {})
        .unwrap();
    assert_eq!(compact["compacted"]["ci_files"]["after"], 0);
}
#[test]
fn vector_inspection_reports_each_incompatible_space_without_erasing_it() {
    let (root, p) = fixture();
    let store = ProjectStore::open(&p).unwrap();
    store
        .vectors(VectorSpace::Files, 3, Some("old"))
        .unwrap()
        .write(&[0], &[vec![1., 0., 0.]], true)
        .unwrap();
    let before = std::fs::read(p.vectors().join("ci_files.json")).unwrap();
    drop(store);
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let report = app
        .vectors(VectorAction::Status, 2, Some("current"), &mut |_| {})
        .unwrap();
    assert!(report["spaces"]["ci_files"]["error"].is_string());
    assert_eq!(
        before,
        std::fs::read(p.vectors().join("ci_files.json")).unwrap()
    );
    assert!(MaintenanceApplication::open(&root.path().join("missing")).is_err());
}
