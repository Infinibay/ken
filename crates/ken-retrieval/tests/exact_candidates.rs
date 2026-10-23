use ken_retrieval::{
    EntityKey, Passage, PassageFields, PassagePolicy, Span, candidates::exact_candidates,
    query::SearchRequest, storage::replace_file_passages,
};
use ken_store::ProjectDatabase;
use rusqlite::params;
use std::collections::BTreeMap;
fn database(path: &str) -> (tempfile::TempDir, ProjectDatabase) {
    let temp = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&temp.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    db.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,language)VALUES(?1,x'00',0,0,'python')",[path]).unwrap();
    let mut passages = Vec::new();
    for (i, (qualname, kind)) in [
        ("Box.read", "method"),
        ("box.read", "method"),
        ("OtherName", "function"),
        ("Payload", "class"),
        ("Payload", "struct"),
    ]
    .iter()
    .enumerate()
    {
        let start = 1 + i * 10;
        let end = start + 7;
        db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end)VALUES(1,?1,?2,?3,?4,?5)",params![kind,qualname.rsplit('.').next().unwrap(),qualname,start as i64,end as i64]).unwrap();
        for (a, b) in [(start, start + 1), (start + 4, end)] {
            passages.push(Passage {
                entity: EntityKey {
                    path: path.into(),
                    kind: (*kind).into(),
                    qualname: Some((*qualname).into()),
                    owner: None,
                    definition_ordinal: 0,
                },
                span: Span::new(a, b).unwrap(),
                fields: PassageFields {
                    identity: format!("{kind} {qualname}").into(),
                    signature: format!("def {qualname}():").into(),
                    documentation: "".into(),
                    body: "return 1".into(),
                    path: path.into(),
                },
                source_hash: "a".repeat(64),
                entity_span: Span::new(start, end).unwrap(),
                language: "python".into(),
                role: "definition".into(),
                split_reason: None,
                signals: BTreeMap::new(),
                implementation_start_line: Some(start),
            });
        }
    }
    let tx = db.immediate().unwrap();
    replace_file_passages(
        &tx,
        1,
        &passages,
        Some(&"a".repeat(64)),
        &PassagePolicy::default(),
    )
    .unwrap();
    tx.commit().unwrap();
    (temp, db)
}
fn lookup(db: &ProjectDatabase, query: &str) -> Vec<ken_retrieval::query::Candidate> {
    exact_candidates(db.connection(), &SearchRequest::new(query).unwrap()).unwrap()
}
#[test]
fn exact_lookup_keeps_case_kind_namespace_and_complete_owned_regions_without_models() {
    let (_root, db) = database("src/store/config.py");
    for (q, name) in [
        ("Box.read", "Box.read"),
        ("box.read", "box.read"),
        ("OTHERNAME", "OtherName"),
        ("store.config::Box.read", "Box.read"),
        ("src/store/config.py::Box.read", "Box.read"),
    ] {
        let found = lookup(&db, q);
        assert_eq!(found.len(), 1, "{q}");
        assert_eq!(found[0].entity.qualname.as_deref(), Some(name));
        assert_eq!(found[0].passages.len(), 2);
        assert_eq!(found[0].owned_regions.len(), 2);
        assert_eq!(found[0].signals["exact"], 1.);
    }
    assert_eq!(lookup(&db, "BOX.read").len(), 2);
    for kind in ["class", "struct"] {
        let found = lookup(&db, &format!("Show the Payload {kind} declaration."));
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].entity.kind, kind);
    }
    assert!(lookup(&db, "other.config::Box.read").is_empty());
    assert!(lookup(&db, "Which function calls `store.config::Box.read`?").is_empty());
    assert_eq!(
        db.connection()
            .query_row("SELECT COUNT(*) FROM ci_retrieval_embeddings", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn exact_names_follow_own_writes_rollback_generation_reuse_and_other_connections() {
    let (_a, a) = database("src/store/config.py");
    let (_b, b) = database("other/config.py");
    assert_eq!(
        lookup(&a, "OtherName")[0].entity.path,
        "src/store/config.py"
    );
    assert_eq!(lookup(&b, "OtherName")[0].entity.path, "other/config.py");
    a.connection().execute_batch("SAVEPOINT edited;UPDATE ci_symbols SET name='temporary',qualname='temporary' WHERE name='OtherName';INSERT INTO meta(key,value)VALUES('retrieval_generation','2')ON CONFLICT(key)DO UPDATE SET value='2';").unwrap();
    assert!(lookup(&a, "OtherName").is_empty());
    assert_eq!(lookup(&a, "temporary").len(), 1);
    a.connection()
        .execute_batch("ROLLBACK TO edited;RELEASE edited;")
        .unwrap();
    assert_eq!(lookup(&a, "OtherName").len(), 1);
    a.connection().execute_batch("UPDATE ci_symbols SET name='final_name',qualname='final_name' WHERE name='OtherName';INSERT INTO meta(key,value)VALUES('retrieval_generation','2')ON CONFLICT(key)DO UPDATE SET value='2';").unwrap();
    assert!(lookup(&a, "temporary").is_empty());
    assert_eq!(lookup(&a, "final_name").len(), 1);
    assert_eq!(lookup(&b, "OtherName").len(), 1);
    a.connection().execute("DELETE FROM ci_files", []).unwrap();
    assert!(lookup(&a, "final_name").is_empty());
}
