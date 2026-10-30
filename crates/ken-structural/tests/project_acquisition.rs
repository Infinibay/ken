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
fn acquired_graph_retains_source_units_nodes_and_ast_for_indexed_queries() {
    use ken_query::execution::{Execution, GraphRead, SourceProbe};
    use ken_structural::GraphSnapshot;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(root.join("a.py"), "def target(x): return x\n").unwrap();
    std::fs::write(root.join("empty.py"), "# no declarations\n").unwrap();
    let catalog = catalog();
    let front = Front {
        catalog: &catalog,
        fail: Cell::new(false),
        calls: Cell::new(0),
    };
    let db = root.join(".ken/source-reader.sqlite");
    let mut builder = builder(root, &front);
    let mut project = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let mut index = project.index().unwrap();
    let run = Execution::new(Default::default()).unwrap();
    let scope = index.execution(|| false).unwrap();
    let reader = GraphSnapshot::indexed(&scope, run.interruption());
    let mut units = vec![];
    reader
        .source_units(&mut || Ok(()), &mut |unit| {
            units.push(unit);
            Ok(())
        })
        .unwrap();
    assert_eq!(units.len(), 2);
    let mut nodes = vec![];
    reader
        .source_scan(
            &SourceProbe {
                kind: Some("CALLABLE".into()),
                ..Default::default()
            },
            &mut || Ok(()),
            &mut |node| {
                nodes.push(node);
                Ok(())
            },
        )
        .unwrap();
    assert_eq!(nodes.len(), 1);
    assert_eq!(nodes[0].name.as_deref(), Some("target"));
    assert!(nodes[0].id > 0);
    assert!(units.contains(&nodes[0].unit));
    assert_eq!(
        reader.source_node(&nodes[0].local_id).unwrap().unwrap(),
        nodes[0]
    );
    for unit in units {
        reader
            .source_program(unit)
            .unwrap()
            .unwrap()
            .validate()
            .unwrap();
    }
    assert!(reader.source_program(i64::MAX).unwrap().is_none());
    assert!(reader.source_coverage().unwrap());
    drop(reader);
    drop(scope);
    drop(index);
    drop(project);
    let mut again = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(again.analysis["query_index"]["hit"], true);
    assert_eq!(front.calls.get(), 2);
    let index = again.index().unwrap();
    let mut reopened = vec![];
    index
        .source_store()
        .snapshot_units_checked(index.snapshot_id(), |unit| {
            reopened.push(unit);
            Ok(())
        })
        .unwrap();
    assert_eq!(reopened.len(), 2);
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

#[test]
fn explicit_source_capture_is_confined_deduplicated_and_does_not_include_other_files() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::create_dir(root.join("nested")).unwrap();
    std::fs::write(root.join("a.py"), "def a(): return 1\n").unwrap();
    std::fs::write(root.join("nested/b.py"), "def b(): return 2\n").unwrap();
    std::fs::write(root.join("other.py"), "def other(): return 3\n").unwrap();
    let catalog = catalog();
    let front = Front {
        catalog: &catalog,
        fail: Cell::new(false),
        calls: Cell::new(0),
    };
    let mut builder = builder(root, &front);
    let db = root.join(".ken/structural/v2/explicit.sqlite");
    let sources = vec!["nested/b.py".into(), "a.py".into(), "a.py".into()];
    let mut acquired = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire_sources(
            Path::new("."),
            Some(&sources),
            ScanLimits::default(),
            || Ok(()),
        )
        .unwrap();
    assert_eq!(front.calls.get(), 2);
    assert_eq!(
        acquired.analysis["files"],
        serde_json::json!(["a.py", "nested/b.py"])
    );
    let mut index = acquired.index().unwrap();
    let mut units = vec![];
    index
        .source_store()
        .snapshot_units_checked(index.snapshot_id(), &mut |id| {
            units.push(id);
            Ok(())
        })
        .unwrap();
    assert_eq!(units.len(), 2);
    {
        use ken_query::execution::GraphRead;
        let scope = index.execution(|| false).unwrap();
        let snapshot =
            ken_structural::GraphSnapshot::indexed(&scope, Default::default()).with_coverage(false);
        assert!(!snapshot.source_coverage().unwrap());
    }
    drop(index);
    use sha2::{Digest, Sha256};
    let expected = serde_json::json!([
        [
            "a.py",
            format!("{:x}", Sha256::digest(b"def a(): return 1\n"))
        ],
        [
            "nested/b.py",
            format!("{:x}", Sha256::digest(b"def b(): return 2\n"))
        ]
    ]);
    assert_eq!(acquired.analysis["manifest"], expected);
    let empty: Vec<String> = vec![];
    let empty = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire_sources(Path::new("."), Some(&empty), ScanLimits::default(), || {
            Ok(())
        })
        .unwrap();
    assert_eq!(empty.analysis["files"], serde_json::json!([]));
    assert!(
        ProjectAcquisition::new(&mut builder, &db, true)
            .acquire_sources(
                Path::new("nested"),
                Some(&["a.py".into()]),
                ScanLimits::default(),
                || Ok(())
            )
            .is_err()
    );
    assert!(
        ProjectAcquisition::new(&mut builder, &db, true)
            .acquire_sources(
                Path::new("."),
                Some(&["../outside.py".into()]),
                ScanLimits::default(),
                || Ok(())
            )
            .is_err()
    );
    assert!(
        ProjectAcquisition::new(&mut builder, &db, true)
            .acquire_sources(
                Path::new("."),
                Some(&["nested".into()]),
                ScanLimits::default(),
                || Ok(())
            )
            .is_err()
    );
}

#[test]
fn retained_reader_does_not_repin_during_queries_or_revive_expired_lease() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(root.join("a.py"), "def a(): return 1\n").unwrap();
    let catalog = catalog();
    let front = Front {
        catalog: &catalog,
        fail: Cell::new(false),
        calls: Cell::new(0),
    };
    let mut builder = builder(root, &front);
    let db = root.join(".ken/structural/v2/retained.sqlite");
    let mut acquired = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    {
        let _prepared = acquired.index().unwrap();
    }
    acquired.source_store_mut().defer_busy_renewal = true;
    acquired
        .source_store()
        .connection()
        .busy_timeout(std::time::Duration::ZERO)
        .unwrap();
    let before = acquired.source_store().connection().total_changes();
    let writer = rusqlite::Connection::open(&db).unwrap();
    writer.execute_batch("BEGIN IMMEDIATE").unwrap();
    {
        let reader = acquired.retained_index().unwrap();
        reader.check_snapshot().unwrap();
    }
    assert_eq!(acquired.source_store().connection().total_changes(), before);
    writer.execute_batch("ROLLBACK").unwrap();
    writer
        .execute("UPDATE k2_leases SET expires_ns=0", [])
        .unwrap();
    assert!(acquired.retained_index().is_err());
    assert_eq!(
        writer
            .query_row("SELECT MAX(expires_ns) FROM k2_leases", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
    acquired.close().unwrap();
}
