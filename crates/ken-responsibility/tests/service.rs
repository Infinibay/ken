use ken_responsibility::{
    self as responsibility, Candidate, CurrentSources, IndexedCandidate, LiveScores, NativeSources,
    Preview, RankedRows, ResponsibilityVectors, Symbol, WhoRequest,
};
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/responsibility-domain.json")).unwrap()
}
fn hex(value: &str) -> Vec<u8> {
    (0..value.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).unwrap())
        .collect()
}
fn catalog() -> Arc<ken_syntax::GrammarCatalog> {
    Arc::new(
        ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    )
}
fn setup(root: &Path, case: &Value) -> Connection {
    std::fs::create_dir(root.join(".ken")).unwrap();
    let path = root.join(".ken/ken.db");
    let mut store = ken_store::ProjectDatabase::open(&path).unwrap();
    store.initialize().unwrap();
    drop(store);
    let db = Connection::open(path).unwrap();
    let mut files = BTreeMap::new();
    for (path, source) in case["request"]["files"].as_object().unwrap() {
        let file = root.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, source.as_str().unwrap()).unwrap();
        let hash = case["indexed"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["path"] == path.as_str())
            .unwrap()["content_hash"]
            .as_str()
            .unwrap();
        db.execute(
            "INSERT INTO ci_files(path,content_hash,mtime,indexed_at) VALUES(?,?,0,0)",
            params![path, hex(hash)],
        )
        .unwrap();
        files.insert(path.clone(), db.last_insert_rowid());
    }
    for (index, row) in case["indexed"].as_array().unwrap().iter().enumerate() {
        let fid = files[row["path"].as_str().unwrap()];
        let mut sid = None;
        if row["kind"] != "module" {
            let id = index as i64 + 1;
            db.execute("INSERT INTO ci_symbols(id,file_id,qualname,name,kind,line_start,line_end,docstring) VALUES(?,?,?,?,?,1,1,?)",params![id,fid,row["qualname"].as_str(),row["name"].as_str(),row["kind"].as_str(),row["docstring"].as_str()]).unwrap();
            sid = Some(id);
        }
        if let Some(embedding) = row["embedding"].as_array() {
            let blob = embedding
                .iter()
                .flat_map(|v| (v.as_f64().unwrap() as f32).to_le_bytes())
                .collect::<Vec<_>>();
            db.execute("INSERT INTO ci_intent_sources(file_id,symbol_id,source_kind,text,embedding,vec_slot,updated_at) VALUES(?,?,?,?,?,?,0)",params![fid,sid,if sid.is_some(){"symbol_docstring"}else{"module_docstring"},row["docstring"].as_str(),blob,row["vec_slot"].as_i64()]).unwrap();
        }
    }
    for (path, source) in case["request"]["current"].as_object().into_iter().flatten() {
        std::fs::write(root.join(path), source.as_str().unwrap()).unwrap();
    }
    db
}
struct ControlledVectors {
    forms: Vec<String>,
    passages: Vec<String>,
    live: Option<LiveScores>,
}
impl ControlledVectors {
    fn new(request: &WhoRequest) -> Self {
        let mut forms = vec![request.question.trim().to_owned()];
        for form in &request.hypotheses {
            let form = form.trim().to_owned();
            if !forms.contains(&form) {
                forms.push(form);
            }
        }
        Self {
            forms,
            passages: Vec::new(),
            live: None,
        }
    }
}
impl ResponsibilityVectors for ControlledVectors {
    fn embed_query(&mut self, text: &str) -> responsibility::Result<Vec<f32>> {
        let mut q = vec![0.; 4];
        q[self.forms.iter().position(|f| f == text).unwrap()] = 1.;
        Ok(q)
    }
    fn embed_passages(&mut self, texts: &[String]) -> responsibility::Result<Vec<Vec<f32>>> {
        self.passages.extend_from_slice(texts);
        Ok(texts
            .iter()
            .map(|text| {
                let doc = text.split_once(" — ").unwrap().1;
                let mut row = self
                    .forms
                    .iter()
                    .map(|f| {
                        if responsibility::reasoners::overlap(
                            &responsibility::reasoners::terms(f),
                            doc,
                        ) > 0.
                        {
                            0.8
                        } else {
                            0.
                        }
                    })
                    .collect::<Vec<_>>();
                row.resize(4, 0.);
                row
            })
            .collect())
    }
    fn live_scores(
        &mut self,
        _: &Connection,
        _: &Path,
        _: &[f32],
    ) -> responsibility::Result<Option<LiveScores>> {
        Ok(self.live.clone())
    }
    fn rank_against(
        &mut self,
        query: &[f32],
        blobs: &[Vec<u8>],
    ) -> responsibility::Result<RankedRows> {
        let column = query.iter().position(|v| *v == 1.).unwrap();
        let mut out = RankedRows {
            kept: Vec::new(),
            scores: Vec::new(),
        };
        for (i, b) in blobs.iter().enumerate() {
            if b.len() / 4 == query.len() {
                out.kept.push(i);
                out.scores.push(f32::from_le_bytes(
                    b[column * 4..column * 4 + 4].try_into().unwrap(),
                ));
            }
        }
        Ok(out)
    }
    fn cosine(
        &mut self,
        query: &[f32],
        flat: &[f32],
        rows: usize,
        width: usize,
    ) -> responsibility::Result<Vec<f32>> {
        assert_eq!(flat.len(), rows * width);
        let column = query.iter().position(|v| *v == 1.).unwrap();
        Ok(flat.chunks_exact(width).map(|r| r[column]).collect())
    }
}
struct FailingPreview(NativeSources);
impl CurrentSources for FailingPreview {
    fn resolve(&mut self, row: &IndexedCandidate) -> responsibility::Result<Symbol> {
        self.0.resolve(row)
    }
    fn preview(&mut self, _: &Candidate) -> responsibility::Result<Preview> {
        Err(responsibility::Error::Invalid(
            "Preview unavailable; read this symbol directly.".into(),
        ))
    }
}
#[test]
fn native_sqlite_current_sources_and_controlled_vectors_match_original_service() {
    let f = fixture();
    for case in f["service"].as_array().unwrap() {
        let d = tempfile::tempdir().unwrap();
        let db = setup(d.path(), case);
        let request = WhoRequest {
            question: case["request"]["question"].as_str().unwrap().into(),
            path: case["request"]["path"].as_str().unwrap_or(".").into(),
            hypotheses: case["request"]["hypotheses"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|v| v.as_str().unwrap().to_owned())
                .collect(),
            limit: case["request"]["limit"].as_i64().unwrap_or(3),
            include_tests: case["request"]["include_tests"].as_bool().unwrap_or(false),
        };
        let mut vectors = ControlledVectors::new(&request);
        let native = NativeSources::new(d.path(), catalog()).unwrap();
        let mut sources: Box<dyn CurrentSources> = if case["request"]["preview_failure"] == true {
            Box::new(FailingPreview(native))
        } else {
            Box::new(native)
        };
        let actual = responsibility::who_with(
            &db,
            d.path(),
            &request,
            &mut vectors,
            sources.as_mut(),
            &responsibility::default_reasoners(),
        )
        .unwrap();
        assert_eq!(
            actual.to_json().unwrap(),
            case["result"],
            "{}",
            case["request"]["id"]
        );
        assert_eq!(json!(vectors.passages), case["passages"]);
    }
}
#[test]
fn invalid_requests_are_rejected_before_model_or_source_access() {
    let d = tempfile::tempdir().unwrap();
    let db = Connection::open_in_memory().unwrap();
    let mut sources = NativeSources::new(d.path(), catalog()).unwrap();
    for request in [
        WhoRequest {
            question: "".into(),
            ..Default::default()
        },
        WhoRequest {
            question: "a".into(),
            limit: 0,
            ..Default::default()
        },
        WhoRequest {
            question: "a".into(),
            path: "..".into(),
            ..Default::default()
        },
        WhoRequest {
            question: "a".into(),
            hypotheses: vec!["a".into(); 4],
            ..Default::default()
        },
    ] {
        let mut vectors = ControlledVectors::new(&request);
        assert!(
            responsibility::who_with(
                &db,
                d.path(),
                &request,
                &mut vectors,
                &mut sources,
                &responsibility::default_reasoners()
            )
            .is_err()
        );
    }
}
#[test]
fn vector_slot_precedence_and_stale_inline_dimensions_remain_policy_decisions() {
    let d = tempfile::tempdir().unwrap();
    let case = &fixture()["service"][0];
    let db = setup(d.path(), case);
    let request = WhoRequest {
        question: "Store findings".into(),
        ..Default::default()
    };
    let mut vectors = ControlledVectors::new(&request);
    vectors.live = Some(LiveScores {
        slots: vec![0],
        scores: vec![0.1],
    });
    let scores = responsibility::retrieval::similarities(
        &db,
        d.path(),
        &[
            IndexedCandidate {
                path: "a.py".into(),
                qualname: "a".into(),
                kind: "function".into(),
                vec_slot: Some(0),
                embedding: Some([0.9f32.to_le_bytes(); 4].concat()),
                ..Default::default()
            },
            IndexedCandidate {
                path: "b.py".into(),
                qualname: "b".into(),
                kind: "function".into(),
                embedding: Some([0.8f32.to_le_bytes(); 4].concat()),
                ..Default::default()
            },
            IndexedCandidate {
                path: "c.py".into(),
                qualname: "c".into(),
                kind: "function".into(),
                embedding: Some([0.9f32.to_le_bytes(); 2].concat()),
                ..Default::default()
            },
        ],
        &[vec![1., 0., 0., 0.]],
        &mut vectors,
    )
    .unwrap();
    assert_eq!(scores[0].get(&0), Some(&0.1f32));
    assert_eq!(scores[0].get(&1), Some(&0.8f32));
    assert!(!scores[0].contains_key(&2));
}

#[test]
fn repeated_requests_refresh_documentation_while_each_request_quotes_one_snapshot() {
    let d = tempfile::tempdir().unwrap();
    let f = fixture();
    let case = &f["service"][0];
    let db = setup(d.path(), case);
    let request = WhoRequest {
        question: "Store reusable findings".into(),
        ..Default::default()
    };
    let mut sources = NativeSources::new(d.path(), catalog()).unwrap();
    let mut vectors = ControlledVectors::new(&request);
    let first = responsibility::who_with(
        &db,
        d.path(),
        &request,
        &mut vectors,
        &mut sources,
        &responsibility::default_reasoners(),
    )
    .unwrap()
    .to_json()
    .unwrap();
    assert_eq!(first["candidates"][0]["symbol"], "perform");
    std::fs::write(d.path().join("store.py"),"def perform():\n    \"\"\"Does not store reusable findings.\"\"\"\n    raise NotImplementedError\n").unwrap();
    let second = responsibility::who_with(
        &db,
        d.path(),
        &request,
        &mut vectors,
        &mut sources,
        &responsibility::default_reasoners(),
    )
    .unwrap()
    .to_json()
    .unwrap();
    assert!(second["candidates"].as_array().unwrap().is_empty());
    assert_eq!(
        second["counterevidence"][0]["source"]["index_changed"],
        true
    );
    assert!(
        second["counterevidence"][0]["snippets"]
            .to_string()
            .contains("NotImplementedError")
    );
}

#[test]
fn shared_native_live_store_bridge_preserves_segments_and_free_slot_filtering() {
    let d = tempfile::tempdir().unwrap();
    let db = Connection::open_in_memory().unwrap();
    db.execute_batch("CREATE TABLE ci_vec_alloc(space TEXT PRIMARY KEY,next_slot INTEGER);CREATE TABLE ci_vec_free(space TEXT,slot INTEGER);INSERT INTO ci_vec_alloc VALUES('ci_intent_sources',3);INSERT INTO ci_vec_free VALUES('ci_intent_sources',1);").unwrap();
    let directory = d.path().join(".ken/vectors");
    std::fs::create_dir_all(&directory).unwrap();
    let space = ken_store::VectorSpace::IntentSources;
    let initial = ken_store::VectorStore::open(&directory, space, 2, None).unwrap();
    drop(initial);
    let manifest = directory.join("ci_intent_sources.json");
    let mut definition: Value = serde_json::from_slice(&std::fs::read(&manifest).unwrap()).unwrap();
    definition["segment_rows"] = json!(2);
    std::fs::write(&manifest, serde_json::to_vec(&definition).unwrap()).unwrap();
    let store = ken_store::VectorStore::open(&directory, space, 2, None).unwrap();
    store
        .write(
            &[0, 1, 2],
            &[vec![1., 0.], vec![-1., 0.], vec![0., 1.]],
            true,
        )
        .unwrap();
    let math = ken_retrieval::vector_math::NativeVectorMath::platform().unwrap();
    let scores = ken_retrieval::vector_store::live_store_scores(
        &db,
        Some(d.path()),
        space,
        &[1., 0.],
        &math,
    )
    .unwrap()
    .unwrap();
    assert_eq!(scores.slots, vec![0, 2]);
    assert_eq!(scores.scores, vec![1., 0.]);
    assert!(
        ken_retrieval::vector_store::live_store_scores(&db, None, space, &[1., 0.], &math)
            .unwrap()
            .is_none()
    );
}
