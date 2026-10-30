use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_maintenance::{MaintenanceApplication, PROBE_TEXT, ReembedEvent, ReembedOptions};
use ken_retrieval::{DocumentEncoder, query_encoder::QueryEncoder};
use ken_store::{ProjectStore, VectorSpace};
use ken_text::PythonText;
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    io::Read,
    path::Path,
};
fn reference() -> Value {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(&include_bytes!("fixtures/maintenance-reference.json.gz")[..])
        .read_to_string(&mut raw)
        .unwrap();
    serde_json::from_str(&raw).unwrap()
}
fn paths(root: &Path) -> ProjectPaths {
    ProjectPaths::at(
        root,
        &DiscoveryContext {
            cwd: root.into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap()
}
fn fixture() -> (tempfile::TempDir, ProjectPaths) {
    let root = tempfile::tempdir().unwrap();
    let p = paths(root.path());
    let mut project = ProjectStore::open(&p).unwrap();
    project.initialize().unwrap();
    let c = project.database().connection();
    let blob = vec![0u8; 8];
    c.execute("INSERT INTO ci_files(id,path,language,content_hash,mtime,indexed_at,embedding)VALUES(1,'src/a.py','python',x'',0,0,?)",[&blob]).unwrap();
    c.execute("INSERT INTO ci_symbols(id,file_id,kind,name,qualname,line_start,line_end,docstring,embedding)VALUES(1,1,'function','go','go',1,2,'  does things  ',?)",[&blob]).unwrap();
    c.execute("INSERT INTO ci_intent_sources(id,file_id,source_kind,text,embedding,updated_at)VALUES(1,1,'module_docstring','  two\\n words ',?,0)",[&blob]).unwrap();
    c.execute(
        "INSERT INTO cr_sessions(id,agent_id,started_at)VALUES(1,'agent',0)",
        [],
    )
    .unwrap();
    c.execute("INSERT INTO cr_contexts(id,session_id,kind,content,iteration,embedding,created_at)VALUES(1,1,'user_prompt','fix the thing',0,?,0)",[&blob]).unwrap();
    c.execute("INSERT INTO cr_findings(id,topic,content,tags,embedding,created_at,updated_at)VALUES(1,'topic','a useful finding','[]',?,0,0)",[&blob]).unwrap();
    (root, p)
}
struct Encoder {
    dim: usize,
    calls: RefCell<Vec<Value>>,
    fail: Cell<bool>,
    action: RefCell<Option<Box<dyn Fn()>>>,
}
impl Encoder {
    fn new(dim: usize) -> Self {
        Self {
            dim,
            calls: RefCell::new(vec![]),
            fail: Cell::new(false),
            action: RefCell::new(None),
        }
    }
    fn vector(&self, query: bool) -> Vec<f32> {
        let mut v = vec![0.; self.dim];
        if query {
            v[self.dim - 1] = 2.;
        } else {
            v[0] = 3.;
            v[self.dim - 1] = 4.;
        }
        v
    }
}
impl DocumentEncoder for Encoder {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        Ok(self.dim)
    }
    fn token_count(&self, t: &str) -> ken_retrieval::Result<usize> {
        Ok(t.len())
    }
    fn embed_passages(&self, t: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        if self.fail.get() {
            return Err(ken_retrieval::RetrievalError::Invalid(
                "injected encoder failure".into(),
            ));
        }
        if let Some(action) = self.action.borrow_mut().take() {
            action();
        }
        for t in t {
            self.calls.borrow_mut().push(json!(["passage", t]));
        }
        Ok(t.iter().map(|_| self.vector(false)).collect())
    }
}
impl QueryEncoder for Encoder {
    fn embed_query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        if self.fail.get() {
            return Err(ken_retrieval::RetrievalError::Invalid(
                "injected query failure".into(),
            ));
        }
        self.calls.borrow_mut().push(json!(["query", t]));
        Ok(self.vector(true))
    }
}
#[test]
fn actual_all_space_reencode_matches_original_text_roles_probe_and_counts() {
    let (root, p) = fixture();
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let encoder = Encoder::new(2);
    let report = app
        .reembed(
            "provided/model",
            &encoder,
            &encoder,
            &ReembedOptions {
                now_ms: 123,
                ..Default::default()
            },
            &mut |_| {},
        )
        .unwrap();
    let probe = app.validate_embeddings("provided/model", &encoder).unwrap();
    let expected = reference();
    assert_eq!(
        serde_json::to_value(report).unwrap(),
        expected["reembed"]["counts"]
    );
    assert_eq!(
        serde_json::to_value(probe).unwrap(),
        expected["reembed"]["probe"]
    );
    assert_eq!(
        *encoder.calls.borrow(),
        expected["reembed"]["calls"].as_array().unwrap().clone()
    );
    drop(app);
    let project = ProjectStore::open(&p).unwrap();
    let c = project.database().connection();
    for space in VectorSpace::ALL {
        let state: (bool, bool) = c
            .query_row(
                &format!("SELECT embedding IS NOT NULL,vec_slot IS NOT NULL FROM {space}"),
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(state, (false, true));
        let v = project
            .vectors(space, 2, Some("provided/model"))
            .unwrap()
            .read(&[0])
            .unwrap();
        assert!((v[0][0] - 0.6).abs() < 1e-6);
    }
    assert_eq!(
        project
            .database()
            .get_meta("embed_probe_text")
            .unwrap()
            .as_deref(),
        Some(PROBE_TEXT)
    );
    assert_eq!(
        project
            .database()
            .get_meta("embed_doc_space")
            .unwrap()
            .as_deref(),
        Some("2")
    );
    assert!(
        project
            .database()
            .get_meta("reembed_in_progress")
            .unwrap()
            .is_none()
    );
}
#[test]
fn repeated_model_and_dimension_changes_keep_slot_only_eligibility_and_inline_roles() {
    let (root, p) = fixture();
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    for (model, dim) in [("first", 2), ("second", 2), ("wide", 4)] {
        let enc = Encoder::new(dim);
        let report = app
            .reembed(model, &enc, &enc, &ReembedOptions::default(), &mut |_| {})
            .unwrap();
        assert_eq!(
            (
                report.files,
                report.symbols,
                report.intent,
                report.prompts,
                report.findings
            ),
            (1, 1, 1, 1, 1)
        );
        drop(app);
        let project = ProjectStore::open(&p).unwrap();
        for space in VectorSpace::ALL {
            let slot: i64 = project
                .database()
                .connection()
                .query_row(&format!("SELECT vec_slot FROM {space}"), [], |r| r.get(0))
                .unwrap();
            assert_eq!(slot, 0);
            assert_eq!(
                project
                    .vectors(space, dim, Some(model))
                    .unwrap()
                    .read(&[slot])
                    .unwrap()[0]
                    .len(),
                dim
            );
        }
        let prompt: Vec<u8> = project
            .database()
            .connection()
            .query_row("SELECT embedding FROM cr_contexts", [], |r| r.get(0))
            .unwrap();
        assert_eq!(prompt.len(), dim * 4);
        assert_eq!(
            f32::from_le_bytes(prompt[prompt.len() - 4..].try_into().unwrap()),
            2.
        );
        drop(project);
        app = MaintenanceApplication::open(root.path()).unwrap();
    }
}
#[test]
fn failed_encoding_and_ready_publication_abort_leave_old_vectors_and_metadata_recoverable() {
    let (root, p) = fixture();
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let good = Encoder::new(2);
    app.reembed("old", &good, &good, &Default::default(), &mut |_| {})
        .unwrap();
    for crash in [false, true] {
        let fail = Encoder::new(4);
        fail.fail.set(!crash);
        let run = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            app.reembed("new", &fail, &fail, &Default::default(), &mut |event| {
                if crash && matches!(event, ReembedEvent::ReadyToPublish) {
                    panic!("injected publication interruption")
                }
            })
        }));
        assert!(run.is_err() || run.unwrap().is_err());
        drop(app);
        let project = ProjectStore::open(&p).unwrap();
        assert_eq!(
            project
                .database()
                .get_meta("embed_model")
                .unwrap()
                .as_deref(),
            Some("old")
        );
        assert!(
            project
                .database()
                .get_meta("reembed_in_progress")
                .unwrap()
                .is_some()
        );
        assert_eq!(
            project
                .vectors(VectorSpace::Symbols, 2, Some("old"))
                .unwrap()
                .read(&[0])
                .unwrap()[0]
                .len(),
            2
        );
        drop(project);
        app = MaintenanceApplication::open(root.path()).unwrap();
    }
    let encoder = Encoder::new(4);
    assert_eq!(
        app.reembed("new", &encoder, &encoder, &Default::default(), &mut |_| {})
            .unwrap()
            .symbols,
        1
    );
}
#[test]
fn source_row_mutation_while_encoding_aborts_publication_without_losing_new_source() {
    let (root, p) = fixture();
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let old = Encoder::new(2);
    app.reembed("old", &old, &old, &Default::default(), &mut |_| {})
        .unwrap();
    let new = Encoder::new(4);
    let db = p.db();
    *new.action.borrow_mut() = Some(Box::new(move || {
        let conn = rusqlite::Connection::open(&db).unwrap();
        conn.execute(
            "UPDATE ci_symbols SET docstring='newer source' WHERE id=1",
            [],
        )
        .unwrap();
    }));
    assert!(
        app.reembed("new", &new, &new, &Default::default(), &mut |_| {})
            .is_err()
    );
    drop(app);
    let project = ProjectStore::open(&p).unwrap();
    assert_eq!(
        project
            .database()
            .get_meta("embed_model")
            .unwrap()
            .as_deref(),
        Some("old")
    );
    let doc: String = project
        .database()
        .connection()
        .query_row("SELECT docstring FROM ci_symbols", [], |r| r.get(0))
        .unwrap();
    assert_eq!(doc, "newer source");
}
#[test]
fn probe_is_readonly_and_detects_missing_width_and_same_name_drift() {
    let (root, p) = fixture();
    let mut app = MaintenanceApplication::open(root.path()).unwrap();
    let encoder = Encoder::new(2);
    assert!(!app.validate_embeddings("same", &encoder).unwrap().ok);
    app.reembed("same", &encoder, &encoder, &Default::default(), &mut |_| {})
        .unwrap();
    assert!(
        !app.validate_embeddings("same", &Encoder::new(4))
            .unwrap()
            .ok
    );
    struct Drift;
    impl QueryEncoder for Drift {
        fn embed_query(&self, _: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
            Ok(vec![2., 0.])
        }
    }
    assert!(!app.validate_embeddings("same", &Drift).unwrap().ok);
    drop(app);
    let project = ProjectStore::open(&p).unwrap();
    assert_eq!(
        project
            .database()
            .get_meta("embed_model")
            .unwrap()
            .as_deref(),
        Some("same")
    );
    assert!(
        project
            .database()
            .get_meta("reembed_in_progress")
            .unwrap()
            .is_none()
    );
}
