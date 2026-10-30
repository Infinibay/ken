//! Caller contract for storage-owned generation replacement used by reembedding.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_store::{MaintenanceEvent, ProjectStore, VectorRebuild, VectorSpace};
fn fixture() -> (tempfile::TempDir, ProjectPaths, ProjectStore) {
    let root = tempfile::tempdir().unwrap();
    let paths = ProjectPaths::at(
        root.path(),
        &DiscoveryContext {
            cwd: root.path().into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let mut store = ProjectStore::open(&paths).unwrap();
    store.initialize().unwrap();
    store.database().connection().execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot)VALUES(1,'a.py',x'',0,0,0)",[]).unwrap();
    store
        .database()
        .connection()
        .execute(
            "INSERT INTO ci_vec_alloc(space,next_slot)VALUES('ci_files',1)",
            [],
        )
        .unwrap();
    store.database().set_meta("embed_model", "old").unwrap();
    store
        .vectors(VectorSpace::Files, 2, Some("old"))
        .unwrap()
        .write(&[0], &[vec![1., 0.]], true)
        .unwrap();
    (root, paths, store)
}
#[test]
fn replacement_keeps_old_generation_until_atomic_commit_and_preserves_private_files() {
    let (_root, paths, mut store) = fixture();
    std::fs::write(paths.vectors().join("private-note"), "preserve me").unwrap();
    let mut replacement = VectorRebuild::begin(&store, 4, Some("new")).unwrap();
    replacement
        .write(VectorSpace::Files, &[1], &[vec![0., 0., 0., 1.]])
        .unwrap();
    assert_eq!(
        store
            .vectors(VectorSpace::Files, 2, Some("old"))
            .unwrap()
            .read(&[0])
            .unwrap(),
        vec![vec![1., 0.]]
    );
    replacement
        .commit(
            &mut store,
            |tx| {
                tx.connection()
                    .execute("UPDATE meta SET value='new' WHERE key='embed_model'", [])
                    .map_err(|source| ken_store::StoreError::Sqlite {
                        path: paths.db(),
                        source,
                    })?;
                Ok(())
            },
            &mut |_| {},
        )
        .unwrap();
    drop(store);
    let store = ProjectStore::open(&paths).unwrap();
    assert_eq!(
        store
            .vectors(VectorSpace::Files, 4, Some("new"))
            .unwrap()
            .read(&[0])
            .unwrap(),
        vec![vec![0., 0., 0., 1.]]
    );
    assert_eq!(
        std::fs::read_to_string(paths.vectors().join("private-note")).unwrap(),
        "preserve me"
    );
    assert_eq!(
        store.database().get_meta("embed_model").unwrap().as_deref(),
        Some("new")
    );
}
#[test]
fn reopen_recovers_each_filesystem_and_sqlite_publication_boundary() {
    for stage in ["journal", "backup", "new", "committed"] {
        let (_root, paths, mut store) = fixture();
        let mut replacement = VectorRebuild::begin(&store, 4, Some("new")).unwrap();
        replacement
            .write(VectorSpace::Files, &[1], &[vec![0., 0., 0., 1.]])
            .unwrap();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            replacement.commit(
                &mut store,
                |tx| {
                    tx.connection()
                        .execute("UPDATE meta SET value='new' WHERE key='embed_model'", [])
                        .map_err(|source| ken_store::StoreError::Sqlite {
                            path: paths.db(),
                            source,
                        })?;
                    Ok(())
                },
                &mut |event| {
                    let stop = matches!(
                        (stage, event),
                        ("journal", MaintenanceEvent::JournalPublished)
                            | ("backup", MaintenanceEvent::BackupRenamed)
                            | ("new", MaintenanceEvent::NewPublished)
                            | ("committed", MaintenanceEvent::DatabaseCommitted)
                    );
                    if stop {
                        panic!("injected publication crash");
                    }
                },
            )
        }));
        assert!(result.is_err());
        drop(store);
        let store = ProjectStore::open(&paths).unwrap();
        let committed = stage == "committed";
        let model = if committed { "new" } else { "old" };
        let dim = if committed { 4 } else { 2 };
        assert_eq!(
            store.database().get_meta("embed_model").unwrap().as_deref(),
            Some(model)
        );
        assert_eq!(
            store
                .vectors(VectorSpace::Files, dim, Some(model))
                .unwrap()
                .read(&[0])
                .unwrap()[0]
                .len(),
            dim
        );
        assert!(!paths.root().join(".ken/vectors-maintenance.json").exists());
    }
}
#[test]
fn concurrent_slot_allocation_and_source_guard_abort_before_generation_swap() {
    let (_root, paths, mut store) = fixture();
    let mut replacement = VectorRebuild::begin(&store, 4, Some("new")).unwrap();
    replacement
        .write(VectorSpace::Files, &[1], &[vec![0., 0., 0., 1.]])
        .unwrap();
    store
        .database()
        .connection()
        .execute(
            "UPDATE ci_vec_alloc SET next_slot=2 WHERE space='ci_files'",
            [],
        )
        .unwrap();
    assert!(
        replacement
            .commit(&mut store, |_| Ok(()), &mut |_| {})
            .is_err()
    );
    let mut replacement = VectorRebuild::begin(&store, 4, Some("new")).unwrap();
    replacement
        .write(VectorSpace::Files, &[1], &[vec![0., 0., 0., 1.]])
        .unwrap();
    assert!(
        replacement
            .commit(
                &mut store,
                |_| Err(ken_store::StoreError::InvalidSlot(
                    "source changed while encoding"
                )),
                &mut |_| {}
            )
            .is_err()
    );
    assert_eq!(
        store
            .vectors(VectorSpace::Files, 2, Some("old"))
            .unwrap()
            .read(&[0])
            .unwrap()[0],
        vec![1., 0.]
    );
    assert!(!paths.root().join(".ken/vectors-maintenance.json").exists());
}
