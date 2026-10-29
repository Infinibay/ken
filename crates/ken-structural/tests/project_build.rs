//! Captured original service behavior plus native invalidation/failure boundaries.
use flate2::read::GzDecoder;
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_program::StructuralIr;
use ken_store::artifact_cache::ArtifactCache;
use ken_structural::{BuildError, Frontend, NativeFrontend, ProjectBuilder, ScanLimits};
use ken_syntax::{GrammarCatalog, Language, structural::lower_source};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    io::Read,
    path::{Path, PathBuf},
};
fn catalog() -> GrammarCatalog {
    GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap()
}
fn context(root: &Path) -> DiscoveryContext {
    DiscoveryContext {
        cwd: root.into(),
        forced_root: None,
        home: None,
    }
}
fn corpus() -> Value {
    let b = include_bytes!("project-build-reference.json.gz");
    assert_eq!(b.len(), 70425);
    assert_eq!(
        format!("{:x}", Sha256::digest(b)),
        "e925a0072a30650ecc99ad275a9fc7caa3d1a84ff6e819ade4fc5eacd3ef9997"
    );
    let mut s = String::new();
    GzDecoder::new(&b[..]).read_to_string(&mut s).unwrap();
    serde_json::from_str(&s).unwrap()
}
fn put(root: &Path, path: &str, text: &str) {
    let path = root.join(path);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, text).unwrap();
}
struct Pinned<'a> {
    catalog: &'a GrammarCatalog,
    revision: &'a str,
    failed: Cell<bool>,
    calls: Cell<usize>,
}
impl Frontend for Pinned<'_> {
    fn revision(&self) -> &str {
        self.revision
    }
    fn lower(&self, b: &[u8], language: Language, path: &str) -> Result<StructuralIr, String> {
        self.calls.set(self.calls.get() + 1);
        if self.failed.get() && path == "failure.py" {
            return Err("RuntimeError: injected failure".into());
        }
        lower_source(self.catalog, language, b, path).map_err(|e| e.to_string())
    }
}
fn canonical(mut ir: Value) -> Value {
    ir["facts"]
        .as_array_mut()
        .unwrap()
        .sort_by_key(Value::to_string);
    ir
}
fn builder<'a>(root: &Path, frontend: &'a dyn Frontend, mb: f64) -> ProjectBuilder<'a> {
    let ctx = context(root);
    let paths = ProjectPaths::at(root, &ctx).unwrap();
    ProjectBuilder::new(
        paths,
        ctx,
        frontend,
        ArtifactCache::open(&root.join(".ken/structural-cache.sqlite"), mb).unwrap(),
    )
}
#[test]
fn original_manifest_keys_build_graphs_edits_limits_and_frontend_recovery_match() {
    let data = corpus();
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    for (p, t) in data["files"].as_object().unwrap() {
        put(root, p, t.as_str().unwrap());
    }
    let catalog = catalog();
    let frontend = Pinned {
        catalog: &catalog,
        revision: data["versions"].as_str().unwrap(),
        failed: Cell::new(false),
        calls: Cell::new(0),
    };
    for case in data["builds"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        match name {
            "edited" => put(root, "a.py", "class BuildA:\n def value(self): return 8\n"),
            "deleted" => std::fs::remove_file(root.join("pkg/b.py")).unwrap(),
            "added" => put(
                root,
                "added.py",
                "def added_build(x): return x\nadded_build(2)\n",
            ),
            "frontend_failed" => {
                put(root, "failure.py", "def recovered_build(): return 12\n");
                frontend.failed.set(true);
            }
            "frontend_recovered" => frontend.failed.set(false),
            _ => {}
        }
        let options = &case["options"];
        let limits = ScanLimits {
            max_files: options["max_files"].as_u64().map(|n| n as usize),
            max_file_bytes: options["max_file_bytes"].as_u64().unwrap_or(2000000),
        };
        let report = builder(root, &frontend, 500.)
            .build(
                Path::new(options["path"].as_str().unwrap_or(".")),
                limits,
                || Ok(()),
            )
            .unwrap();
        assert_eq!(
            canonical(serde_json::to_value(report.graph).unwrap()),
            canonical(case["result"].clone()),
            "{name} graph"
        );
        let mut analysis = serde_json::to_value(report.analysis).unwrap();
        analysis.as_object_mut().unwrap().remove("elapsed_ms");
        analysis["cache"].as_object_mut().unwrap().remove("bytes");
        // Linked graphs have an independent native-engine namespace. Source-unit
        // framing stays compatible with the original frontend revision contract.
        let mut expected = case["analysis"].clone();
        expected["graph_key"] = ArtifactCache::key([
            b"native-project-graph/1".as_slice(),
            ken_structural::IMPLEMENTATION_FINGERPRINT.as_bytes(),
            case["analysis"]["graph_key"].as_str().unwrap().as_bytes(),
        ])
        .into();
        assert_eq!(analysis, expected, "{name} analysis");
    }
    for case in data["manifests"].as_array().unwrap() {
        let manifest = builder(root, &frontend, 0.)
            .manifest(
                Path::new(case["scope"].as_str().unwrap()),
                ScanLimits {
                    max_files: case["max_files"].as_u64().map(|n| n as usize),
                    max_file_bytes: case["max_file_bytes"].as_u64().unwrap(),
                },
                || Ok(()),
            )
            .unwrap();
        let entries = manifest
            .entries()
            .iter()
            .map(|e| json!([e.path(), e.key(), e.content()]))
            .collect::<Vec<_>>();
        assert_eq!(serde_json::to_value(entries).unwrap(), case["entries"]);
        assert_eq!(
            serde_json::to_value(manifest.skipped()).unwrap(),
            case["skipped"]
        );
    }
    for case in data["keys"].as_array().unwrap() {
        let parts = case["parts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| s.as_str().unwrap().as_bytes())
            .collect::<Vec<_>>();
        assert_eq!(ArtifactCache::key(parts), case["value"].as_str().unwrap());
    }
}
#[test]
fn captured_manifest_is_one_revision_and_frontend_revision_invalidates_cache() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    put(root, "a.py", "def build_revision(): return 1\n");
    let catalog = catalog();
    let one = Pinned {
        catalog: &catalog,
        revision: "one",
        failed: Cell::new(false),
        calls: Cell::new(0),
    };
    let mut service = builder(root, &one, 2.);
    let manifest = service
        .manifest(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let captured = manifest.graph_key().to_string();
    put(root, "a.py", "def build_revision(): return 2\n");
    let report = service.build_manifest(manifest, || Ok(())).unwrap();
    assert_eq!(captured, report.analysis.graph_key);
    assert!(
        report
            .graph
            .entities
            .iter()
            .any(|(_, e)| e.attrs.get("literal").is_some_and(|v| v.get() == "\"1\""))
    );
    let report = service
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_ne!(captured, report.analysis.graph_key);
    let changed = report.analysis.graph_key;
    let report = service
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(report.analysis.cache.hits, 1);
    assert_eq!(report.analysis.cache.misses, 0);
    let two = Pinned {
        catalog: &catalog,
        revision: "two",
        failed: Cell::new(false),
        calls: Cell::new(0),
    };
    let report = builder(root, &two, 2.)
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_ne!(changed, report.analysis.graph_key);
    assert_eq!(two.calls.get(), 1);
    let native = NativeFrontend::new(&catalog);
    assert!(
        native
            .revision()
            .contains(ken_structural::IMPLEMENTATION_FINGERPRINT)
    );
}
#[test]
fn fresh_omission_evidence_survives_graph_hits_and_cancellation_never_publishes_a_partial_graph() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    put(root, "a.py", "def complete_build(): return 3\n");
    let catalog = catalog();
    let frontend = Pinned {
        catalog: &catalog,
        revision: "cancel",
        failed: Cell::new(false),
        calls: Cell::new(0),
    };
    let report = builder(root, &frontend, 2.)
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert!(report.analysis.coverage_complete);
    let key = report.analysis.graph_key;
    put(root, "unsupported.kt", "class BuildUnsupported{}");
    let report = builder(root, &frontend, 2.)
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(report.analysis.graph_key, key);
    assert_eq!(report.analysis.cache.hits, 1);
    assert!(!report.analysis.coverage_complete);
    assert_eq!(report.analysis.skipped[0].reason, "no structural frontend");
    put(root, "b.py", "def cancelled_build():return 9\n");
    let mut service = builder(root, &frontend, 2.);
    let manifest = service
        .manifest(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let key = manifest.graph_key().to_string();
    let mut checks = 0;
    let result = service.build_manifest(manifest, || {
        checks += 1;
        if checks == 5 {
            Err(BuildError::Invalid("cancel build"))
        } else {
            Ok(())
        }
    });
    assert!(result.is_err());
    assert!(
        ArtifactCache::open(&root.join(".ken/structural-cache.sqlite"), 2.)
            .unwrap()
            .get_ir(&key)
            .is_none()
    );
    let recovered = service
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(recovered.analysis.files, vec!["a.py", "b.py"]);
    assert!(
        service
            .build(Path::new("missing"), ScanLimits::default(), || Ok(()))
            .is_err()
    );
    assert!(
        service
            .build(
                Path::new("."),
                ScanLimits {
                    max_files: Some(0),
                    ..Default::default()
                },
                || Ok(())
            )
            .is_err()
    );
}
#[cfg(unix)]
#[test]
fn confined_reads_and_explicit_single_files_preserve_coverage() {
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("project");
    std::fs::create_dir(&root).unwrap();
    let outside = temp.path().join("secret.py");
    std::fs::write(&outside, "def outside_build():return 1\n").unwrap();
    put(&root, ".gitignore", "ignored.py\n");
    put(&root, "ignored.py", "def ignored_build():return 1\n");
    symlink(&outside, root.join("escape.py")).unwrap();
    let catalog = catalog();
    let native = NativeFrontend::new(&catalog);
    let mut service = builder(&root, &native, 0.);
    let report = service
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert!(report.analysis.files.is_empty());
    assert!(!report.analysis.coverage_complete);
    assert_eq!(report.analysis.skipped[0].reason, "symlink escapes project");
    let report = service
        .build(Path::new("ignored.py"), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(report.analysis.files, vec!["ignored.py"]);
    assert!(
        service
            .build(Path::new("../secret.py"), ScanLimits::default(), || Ok(()))
            .is_err()
    );
    let ctx = context(&root);
    let paths = ProjectPaths::at(&root, &ctx).unwrap();
    let reader = ken_core::source_reader::SourceFileReader::new(&paths).unwrap();
    let handle = reader.open(Path::new("ignored.py")).unwrap();
    put(&root, "ignored.py", &"x".repeat(20000));
    assert!(handle.read_bounded(100).unwrap().is_none());
}

#[test]
fn wrong_identity_cache_entries_are_rebuilt() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let source = "def identity_build():return 1\n";
    put(root, "a.py", source);
    let catalog = catalog();
    let frontend = Pinned {
        catalog: &catalog,
        revision: "identity",
        failed: Cell::new(false),
        calls: Cell::new(0),
    };
    let mut service = builder(root, &frontend, 2.);
    let manifest = service
        .manifest(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let unit_key = manifest.entries()[0].key().to_string();
    let graph_key = manifest.graph_key().to_string();
    let mut foreign = lower_source(&catalog, Language::Python, source.as_bytes(), "b.py").unwrap();
    let path = root.join(".ken/structural-cache.sqlite");
    let mut cache = ArtifactCache::open(&path, 2.).unwrap();
    cache.put_ir(&unit_key, &foreign);
    drop(cache);
    let report = service.build_manifest(manifest, || Ok(())).unwrap();
    assert_eq!(
        frontend.calls.get(),
        1,
        "a foreign unit was treated as a cache hit"
    );
    assert!(report.graph.entities.iter().all(|(_, e)| e.path != "b.py"));
    foreign.path = "a.py".into();
    foreign.language = "javascript".into();
    let mut cache = ArtifactCache::open(&path, 2.).unwrap();
    cache.put_ir(&unit_key, &foreign);
    cache.put_ir(&graph_key, &foreign);
    drop(cache);
    let report = service
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    assert_eq!(report.graph.path, "<project>");
    assert_eq!(report.graph.language, "mixed");
    assert_eq!(frontend.calls.get(), 2);
}

#[test]
fn graph_cache_hits_check_cancellation_after_acquisition() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    put(root, "a.py", "def warm_cancel():return 1\n");
    let catalog = catalog();
    let frontend = Pinned {
        catalog: &catalog,
        revision: "warm-cancel",
        failed: Cell::new(false),
        calls: Cell::new(0),
    };
    let mut service = builder(root, &frontend, 2.);
    service
        .build(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let manifest = service
        .manifest(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let mut checks = 0;
    let result = service.build_manifest(manifest, || {
        checks += 1;
        if checks == 2 {
            Err(BuildError::Invalid("cancel warm project"))
        } else {
            Ok(())
        }
    });
    assert!(
        result.is_err(),
        "graph-hit completion never checked cancellation"
    );
    assert_eq!(checks, 2);
}
