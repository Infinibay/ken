use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    status::{rules::*, *},
};
use rusqlite::Connection;
use serde_json::{Map, Value};
use std::{
    fs,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use tempfile::TempDir;

struct Stopped;
impl HealthProbe for Stopped {
    fn probe(
        &self,
        _: &ProjectPaths,
        _: &Map<String, Value>,
    ) -> Result<Option<Map<String, Value>>, StatusError> {
        Ok(None)
    }
}
fn ctx(root: &Path) -> DiscoveryContext {
    DiscoveryContext {
        cwd: root.into(),
        forced_root: None,
        home: None,
    }
}
fn project() -> TempDir {
    let t = TempDir::new().unwrap();
    fs::create_dir(t.path().join(".ken")).unwrap();
    fs::write(t.path().join(".ken/meta.json"), r#"{"project_id":7}"#).unwrap();
    t
}
fn database(root: &Path) -> Connection {
    let c = Connection::open(root.join(".ken/ken.db")).unwrap();
    c.execute_batch(include_str!("../../../src/ken/schema.sql"))
        .unwrap();
    c
}
fn installed(root: &Path) -> InstalledStatus {
    match read_status(root, &ctx(root), &Stopped).unwrap() {
        StatusReport::Installed(s) => *s,
        other => panic!("{other:?}"),
    }
}
fn file(c: &Connection, path: &str, blob: Option<&[u8]>, slot: Option<i64>) {
    c.execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,embedding,vec_slot) VALUES(?1,x'00',1,1,?2,?3)",rusqlite::params![path,blob,slot]).unwrap();
}
#[test]
fn missing_database_is_not_created() {
    struct Never;
    impl HealthProbe for Never {
        fn probe(
            &self,
            _: &ProjectPaths,
            _: &Map<String, Value>,
        ) -> Result<Option<Map<String, Value>>, StatusError> {
            panic!("no DB must not probe health")
        }
    }
    let t = project();
    let result = read_status(t.path(), &ctx(t.path()), &Never).unwrap();
    let StatusReport::MetadataOnly(report) = result else {
        panic!("wrong variant")
    };
    assert_eq!(report.project_id, Value::from(7));
    assert!(!report.db.exists);
    assert_eq!(report.db.size, "missing");
    assert!(!t.path().join(".ken/ken.db").exists());
}
#[test]
fn all_fifteen_counts_include_inline_and_slots() {
    let t = project();
    let c = database(t.path());
    file(&c, "a", Some(b"v"), None);
    file(&c, "b", None, Some(0));
    file(&c, "c", None, None);
    c.execute_batch("INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,embedding) VALUES(1,'fn','f',1,1,x'01');
    INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,vec_slot) VALUES(2,'fn','g',1,1,0);
    INSERT INTO cr_sessions(id,started_at) VALUES(1,1); INSERT INTO cr_sessions(id,started_at,ended_at) VALUES(2,1,2);
    INSERT INTO cr_contexts(session_id,kind,content,iteration,embedding,created_at) VALUES(1,'user_prompt','p',1,x'01',1),(1,'tool_call','t',1,NULL,1);
    INSERT INTO cr_interactions(session_id,iteration,event_type,target_kind,created_at) VALUES(1,1,'read','file',1);
    INSERT INTO cr_session_scores(session_id,target_kind,score,pattern,created_at) VALUES(1,'file',1,'read',1);
    INSERT INTO cr_findings(topic,content,embedding,created_at,updated_at) VALUES('a','n',x'01',1,1),('b','n',NULL,1,1);
    INSERT INTO ci_intent_sources(source_kind,text,embedding,updated_at) VALUES('doc','a',x'01',1);
    INSERT INTO ci_intent_sources(source_kind,text,vec_slot,updated_at) VALUES('doc','b',0,1);").unwrap();
    let before = fs::read(t.path().join(".ken/ken.db")).unwrap();
    let s = installed(t.path());
    assert_eq!(
        s.counts,
        StatusCounts {
            files: 3,
            files_embedded: 2,
            symbols: 2,
            symbols_embedded: 2,
            sessions: 2,
            active_sessions: 1,
            contexts: 2,
            prompt_contexts: 1,
            prompt_contexts_embedded: 1,
            interactions: 1,
            session_scores: 1,
            findings: 2,
            findings_embedded: 1,
            intent_sources: 2,
            intent_sources_embedded: 2
        }
    );
    assert_eq!(s.rank_signals.predictive, "yes");
    assert_eq!(s.rank_signals.findings, "yes");
    assert_eq!(before, fs::read(t.path().join(".ken/ken.db")).unwrap());
    assert_eq!(rusqlite::version(), "3.53.2");
}
#[test]
fn counts_and_paths_share_one_snapshot() {
    let t = project();
    let c = database(t.path());
    c.execute_batch("PRAGMA journal_mode=WAL").unwrap();
    drop(c);
    let path = t.path().join(".ken/ken.db");
    let stop = Arc::new(AtomicBool::new(false));
    let signal = stop.clone();
    let writer = std::thread::spawn(move || {
        let mut c = Connection::open(path).unwrap();
        while !signal.load(Ordering::Relaxed) {
            let tx = c.transaction().unwrap();
            tx.execute("DELETE FROM ci_files", []).unwrap();
            for i in 0..7 {
                file(&tx, &format!("missing{i}"), None, None);
            }
            tx.commit().unwrap();
        }
    });
    for _ in 0..50 {
        let s = installed(t.path());
        assert_eq!(s.counts.files, s.index_health.stale_files);
        assert_eq!(s.index_health.sample.len(), s.counts.files.min(5) as usize);
    }
    stop.store(true, Ordering::Relaxed);
    writer.join().unwrap();
}
#[test]
fn wal_commit_visible_without_checkpoint() {
    let t = project();
    let c = database(t.path());
    c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0")
        .unwrap();
    file(&c, "live", None, None);
    fs::write(t.path().join("live"), "code").unwrap();
    let path = t.path().join(".ken/ken.db");
    let before = fs::read(&path).unwrap();
    let meta = fs::read(t.path().join(".ken/meta.json")).unwrap();
    let s = installed(t.path());
    assert_eq!(s.counts.files, 1);
    assert_eq!(s.index_health.stale_files, 0);
    assert_eq!(before, fs::read(path).unwrap());
    assert_eq!(meta, fs::read(t.path().join(".ken/meta.json")).unwrap());
    assert_eq!(
        c.query_row("SELECT count(*) FROM ci_files", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        1
    );
}

#[cfg(unix)]
#[test]
fn readonly_directory_does_not_need_write_access() {
    use std::os::unix::fs::PermissionsExt;
    let t = project();
    drop(database(t.path()));
    let directory = t.path().join(".ken");
    let db = directory.join("ken.db");
    let before = fs::read(&db).unwrap();
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o555)).unwrap();
    let report = read_status(t.path(), &ctx(t.path()), &Stopped);
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(matches!(report.unwrap(), StatusReport::Installed(_)));
    assert_eq!(before, fs::read(&db).unwrap());
    assert_eq!(fs::read_dir(directory).unwrap().count(), 2);
}
#[test]
fn corrupt_or_old_incompatible_schema_fails() {
    let t = project();
    fs::write(t.path().join(".ken/ken.db"), b"not sqlite").unwrap();
    assert!(read_status(t.path(), &ctx(t.path()), &Stopped).is_err());
    fs::remove_file(t.path().join(".ken/ken.db")).unwrap();
    let c = database(t.path());
    c.execute("DROP TABLE ci_symbols", []).unwrap();
    assert!(read_status(t.path(), &ctx(t.path()), &Stopped).is_err());
    for meta in ["{", "[]", "{}"] {
        fs::write(t.path().join(".ken/meta.json"), meta).unwrap();
        assert!(read_status(t.path(), &ctx(t.path()), &Stopped).is_err());
    }
}
#[test]
fn rules_and_rounding_match_python() {
    for (n, want) in [
        (0, "0B"),
        (1023, "1023B"),
        (1024, "1KiB"),
        (1536, "2KiB"),
        (2560, "2KiB"),
        (1 << 20, "1MiB"),
        (1 << 30, "1GiB"),
        (1 << 40, "1TiB"),
    ] {
        assert_eq!(format_size(Some(n)), want);
    }
    assert_eq!(format_size(None), "missing");
    let mut c = StatusCounts::default();
    assert_eq!(embedding_coverage(&c).percent, 0.0);
    c.files = 80;
    c.files_embedded = 1;
    assert_eq!(embedding_coverage(&c).percent, 1.2);
    c.files = 160;
    assert_eq!(embedding_coverage(&c).percent, 0.6);
    let h = IndexHealth {
        stale_files: 7,
        sample: vec![],
    };
    c = StatusCounts::default();
    assert_eq!(
        recommendations(&c, &h),
        vec![
            "run `ken install .` or re-run it to populate the code index",
            "submit at least one prompt through a hooked agent to seed context history",
            "let hooks run through a few real turns to build predictive history",
            "save reusable project facts with `ken remember TOPIC CONTENT`"
        ]
    );
    c.files = 1;
    c.prompt_contexts_embedded = 1;
    c.active_sessions = 1;
    assert_eq!(
        recommendations(&c, &h),
        vec![
            "indexed files are missing on disk; run `ken install .` to resync after branch changes",
            "run `ken rank \"your task\"` once to lazily build embeddings",
            "verify tool hooks are recording reads/edits; no interactions have been captured",
            "end the active session to snapshot predictive scores",
            "save reusable project facts with `ken remember TOPIC CONTENT`"
        ]
    );
}
