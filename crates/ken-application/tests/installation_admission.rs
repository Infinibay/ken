//! Important review regressions; installation delegates segment admission to storage.
#![cfg(unix)]
use ken_application::installation::{InstallOptions, ProjectInstallation};
use ken_hosts::{Bundles, NativeCommand};
use ken_index::DocumentEncoder;
use ken_maintenance::{ConfigEnvironment, UserConfig};
use ken_syntax::GrammarCatalog;
use serde_json::json;
use std::{
    ffi::OsString,
    os::unix::ffi::OsStringExt,
    path::{Path, PathBuf},
    sync::Arc,
};
fn installer(root: &Path) -> ken_application::installation::Result<ProjectInstallation> {
    let catalog = Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    let config = UserConfig::new(&ConfigEnvironment {
        config_dir: Some(root.join(".fixture-config")),
        xdg_config_home: None,
        home: root.into(),
    });
    ProjectInstallation::new(
        root,
        catalog,
        NativeCommand::new("/native/ken-rs", vec![]).unwrap(),
        Bundles::new(),
        config,
        Some("fixture/native-model".into()),
    )
}
struct Encoder;
impl DocumentEncoder for Encoder {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        Ok(2)
    }
    fn token_count(&self, text: &str) -> ken_retrieval::Result<usize> {
        Ok(text.split_whitespace().count())
    }
    fn embed_passages(&self, texts: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        Ok(texts.iter().map(|_| vec![1., 0.]).collect())
    }
}
#[test]
fn eager_install_cannot_write_a_symlinked_existing_automatic_vector_segment() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let external = outside.path().join("keep");
    let original = b"01234567";
    std::fs::write(&external, original).unwrap();
    std::fs::write(d.path().join("source.py"), "def example():\n return 1\n").unwrap();
    std::fs::create_dir_all(d.path().join(".ken/vectors")).unwrap();
    std::fs::write(d.path().join(".ken/vectors/ci_files.json"),json!({"format":1,"space":"ci_files","dim":2,"dtype":"float32","segment_rows":1,"model":"fixture/native-model"}).to_string()).unwrap();
    std::os::unix::fs::symlink(&external, d.path().join(".ken/vectors/ci_files.0000.vec")).unwrap();
    let options = InstallOptions {
        embed: true,
        hosts: ken_hosts::InstallOptions {
            no_wire: true,
            ..Default::default()
        },
        ..Default::default()
    };
    let _ = installer(d.path())
        .unwrap()
        .install(&options, Some(&Encoder), 10);
    assert_eq!(
        std::fs::read(external).unwrap(),
        original,
        "embedding must not follow the existing vector segment symlink"
    );
}
#[test]
fn non_utf8_project_root_returns_a_controlled_error_before_any_provisioning() {
    let d = tempfile::tempdir().unwrap();
    let root = d.path().join(OsString::from_vec(b"native-\xff".to_vec()));
    std::fs::create_dir(&root).unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        installer(&root).and_then(|app| {
            app.install(
                &InstallOptions {
                    hosts: ken_hosts::InstallOptions {
                        no_wire: true,
                        ..Default::default()
                    },
                    ..Default::default()
                },
                None,
                10,
            )
        })
    }));
    assert!(
        result.is_ok(),
        "nonUTF8 admission must not panic while serializing metadata"
    );
    assert!(result.unwrap().is_err());
    assert!(
        !root.join(".ken").exists(),
        "a rejected root cannot be partially provisioned"
    );
}
