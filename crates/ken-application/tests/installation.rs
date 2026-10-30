use ken_application::installation::{
    DaemonLifecycle, Error, InstallOptions, ProjectInstallation, Result, UninstallOptions,
    uninstall,
};
use ken_hosts::{Bundles, HostSelection, NativeCommand};
use ken_index::DocumentEncoder;
use ken_maintenance::{ConfigEnvironment, UserConfig};
use ken_syntax::GrammarCatalog;
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};
fn grammars() -> Arc<GrammarCatalog> {
    Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("explicit prepared native grammars"),
        ))
        .unwrap(),
    )
}
fn native() -> NativeCommand {
    NativeCommand::new(
        "/native/ken-rs",
        vec!["--resources".into(), "/native/search.json".into()],
    )
    .unwrap()
}
fn bundles() -> Bundles {
    BTreeMap::from([(
        "ken-example".into(),
        BTreeMap::from([("SKILL.md".into(), b"# Native fixture\n".to_vec())]),
    )])
}
fn installer(root: &Path) -> ProjectInstallation {
    let config = UserConfig::new(&ConfigEnvironment {
        config_dir: Some(root.join(".fixture-config")),
        xdg_config_home: None,
        home: root.into(),
    });
    ProjectInstallation::new(
        root,
        grammars(),
        native(),
        bundles(),
        config,
        Some("fixture/native-model".into()),
    )
    .unwrap()
}
fn structural() -> InstallOptions {
    InstallOptions {
        hosts: ken_hosts::InstallOptions {
            no_wire: true,
            ..Default::default()
        },
        ..Default::default()
    }
}
fn meta(root: &Path) -> Value {
    serde_json::from_slice(&std::fs::read(root.join(".ken/meta.json")).unwrap()).unwrap()
}
fn source(root: &Path, path: &str, text: &str) {
    let path = root.join(path);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, text).unwrap();
}
#[test]
fn native_no_wire_provisions_secure_metadata_schema_model_pin_and_actual_grammar_index() {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().unwrap();
    source(
        root.path(),
        "src/core.py",
        "def normalize(value):\n return value.lower()\n",
    );
    std::fs::write(root.path().join(".gitignore"), "build/\n").unwrap();
    let report = installer(root.path())
        .install(&structural(), None, 12345)
        .unwrap();
    let metadata = meta(root.path());
    let id = metadata["project_id"].as_str().unwrap();
    assert_eq!(id.len(), 36);
    assert_eq!(&id[14..15], "4");
    assert!(["8", "9", "a", "b"].contains(&&id[19..20]));
    let token = metadata["auth_token"].as_str().unwrap();
    assert_eq!(token.len(), 43);
    assert!(
        token
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
    );
    assert_eq!(metadata["created_at_ms"], 12345);
    assert_eq!(
        metadata["project_path"],
        root.path().to_string_lossy().as_ref()
    );
    assert_eq!(
        std::fs::metadata(root.path().join(".ken/meta.json"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    assert_eq!(report.project_id, id);
    assert_eq!(report.files_indexed, 1);
    assert_eq!(report.symbols, 1);
    assert_eq!(report.model, "fixture/native-model");
    assert!(report.gitignore_changed);
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    assert_eq!(
        db.query_row("SELECT value FROM meta WHERE key='project_id'", [], |r| {
            r.get::<_, String>(0)
        })
        .unwrap(),
        id
    );
    assert_eq!(
        db.query_row("SELECT value FROM meta WHERE key='embed_model'", [], |r| {
            r.get::<_, String>(0)
        })
        .unwrap(),
        "fixture/native-model"
    );
    assert_eq!(
        db.query_row(
            "SELECT name FROM ci_symbols WHERE qualname='normalize'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        "normalize"
    );
    assert!(!root.path().join(".claude").exists());
    assert!(!root.path().join(".mcp.json").exists());
    assert!(
        std::fs::read_to_string(root.path().join(".gitignore"))
            .unwrap()
            .ends_with("# ken — local index, daemon socket, logs\n.ken/\n")
    );
}
#[test]
fn repeated_install_preserves_exact_metadata_identity_auth_extra_fields_and_pinned_model() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), "a.py", "def same():\n return 1\n");
    let app = installer(root.path());
    let first = app.install(&structural(), None, 10).unwrap();
    let mut metadata = meta(root.path());
    metadata["extension"] = json!({"keep":true});
    let bytes = serde_json::to_vec_pretty(&metadata).unwrap();
    std::fs::write(root.path().join(".ken/meta.json"), &bytes).unwrap();
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    db.execute(
        "UPDATE meta SET value='existing/project-model' WHERE key='embed_model'",
        [],
    )
    .unwrap();
    drop(db);
    let second = app.install(&structural(), None, 999).unwrap();
    assert_eq!(
        std::fs::read(root.path().join(".ken/meta.json")).unwrap(),
        bytes
    );
    assert_eq!(first.project_id, second.project_id);
    assert!(!second.metadata_created);
    assert_eq!(
        second.model, "fixture/native-model",
        "explicit environment override affects selected encoder while the existing pin is retained"
    );
    assert_eq!(second.index.unchanged, 1);
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    assert_eq!(
        db.query_row("SELECT value FROM meta WHERE key='embed_model'", [], |r| {
            r.get::<_, String>(0)
        })
        .unwrap(),
        "existing/project-model"
    );
}
#[derive(Default)]
struct Encoder {
    passages: RefCell<Vec<String>>,
}
impl DocumentEncoder for Encoder {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        Ok(2)
    }
    fn token_count(&self, text: &str) -> ken_retrieval::Result<usize> {
        Ok(text.split_whitespace().count())
    }
    fn embed_passages(&self, texts: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.passages
            .borrow_mut()
            .extend(texts.iter().map(|s| s.to_string()));
        Ok(texts.iter().map(|_| vec![1., 0.]).collect())
    }
}
#[test]
fn eager_embedding_limit_prioritizes_core_code_and_indexes_all_remaining_sources_structurally() {
    let root = tempfile::tempdir().unwrap();
    source(
        root.path(),
        "src/core.py",
        "def core_unique():\n \"\"\"Core production.\"\"\"\n return 1\n",
    );
    source(
        root.path(),
        "tests/test_core.py",
        "def test_unique():\n return 2\n",
    );
    source(root.path(), "README.md", "Fixture docs.\n");
    let encoder = Encoder::default();
    let report = installer(root.path())
        .install(
            &InstallOptions {
                embed: true,
                embed_limit: Some(1),
                ..structural()
            },
            Some(&encoder),
            10,
        )
        .unwrap();
    assert_eq!(report.embedding_files, 1);
    assert_eq!(report.files_indexed, 2);
    assert!(
        encoder
            .passages
            .borrow()
            .iter()
            .any(|s| s.contains("core_unique"))
    );
    assert!(
        !encoder
            .passages
            .borrow()
            .iter()
            .any(|s| s.contains("test_unique"))
    );
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    let mut stmt=db.prepare("SELECT path FROM ci_files WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL ORDER BY path").unwrap();
    let paths = stmt
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert_eq!(paths, vec!["src/core.py"]);
    assert_eq!(
        db.query_row(
            "SELECT count(*) FROM ci_symbols WHERE qualname='test_unique'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        1
    );
}
#[test]
fn zero_embedding_budget_and_structural_install_never_construct_a_model_provider() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), "core.py", "def core():\n return 1\n");
    let app = installer(root.path());
    let mut provider = |_: &rusqlite::Connection, _: &str| -> Result<Rc<dyn DocumentEncoder>> {
        panic!("no eager files must not load model resources")
    };
    let report = app
        .install_with_provider(
            &InstallOptions {
                embed: true,
                embed_limit: Some(0),
                ..structural()
            },
            10,
            &mut provider,
        )
        .unwrap();
    assert_eq!(report.embedding_files, 0);
    assert_eq!(report.files_indexed, 1);
    app.install_with_provider(&structural(), 11, &mut provider)
        .unwrap();
}
#[test]
fn invalid_embed_options_are_rejected_before_provisioning_or_model_provider() {
    for options in [
        InstallOptions {
            embed: true,
            embed_limit: Some(-1),
            ..structural()
        },
        InstallOptions {
            embed: false,
            embed_limit: Some(1),
            ..structural()
        },
    ] {
        let root = tempfile::tempdir().unwrap();
        let mut provider = |_: &rusqlite::Connection, _: &str| -> Result<Rc<dyn DocumentEncoder>> {
            panic!("invalid options must not load model resources")
        };
        assert!(
            installer(root.path())
                .install_with_provider(&options, 10, &mut provider)
                .is_err()
        );
        assert!(!root.path().join(".ken").exists());
    }
}
struct Stop<'a> {
    calls: &'a Cell<usize>,
    fail: bool,
}
impl DaemonLifecycle for Stop<'_> {
    fn stop_existing(&self, root: &Path) -> Result<()> {
        self.calls.set(self.calls.get() + 1);
        assert!(root.join(".ken/meta.json").exists());
        if self.fail {
            Err(Error::Invalid("existing daemon did not stop".into()))
        } else {
            Ok(())
        }
    }
}
#[test]
fn uninstall_unwires_owned_resources_preserves_edited_config_and_obeys_keep_db() {
    let root = tempfile::tempdir().unwrap();
    let app = installer(root.path());
    let options = InstallOptions {
        hosts: ken_hosts::InstallOptions {
            hosts: HostSelection {
                codex: true,
                ..Default::default()
            },
            instructions: Some(true),
            ..Default::default()
        },
        ..Default::default()
    };
    app.install(&options, None, 10).unwrap();
    let path = root.path().join(".codex/config.toml");
    let edited = std::fs::read_to_string(&path).unwrap() + "# User extension\n";
    std::fs::write(&path, &edited).unwrap();
    let calls = Cell::new(0);
    let report = app
        .uninstall(
            &UninstallOptions { keep_db: true },
            &Stop {
                calls: &calls,
                fail: false,
            },
        )
        .unwrap();
    assert!(!report.removed_project_data);
    assert!(root.path().join(".ken/meta.json").exists());
    assert_eq!(std::fs::read_to_string(&path).unwrap(), edited);
    assert!(
        !root
            .path()
            .join(".agents/skills/ken-example/SKILL.md")
            .exists()
    );
    assert!(!root.path().join("AGENTS.md").exists());
    assert!(report.hosts.preserved.contains_key(".codex/config.toml"));
    let report = uninstall(
        root.path(),
        native(),
        &UninstallOptions { keep_db: false },
        &Stop {
            calls: &calls,
            fail: false,
        },
    )
    .unwrap();
    assert!(report.removed_project_data);
    assert!(!root.path().join(".ken").exists());
    assert_eq!(std::fs::read_to_string(path).unwrap(), edited);
    assert_eq!(calls.get(), 2);
}
#[test]
fn failed_existing_daemon_shutdown_aborts_before_unwiring_or_deleting_project_data() {
    let root = tempfile::tempdir().unwrap();
    let app = installer(root.path());
    app.install(&InstallOptions::default(), None, 10).unwrap();
    let config = std::fs::read(root.path().join(".mcp.json")).unwrap();
    let calls = Cell::new(0);
    assert!(
        app.uninstall(
            &UninstallOptions { keep_db: false },
            &Stop {
                calls: &calls,
                fail: true
            }
        )
        .is_err()
    );
    assert_eq!(calls.get(), 1);
    assert_eq!(
        std::fs::read(root.path().join(".mcp.json")).unwrap(),
        config
    );
    assert!(root.path().join(".ken/ken.db").is_file());
}
#[cfg(unix)]
#[test]
fn symlinked_project_metadata_database_and_sidecars_cannot_mutate_external_files() {
    for target in [
        ".ken",
        ".ken/meta.json",
        ".ken/ken.db",
        ".ken/ken.db-wal",
        ".ken/ken.db-shm",
    ] {
        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let app = installer(root.path());
        if target == ".ken" {
            std::os::unix::fs::symlink(outside.path(), root.path().join(target)).unwrap();
        } else {
            std::fs::create_dir(root.path().join(".ken")).unwrap();
            std::fs::write(
                root.path().join(".ken/meta.json"),
                json!({"project_id":"existing","auth_token":"preserve","project_path":root.path()})
                    .to_string(),
            )
            .unwrap();
            if target == ".ken/meta.json" {
                std::fs::remove_file(root.path().join(target)).unwrap();
            }
            let file = outside.path().join("keep");
            std::fs::write(&file, "unchanged external").unwrap();
            std::os::unix::fs::symlink(file, root.path().join(target)).unwrap();
        }
        assert!(app.install(&structural(), None, 10).is_err(), "{target}");
        if target == ".ken" {
            assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
        } else {
            assert_eq!(
                std::fs::read_to_string(outside.path().join("keep")).unwrap(),
                "unchanged external"
            );
        }
    }
}
#[cfg(unix)]
#[test]
fn uninstall_refuses_project_directory_replaced_between_shutdown_and_removal() {
    struct Replace {
        outside: PathBuf,
    }
    impl DaemonLifecycle for Replace {
        fn stop_existing(&self, root: &Path) -> Result<()> {
            std::fs::rename(root.join(".ken"), root.join(".ken-original"))?;
            std::os::unix::fs::symlink(&self.outside, root.join(".ken"))?;
            Ok(())
        }
    }
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let app = installer(root.path());
    app.install(&structural(), None, 10).unwrap();
    std::fs::write(outside.path().join("keep"), "external").unwrap();
    assert!(
        app.uninstall(
            &UninstallOptions { keep_db: false },
            &Replace {
                outside: outside.path().into()
            }
        )
        .is_err()
    );
    assert_eq!(
        std::fs::read_to_string(outside.path().join("keep")).unwrap(),
        "external"
    );
    assert!(root.path().join(".ken-original/ken.db").exists());
}
#[test]
fn gitignore_is_idempotent_and_missing_gitignore_is_not_created() {
    let root = tempfile::tempdir().unwrap();
    let app = installer(root.path());
    app.install(&structural(), None, 10).unwrap();
    assert!(!root.path().join(".gitignore").exists());
    std::fs::write(root.path().join(".gitignore"), "# keep CRLF\r\n.ken\r\n").unwrap();
    let before = std::fs::read(root.path().join(".gitignore")).unwrap();
    assert!(
        !app.install(&structural(), None, 11)
            .unwrap()
            .gitignore_changed
    );
    assert_eq!(
        std::fs::read(root.path().join(".gitignore")).unwrap(),
        before
    );
}
