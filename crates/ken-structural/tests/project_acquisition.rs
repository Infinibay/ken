use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_program::StructuralIr;
use ken_store::{artifact_cache::ArtifactCache, structural::graph::FactFilter};
use ken_structural::{BuildError, Frontend, ProjectAcquisition, ProjectBuilder, ScanLimits};
use ken_syntax::{GrammarCatalog, Language, structural::lower_source};
use std::{
    cell::Cell,
    path::{Path, PathBuf},
};
struct Front<'a> {
    catalog: &'a GrammarCatalog,
    fail: Cell<bool>,
    calls: Cell<usize>,
}
impl Frontend for Front<'_> {
    fn revision(&self) -> &str {
        "acquisition-test/1"
    }
    fn lower(&self, b: &[u8], lang: Language, path: &str) -> Result<StructuralIr, String> {
        self.calls.set(self.calls.get() + 1);
        if self.fail.get() {
            Err("injected failure".into())
        } else {
            lower_source(self.catalog, lang, b, path).map_err(|e| e.to_string())
        }
    }
}
fn catalog() -> GrammarCatalog {
    GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap()
}
fn builder<'a>(root: &Path, frontend: &'a dyn Frontend) -> ProjectBuilder<'a> {
    let context = DiscoveryContext {
        cwd: root.into(),
        forced_root: None,
        home: None,
    };
    ProjectBuilder::new(
        ProjectPaths::at(root, &context).unwrap(),
        context,
        frontend,
        ArtifactCache::open(&root.join(".ken/source-cache.sqlite"), 500.).unwrap(),
    )
}
#[test]
fn captured_project_acquisition_is_persistent_reusable_invalidated_and_ephemeral() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(
        root.join("a.py"),
        "def target(x): return x\ndef use(): return target(2)\n",
    )
    .unwrap();
    let catalog = catalog();
    let front = Front {
        catalog: &catalog,
        fail: Cell::new(false),
        calls: Cell::new(0),
    };
    let db = root.join(".ken/structural/v2/patterns.sqlite");
    let mut builder = builder(root, &front);
    let mut first = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert!(first.persistent());
    assert_eq!(front.calls.get(), 1);
    assert_eq!(first.analysis["query_index"]["hit"], false);
    let result = first
        .index()
        .unwrap()
        .count(&FactFilter::relation("RESULT"))
        .unwrap();
    assert!(result > 0);
    drop(first);
    let mut second = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(second.analysis["query_index"]["hit"], true);
    assert_eq!(front.calls.get(), 1);
    assert_eq!(
        second
            .index()
            .unwrap()
            .count(&FactFilter::relation("RESULT"))
            .unwrap(),
        result
    );
    let key = second.analysis["graph_key"].clone();
    drop(second);
    // Omission evidence belongs to this capture, even when analyzed bytes match.
    std::fs::write(root.join("unhandled.c"), "int x;\n").unwrap();
    let gap = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(gap.analysis["query_index"]["hit"], true);
    assert_eq!(gap.analysis["coverage_complete"], false);
    assert_eq!(gap.analysis["skipped"].as_array().unwrap().len(), 1);
    drop(gap);
    std::fs::write(root.join("a.py"), "def other(): return 42\n").unwrap();
    let changed = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(changed.analysis["query_index"]["hit"], false);
    assert_ne!(changed.analysis["graph_key"], key);
    drop(changed);
    let temporary = root.join("disabled.sqlite");
    let ephemeral = ProjectAcquisition::new(&mut builder, &temporary, false)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert!(!ephemeral.persistent());
    assert!(!temporary.exists());
    assert!(!temporary.with_extension("acquire.lock").exists());
}
#[test]
fn failed_frontend_does_not_poison_executable_graph_and_recovers() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(root.join("a.py"), "def target(): return 2\n").unwrap();
    let catalog = catalog();
    let front = Front {
        catalog: &catalog,
        fail: Cell::new(true),
        calls: Cell::new(0),
    };
    let db = root.join(".ken/index.sqlite");
    let mut builder = builder(root, &front);
    let failed = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert!(!failed.persistent());
    assert_eq!(failed.analysis["graph_key"], "");
    assert_eq!(failed.analysis["coverage_complete"], false);
    drop(failed);
    front.fail.set(false);
    let recovered = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert!(recovered.persistent());
    assert_eq!(recovered.analysis["query_index"]["hit"], false);
    assert_ne!(recovered.analysis["graph_key"], "");
    assert_eq!(front.calls.get(), 2);
}
#[test]
fn cancellation_during_lock_wait_releases_resources() {
    use std::os::fd::AsRawFd;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(root.join("a.py"), "x=1\n").unwrap();
    let catalog = catalog();
    let front = Front {
        catalog: &catalog,
        fail: Cell::new(false),
        calls: Cell::new(0),
    };
    let db = root.join("index.sqlite");
    let lock = std::fs::File::create(db.with_extension("acquire.lock")).unwrap(); // SAFETY: valid owned test descriptor.
    assert_eq!(
        unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) },
        0
    );
    let mut builder = builder(root, &front);
    let mut checks = 0;
    let result = ProjectAcquisition::new(&mut builder, &db, true).acquire(
        Path::new("."),
        ScanLimits::default(),
        || {
            checks += 1;
            if checks > 12 {
                Err(BuildError::Invalid("cancel lock wait"))
            } else {
                Ok(())
            }
        },
    );
    assert!(matches!(
        result,
        Err(BuildError::Invalid("cancel lock wait"))
    ));
    assert_eq!(front.calls.get(), 0);
    assert!(!db.exists());
    drop(lock);
    assert!(
        ProjectAcquisition::new(&mut builder, &db, true)
            .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
            .is_ok()
    );
}
