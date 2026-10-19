use ken_store::ProjectDatabase;

#[test]
fn model_facts_and_initial_pin_preserve_marker_and_vector_boundaries() {
    struct Case {
        recorded: Option<Option<&'static str>>,
        embedding: Option<&'static [u8]>,
        slot: Option<i64>,
        fresh: bool,
    }
    let cases = [
        Case {
            recorded: None,
            embedding: None,
            slot: None,
            fresh: true,
        },
        Case {
            recorded: Some(None),
            embedding: None,
            slot: None,
            fresh: true,
        },
        Case {
            recorded: Some(Some("")),
            embedding: None,
            slot: None,
            fresh: false,
        },
        Case {
            recorded: Some(Some("stored/model")),
            embedding: None,
            slot: None,
            fresh: false,
        },
        Case {
            recorded: None,
            embedding: Some(b""),
            slot: None,
            fresh: false,
        },
        Case {
            recorded: None,
            embedding: None,
            slot: Some(0),
            fresh: false,
        },
        Case {
            recorded: None,
            embedding: None,
            slot: Some(-1),
            fresh: false,
        },
    ];
    for Case {
        recorded,
        embedding,
        slot,
        fresh,
    } in cases
    {
        let root = tempfile::tempdir().unwrap();
        let mut db = ProjectDatabase::open(&root.path().join("ken.db")).unwrap();
        db.initialize().unwrap();
        db.connection()
            .execute_batch("DROP TABLE meta; CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
            .unwrap();
        db.set_meta("unrelated", "keep").unwrap();
        db.set_meta("embed_doc_space", "9").unwrap();
        if let Some(value) = recorded {
            db.connection()
                .execute("INSERT INTO meta VALUES('embed_model',?1)", [value])
                .unwrap();
        }
        db.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,embedding,vec_slot) VALUES('fixture',x'00',0,0,?1,?2)",
            rusqlite::params![embedding,slot]).unwrap();
        let expected = recorded.flatten().map(str::to_owned);
        let state = db.model_state().unwrap();
        assert_eq!(state.recorded_model, expected);
        assert_eq!(
            state.file_vectors_present,
            embedding.is_some() || slot.is_some()
        );
        let mut tx = db.immediate().unwrap();
        assert_eq!(tx.model_state().unwrap(), state);
        assert_eq!(tx.pin_model_if_fresh("user/model", 2).unwrap(), fresh);
        tx.commit().unwrap();
        assert_eq!(db.get_meta("unrelated").unwrap().as_deref(), Some("keep"));
        assert_eq!(
            db.get_meta("embed_doc_space").unwrap().as_deref(),
            Some(if fresh { "2" } else { "9" })
        );
        assert_eq!(
            db.get_meta("embed_model").unwrap(),
            if fresh {
                Some("user/model".into())
            } else {
                expected
            }
        );
    }
}

#[test]
fn sql_failure_never_becomes_proven_empty_state_or_a_new_pin() {
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("ken.db")).unwrap();
    db.initialize().unwrap();
    db.connection()
        .execute_batch("DROP TABLE ci_files")
        .unwrap();
    assert!(db.model_state().is_err());
    let mut tx = db.immediate().unwrap();
    assert!(tx.pin_model_if_fresh("wrong", 2).is_err());
    drop(tx);
    assert_eq!(db.get_meta("embed_model").unwrap(), None);
    assert_eq!(db.get_meta("embed_doc_space").unwrap(), None);
}

#[test]
fn a_failed_document_marker_cannot_leave_a_partial_model_pin() {
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("ken.db")).unwrap();
    db.initialize().unwrap();
    db.connection().execute_batch("CREATE TRIGGER reject_doc_space BEFORE INSERT ON meta WHEN new.key='embed_doc_space' BEGIN SELECT RAISE(ABORT,'fixture rejects document marker'); END").unwrap();
    let mut tx = db.immediate().unwrap();
    assert!(tx.pin_model_if_fresh("user/model", 2).is_err());
    assert!(!tx.connection().is_autocommit());
    tx.commit().unwrap();
    assert_eq!(db.get_meta("embed_model").unwrap(), None);
    assert_eq!(db.get_meta("embed_doc_space").unwrap(), None);
}
