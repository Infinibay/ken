use ken_structural::application::modules::{ModuleRegistry, ModuleResolver, RegistryReader};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    sync::{Arc, Barrier},
};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/module-registry-domain.json")).unwrap()
}
fn seed(root: &std::path::Path) -> ModuleRegistry {
    let f = fixture();
    let registry = ModuleRegistry::new(root).unwrap();
    for (i, key) in ["library", "middle", "entry"].iter().enumerate() {
        registry
            .save_at(
                f["sources"][key].as_str().unwrap(),
                if i == 0 { Some("Library") } else { None },
                None,
                1001 + i as i64,
            )
            .unwrap();
    }
    registry
}
#[test]
fn persistent_registry_and_immutable_generations_match_frozen_original() {
    let d = tempfile::tempdir().unwrap();
    let f = fixture();
    let registry = ModuleRegistry::new(d.path()).unwrap();
    let mut reader = RegistryReader::new(d.path()).unwrap();
    assert_eq!(reader.snapshot().unwrap().to_value(true), f["missing"]);
    assert!(!d.path().join(".ken").exists());
    for (i, key) in ["library", "middle", "entry"].iter().enumerate() {
        let saved = registry
            .save_at(
                f["sources"][key].as_str().unwrap(),
                if i == 0 { Some("Library") } else { None },
                None,
                1001 + i as i64,
            )
            .unwrap();
        assert_eq!(saved.to_value(true), f["records"][i]);
    }
    let old = reader.snapshot().unwrap();
    assert_eq!(old.to_value(true), f["snapshot"]);
    assert_eq!(
        registry
            .save_at(f["sources"]["library"].as_str().unwrap(), None, None, 2000)
            .unwrap()
            .to_value(true),
        f["idempotent_record"]
    );
    assert!(Arc::ptr_eq(&old, &reader.snapshot().unwrap()));
    let source = f["sources"]["library"]
        .as_str()
        .unwrap()
        .replace("write", "close");
    let updated = registry
        .save_at(
            &source,
            None,
            Some(f["records"][0]["revision"].as_str().unwrap()),
            1004,
        )
        .unwrap();
    assert_eq!(updated.to_value(true), f["updated"]);
    assert_eq!(reader.snapshot().unwrap().to_value(true), f["after"]);
    assert_eq!(old.to_value(true), f["snapshot"]);
    registry.delete("project.search", None).unwrap();
    registry.delete("project.conventions", None).unwrap();
    registry.delete("project.types", None).unwrap();
    assert_eq!(reader.snapshot().unwrap().to_value(true), f["empty"]);
    reader.close().unwrap();
    assert_eq!(
        reader.snapshot().unwrap_err().to_string(),
        f["errors"]["closed_reader"].as_str().unwrap()
    );
    assert!(!d.path().join(".ken/structural").exists());
}
#[test]
fn resolver_pins_transitive_imports_and_explicit_override_without_mutating_old_result() {
    let d = tempfile::tempdir().unwrap();
    let registry = seed(d.path());
    let f = fixture();
    let mut resolver = ModuleResolver::new(d.path(), BTreeMap::new());
    let saved = resolver
        .resolve(None, Some("project.search"), Some("writers"), None)
        .unwrap();
    assert_eq!(serde_json::to_value(&saved).unwrap(), f["saved"]);
    let supplied = BTreeMap::from([(
        "project.types".into(),
        f["sources"]["library"]
            .as_str()
            .unwrap()
            .replace("write", "close"),
    )]);
    let inline = f["sources"]["entry"].as_str().unwrap();
    assert_eq!(
        serde_json::to_value(
            resolver
                .resolve(Some(inline), None, None, Some(&supplied))
                .unwrap()
        )
        .unwrap(),
        f["override"]
    );
    let old = resolver.resolve(Some(inline), None, None, None).unwrap();
    registry
        .save_at(
            &supplied["project.types"],
            None,
            Some(f["records"][0]["revision"].as_str().unwrap()),
            1004,
        )
        .unwrap();
    let new = resolver.resolve(Some(inline), None, None, None).unwrap();
    assert_eq!(serde_json::to_value(&old).unwrap(), f["old"]);
    assert_eq!(serde_json::to_value(&new).unwrap(), f["new"]);
    let mut result = json!({"rows":[]});
    new.annotate(&mut result).unwrap();
    assert_eq!(result, f["annotation"]);
    resolver.close().unwrap();
    assert_eq!(
        resolver
            .resolve(Some(inline), None, None, None)
            .unwrap_err()
            .to_string(),
        f["errors"]["closed_resolver"].as_str().unwrap()
    );
}
#[test]
fn registry_failures_do_not_replace_previous_record_or_advance_generation() {
    let d = tempfile::tempdir().unwrap();
    let registry = seed(d.path());
    let f = fixture();
    let library = f["sources"]["library"].as_str().unwrap();
    let replacement = library.replace("write", "close");
    assert_eq!(
        registry
            .save_at(&replacement, None, None, 10)
            .unwrap_err()
            .to_string(),
        f["errors"]["update_without_revision"].as_str().unwrap()
    );
    assert_eq!(
        registry
            .save_at(&replacement, None, Some("stale"), 10)
            .unwrap_err()
            .to_string(),
        f["errors"]["stale_revision"].as_str().unwrap()
    );
    assert_eq!(
        registry
            .delete("project.types", None)
            .unwrap_err()
            .to_string(),
        f["errors"]["imported_delete"].as_str().unwrap()
    );
    let missing = "language \"kql/2\"; module project.missing_client; import project.absent; query q {select 1;}";
    assert_eq!(
        registry
            .save_at(missing, None, None, 10)
            .unwrap_err()
            .to_string(),
        f["errors"]["missing_import"].as_str().unwrap()
    );
    let mut reader = RegistryReader::new(d.path()).unwrap();
    assert_eq!(reader.snapshot().unwrap().to_value(true), f["snapshot"]);
    let mut resolver = ModuleResolver::new(d.path(), BTreeMap::new());
    assert_eq!(
        resolver
            .resolve(None, Some("project.types"), None, None)
            .unwrap_err()
            .to_string(),
        f["errors"]["pattern_only"].as_str().unwrap()
    );
    assert_eq!(
        resolver
            .resolve(None, Some("project.search"), Some("absent"), None)
            .unwrap_err()
            .to_string(),
        f["errors"]["unknown_query"].as_str().unwrap()
    );
    assert!(resolver.resolve(None, None, None, None).is_err());
    assert!(
        resolver
            .resolve(Some(library), Some("project.search"), None, None)
            .is_err()
    );
}
#[test]
fn absent_invalid_reserved_and_missing_import_reads_do_not_create_database() {
    let d = tempfile::tempdir().unwrap();
    let registry = ModuleRegistry::new(d.path()).unwrap();
    assert!(registry.list_modules().unwrap().is_empty());
    for source in [
        "not KQL",
        "language \"kql/2\"; module ken.core; query q {select 1;}",
        "language \"kql/2\"; module ken.catalog.custom; query q {select 1;}",
        "language \"kql/2\"; module project.bad; import project.absent; query q {select 1;}",
    ] {
        assert!(registry.save_at(source, None, None, 1).is_err());
    }
    assert!(!d.path().join(".ken").exists());
    let mut resolver = ModuleResolver::new(d.path(), BTreeMap::new());
    let inline = "language \"kql/2\"; module plain; query q {select 1;}";
    assert_eq!(
        resolver
            .resolve(Some(inline), None, None, None)
            .unwrap()
            .source,
        inline
    );
    resolver.close().unwrap();
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn reader_rejects_another_thread_without_losing_owner_state() {
    let d = tempfile::tempdir().unwrap();
    seed(d.path());
    let reader = RegistryReader::new(d.path()).unwrap();
    let (mut reader, error) = std::thread::spawn(move || {
        let mut reader = reader;
        let error = reader.snapshot().unwrap_err().to_string();
        (reader, error)
    })
    .join()
    .unwrap();
    assert_eq!(error, fixture()["owner_error"].as_str().unwrap());
    assert_eq!(reader.snapshot().unwrap().generation, 3);
    reader.close().unwrap();
}
#[cfg(unix)]
#[test]
fn reader_detects_database_alias_retarget_and_same_path_inode_replacement() {
    let d = tempfile::tempdir().unwrap();
    for name in ["one", "two"] {
        std::fs::create_dir(d.path().join(name)).unwrap();
    }
    let one = seed(&d.path().join("one"));
    let two = seed(&d.path().join("two"));
    let f = fixture();
    let changed = f["sources"]["library"]
        .as_str()
        .unwrap()
        .replace("write", "close");
    two.save_at(
        &changed,
        None,
        Some(f["records"][0]["revision"].as_str().unwrap()),
        1004,
    )
    .unwrap();
    std::fs::create_dir(d.path().join(".ken")).unwrap();
    let alias = d.path().join(".ken/ken.db");
    std::os::unix::fs::symlink(d.path().join("one/.ken/ken.db"), &alias).unwrap();
    let mut reader = RegistryReader::new(d.path()).unwrap();
    let old = reader.snapshot().unwrap();
    std::fs::remove_file(&alias).unwrap();
    std::os::unix::fs::symlink(d.path().join("two/.ken/ken.db"), &alias).unwrap();
    assert_ne!(
        reader.snapshot().unwrap().modules()["project.types"].revision,
        old.modules()["project.types"].revision
    );
    reader.close().unwrap();
    drop(one);
    drop(two);
    std::fs::remove_file(&alias).unwrap();
    std::fs::copy(d.path().join("one/.ken/ken.db"), &alias).unwrap();
    let mut reader = RegistryReader::new(d.path()).unwrap();
    let old = reader.snapshot().unwrap();
    let replacement = d.path().join("replacement.db");
    std::fs::copy(d.path().join("two/.ken/ken.db"), &replacement).unwrap();
    std::fs::rename(replacement, &alias).unwrap();
    assert_ne!(
        reader.snapshot().unwrap().modules()["project.types"].revision,
        old.modules()["project.types"].revision
    );
}
#[test]
fn compare_and_swap_writers_cannot_both_publish_from_one_revision() {
    let d = tempfile::tempdir().unwrap();
    let registry = seed(d.path());
    let f = fixture();
    let revision = f["records"][0]["revision"].as_str().unwrap().to_owned();
    let source = f["sources"]["library"].as_str().unwrap().to_owned();
    let barrier = Arc::new(Barrier::new(2));
    let mut writers = Vec::new();
    for index in 0..2 {
        let root = d.path().to_path_buf();
        let barrier = barrier.clone();
        let revision = revision.clone();
        let source = source.clone();
        writers.push(std::thread::spawn(move || {
            let registry = ModuleRegistry::new(&root).unwrap();
            barrier.wait();
            registry
                .save_at(
                    &source,
                    Some(&format!("writer-{index}")),
                    Some(&revision),
                    20 + index,
                )
                .is_ok()
        }));
    }
    assert_eq!(
        writers
            .into_iter()
            .map(|w| w.join().unwrap())
            .filter(|ok| *ok)
            .count(),
        1
    );
    assert_ne!(registry.get("project.types").unwrap().revision, revision);
}
#[test]
fn packaged_imports_override_and_cycles_keep_one_immutable_closure() {
    let d = tempfile::tempdir().unwrap();
    let f = fixture();
    let packaged_source = f["sources"]["library"]
        .as_str()
        .unwrap()
        .replace("project.types", "ken.catalog.custom");
    let packaged = BTreeMap::from([("ken.catalog.custom".into(), packaged_source.clone())]);
    let entry = "language \"kql/2\"; module plain; import ken.catalog.custom; query q {select 1;}";
    let mut resolver = ModuleResolver::new(d.path(), packaged.clone());
    let loaded = resolver.resolve(Some(entry), None, None, None).unwrap();
    assert_eq!(loaded.libraries()["ken.catalog.custom"], packaged_source);
    assert!(loaded.revisions().is_empty());
    assert!(!d.path().join(".ken").exists());
    let explicit = BTreeMap::from([(
        "ken.catalog.custom".into(),
        packaged_source.replace("write", "close"),
    )]);
    assert_eq!(
        resolver
            .resolve(Some(entry), None, None, Some(&explicit))
            .unwrap()
            .libraries(),
        &explicit
    );
    let registry = seed(d.path());
    let before = registry.get("project.types").unwrap();
    let cyclic = before.source.replace(
        "pattern HasWrite",
        "import project.conventions; pattern HasWrite",
    );
    registry
        .save_at(&cyclic, None, Some(&before.revision), 1004)
        .unwrap();
    let mut resolver = ModuleResolver::new(d.path(), packaged);
    let resolved = resolver
        .resolve(
            Some(f["sources"]["entry"].as_str().unwrap()),
            None,
            None,
            None,
        )
        .unwrap();
    assert_eq!(resolved.libraries().len(), 2);
}
#[test]
fn failed_sql_publication_preserves_generation_and_unrelated_knowledge() {
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir(d.path().join(".ken")).unwrap();
    {
        let db = rusqlite::Connection::open(d.path().join(".ken/ken.db")).unwrap();
        db.execute_batch("CREATE TABLE existing_knowledge(topic TEXT);INSERT INTO existing_knowledge VALUES('keep');").unwrap();
    }
    let registry = seed(d.path());
    let before = registry.get("project.types").unwrap();
    let mut reader = RegistryReader::new(d.path()).unwrap();
    let snapshot = reader.snapshot().unwrap();
    {
        let db = rusqlite::Connection::open(d.path().join(".ken/ken.db")).unwrap();
        db.execute_batch("CREATE TRIGGER reject_module BEFORE UPDATE ON kql_modules WHEN NEW.description='reject' BEGIN SELECT RAISE(ABORT,'rejected publication');END;").unwrap();
    }
    assert!(
        registry
            .save_at(&before.source, Some("reject"), Some(&before.revision), 1004)
            .is_err()
    );
    assert_eq!(registry.get("project.types").unwrap(), before);
    assert_eq!(
        reader.snapshot().unwrap().to_value(true),
        snapshot.to_value(true)
    );
    let db = rusqlite::Connection::open(d.path().join(".ken/ken.db")).unwrap();
    assert_eq!(
        db.query_row("SELECT topic FROM existing_knowledge", [], |r| r
            .get::<_, String>(0))
            .unwrap(),
        "keep"
    );
}

#[cfg(unix)]
#[test]
fn authoring_registry_rejects_external_storage_created_after_constructor() {
    let project = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let registry = ModuleRegistry::new(project.path()).unwrap();
    std::fs::write(outside.path().join("marker"), "unchanged").unwrap();
    std::os::unix::fs::symlink(outside.path(), project.path().join(".ken")).unwrap();
    let f = fixture();
    let source = f["sources"]["library"].as_str().unwrap();
    let listed = registry.list_modules();
    let saved = registry.save_at(source, None, None, 123);
    let deleted = registry.delete("project.types", None);
    assert!(
        !outside.path().join("ken.db").exists(),
        "authoring operations created an external database"
    );
    assert!(listed.is_err());
    assert!(saved.is_err());
    assert!(deleted.is_err());
    assert_eq!(
        std::fs::read(outside.path().join("marker")).unwrap(),
        b"unchanged"
    );
}

#[cfg(unix)]
#[test]
fn authoring_registry_revalidates_storage_replaced_between_calls() {
    let project = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let registry = seed(project.path());
    let external = seed(outside.path());
    let entry = registry.get("project.search").unwrap();
    assert_eq!(registry.list_modules().unwrap().len(), 3);
    let before = std::fs::read(outside.path().join(".ken/ken.db")).unwrap();
    std::fs::rename(
        project.path().join(".ken"),
        project.path().join(".ken.saved"),
    )
    .unwrap();
    std::os::unix::fs::symlink(outside.path().join(".ken"), project.path().join(".ken")).unwrap();
    let listed = registry.list_modules();
    let saved = registry.save_at(&entry.source, Some("escaped"), Some(&entry.revision), 124);
    let deleted = registry.delete("project.search", None);
    assert!(
        std::fs::read(outside.path().join(".ken/ken.db")).unwrap() == before,
        "authoring operations changed an external database"
    );
    assert!(listed.is_err());
    assert!(saved.is_err());
    assert!(deleted.is_err());
    assert_eq!(external.get("project.search").unwrap(), entry);
    std::fs::remove_file(project.path().join(".ken")).unwrap();
    std::fs::rename(
        project.path().join(".ken.saved"),
        project.path().join(".ken"),
    )
    .unwrap();
    assert_eq!(registry.get("project.search").unwrap(), entry);
}
