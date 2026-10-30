//! Compatibility paths use controlled vectors, not accepted model replays.
use ken_application::search_compat::{CompatibilityModels, EvidenceResponse, SearchCompatibility};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    DocumentEncoder, EntityKey, Passage, PassageFields, PassagePolicy, Result, Span,
    encoder::EncoderLoader,
    projections::index_embeddings,
    query::{SearchOptions, SearchRequest},
    ranking::RelevanceJudge,
    storage::replace_file_passages,
};
use ken_store::{ProjectDatabase, VectorSpace, VectorStore};
use ken_text::PythonText;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    rc::Rc,
};

fn runtime() -> LegacyRuntimeIdentity {
    let v: Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/linux.json"
    ))
    .unwrap();
    LegacyRuntimeIdentity::from_json(&v["legacy_runtime"].to_string()).unwrap()
}
#[derive(Default)]
struct Models {
    calls: RefCell<Vec<String>>,
    judges: Cell<usize>,
}
impl CompatibilityModels for Models {
    fn legacy_query(&self, _: &Connection, query: &PythonText) -> Result<Vec<f32>> {
        self.calls
            .borrow_mut()
            .push(format!("legacy:{}", query.to_utf8().unwrap()));
        Ok(vec![1., 0.])
    }
    fn profile_query(
        &self,
        spec: &EncoderSpec,
        _: &LegacyRuntimeIdentity,
        query: &PythonText,
    ) -> Result<Vec<f32>> {
        self.calls
            .borrow_mut()
            .push(format!("{}:{}", spec.model_id, query.to_utf8().unwrap()));
        Ok(vec![1., 0.])
    }
    fn joint_judge(
        &self,
        _: &EncoderSpec,
        _: &LegacyRuntimeIdentity,
    ) -> Result<Rc<dyn RelevanceJudge>> {
        self.judges.set(self.judges.get() + 1);
        Ok(Rc::new(Judge))
    }
}
struct Judge;
impl RelevanceJudge for Judge {
    fn score(&self, _: &PythonText, documents: &[PythonText], _: &str) -> Result<Vec<f64>> {
        Ok(documents
            .iter()
            .map(|d| {
                if d.to_utf8().unwrap().contains("beta") {
                    0.9
                } else {
                    0.1
                }
            })
            .collect())
    }
}
struct Fixture {
    temp: tempfile::TempDir,
    paths: ProjectPaths,
    db: ProjectDatabase,
    models: Rc<Models>,
}
impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        std::fs::create_dir(temp.path().join(".ken")).unwrap();
        let context = DiscoveryContext {
            cwd: temp.path().into(),
            forced_root: None,
            home: Some(temp.path().into()),
        };
        let paths = ProjectPaths::at(temp.path(), &context).unwrap();
        let mut db = ProjectDatabase::open(&paths.db()).unwrap();
        db.initialize().unwrap();
        Self {
            temp,
            paths,
            db,
            models: Rc::new(Models::default()),
        }
    }
    fn owner(&self) -> SearchCompatibility {
        SearchCompatibility::new(self.models.clone(), runtime())
    }
    fn file(&self, path: &str, vector: Option<&[f32]>) -> i64 {
        std::fs::write(
            self.temp.path().join(path),
            "def alpha():\n    return 1\n\ndef beta():\n    return 2\n",
        )
        .unwrap();
        self.db.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,language,embedding)VALUES(?1,x'00',0,0,'python',?2)",params![path,vector.map(blob)]).unwrap();
        self.db.connection().last_insert_rowid()
    }
    fn symbol(&self, file: i64, name: &str, qualname: &str, line: i64, vector: Option<&[f32]>) {
        self.db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring,embedding)VALUES(?1,'function',?2,?3,?4,?5,' original documentation ',?6)",params![file,name,qualname,line,line+1,vector.map(blob)]).unwrap();
    }
}
fn blob(v: &[f32]) -> Vec<u8> {
    v.iter().flat_map(|f| f.to_le_bytes()).collect()
}
fn value<T: serde::Serialize>(v: T) -> Value {
    serde_json::to_value(v).unwrap()
}
fn legacy(f: &Fixture, query: &str, scope: &str, limit: isize) -> Value {
    value(
        f.owner()
            .legacy(
                f.db.connection(),
                Some(f.paths.root()),
                &query.into(),
                scope,
                limit,
            )
            .unwrap(),
    )
}
#[test]
fn legacy_exact_file_promotion_keeps_cosine_and_original_outline_shape() {
    let f = Fixture::new();
    let noisy = f.file("noise.py", Some(&[1., 0.]));
    f.symbol(noisy, "noise", "noise", 1, None);
    let exact = f.file("target.py", Some(&[0., 1.]));
    f.symbol(exact, "target", "target", 4, None);
    let hits = legacy(&f, "target", "files", 10);
    assert_eq!(
        hits,
        json!([
            {"path":"target.py","language":"python","score":0.0,"match":"exact","symbols":[{"kind":"function","name":"target","line":4}]},
            {"path":"noise.py","language":"python","score":1.0,"symbols":[{"kind":"function","name":"noise","line":1}]}
        ])
    );
    let rendered = f
        .owner()
        .legacy(
            f.db.connection(),
            Some(f.paths.root()),
            &"target".into(),
            "files",
            1,
        )
        .unwrap()
        .render();
    assert!(rendered.contains("0.000  target.py  (python)"));
    assert!(rendered.contains("function target:4"));
    assert_eq!(
        f.models.calls.borrow().as_slice(),
        ["legacy:target", "legacy:target"]
    );
}
#[test]
fn legacy_exact_symbols_without_vectors_are_injected_and_keep_null_scores() {
    let f = Fixture::new();
    let a = f.file("a.py", None);
    let b = f.file("b.py", None);
    f.symbol(a, "other", "other", 1, Some(&[1., 0.]));
    f.symbol(a, "target", "Target.target", 4, None);
    f.symbol(b, "target", "target", 1, None);
    let hits = legacy(&f, "target", "symbols", 10);
    assert_eq!(hits[0]["qualname"], "Target.target");
    assert_eq!(hits[0]["match"], "exact");
    assert_eq!(hits[0]["score"], Value::Null);
    assert_eq!(hits[1]["qualname"], "target");
    assert_eq!(hits[1]["score"], Value::Null);
    assert_eq!(hits[2]["score"], 1.0);
    assert_eq!(hits[0]["file"], "a.py");
    assert_eq!(hits[0]["line"], 4);
    assert_eq!(hits[0]["line_end"], 5);
    assert_eq!(hits[0]["docstring"], " original documentation ");
    assert!(
        f.owner()
            .legacy(
                f.db.connection(),
                Some(f.paths.root()),
                &"target".into(),
                "symbols",
                1
            )
            .unwrap()
            .render()
            .contains("n/a")
    );
}
#[test]
fn legacy_partial_rrf_preserves_semantic_order_and_plain_queries_have_no_literal_label() {
    let f = Fixture::new();
    let a = f.file("a.py", None);
    f.symbol(a, "unrelated", "unrelated", 1, Some(&[1., 0.]));
    f.symbol(a, "call", "Client.call", 2, Some(&[0.8, 0.6]));
    f.symbol(a, "call_async", "call_async", 3, Some(&[0., 1.]));
    let hits = legacy(&f, "call", "symbols", 10);
    assert_eq!(
        hits.as_array()
            .unwrap()
            .iter()
            .map(|r| r["qualname"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["Client.call", "call_async", "unrelated"]
    );
    assert_eq!(hits[0]["match"], "exact"); // s.name is exact even when qualname is qualified.
    assert_eq!(hits[1]["match"], "tokens");
    assert!(hits[2].get("match").is_none());
    let plain = legacy(&f, "find call", "symbols", 0);
    assert_eq!(plain.as_array().unwrap().len(), 1);
    assert_eq!(plain[0]["qualname"], "unrelated");
    assert!(plain[0].get("match").is_none());
}
#[test]
fn legacy_qualified_and_token_tiers_fuse_without_replacing_cosine_scores() {
    let f = Fixture::new();
    let a = f.file("a.py", None);
    for (name, qualified, line, vector) in [
        ("unrelated", "unrelated", 1, [1., 0.]),
        ("call", "Outer.Client.call", 2, [0.8, 0.6]),
        ("Client_call", "Client_call", 3, [0.6, 0.8]),
        ("call", "Client.call", 4, [0., 1.]),
    ] {
        f.symbol(a, name, qualified, line, Some(&vector));
    }
    let hits = legacy(&f, "Client.call", "symbols", 10);
    assert_eq!(
        hits.as_array()
            .unwrap()
            .iter()
            .map(|r| r["qualname"].as_str().unwrap())
            .collect::<Vec<_>>(),
        [
            "Client.call",
            "Outer.Client.call",
            "Client_call",
            "unrelated"
        ]
    );
    assert_eq!(hits[0]["match"], "exact");
    assert_eq!(hits[0]["score"], 0.0);
    assert_eq!(hits[1]["match"], "qualified");
    assert_eq!(hits[1]["score"], 0.8);
    assert_eq!(hits[2]["match"], "tokens");
    assert_eq!(hits[2]["score"], 0.6);
}
#[test]
fn legacy_live_filter_precedes_inline_dimension_check_but_stale_live_vectors_still_error() {
    let f = Fixture::new();
    f.file("gone.py", Some(&[1., 0., 0.]));
    std::fs::remove_file(f.paths.root().join("gone.py")).unwrap();
    f.file("live.py", Some(&[1., 0.]));
    assert_eq!(
        legacy(&f, "semantic question", "files", 10)
            .as_array()
            .unwrap()
            .len(),
        1
    );
    f.db.connection()
        .execute(
            "UPDATE ci_files SET embedding=? WHERE path='live.py'",
            [blob(&[1., 0., 0.])],
        )
        .unwrap();
    let error = f
        .owner()
        .legacy(
            f.db.connection(),
            Some(f.paths.root()),
            &"semantic question".into(),
            "files",
            10,
        )
        .unwrap_err()
        .to_string();
    assert!(error.contains("reembed"), "{error}");
}
#[test]
fn legacy_mapped_top512_pool_precedes_file_literal_promotion_and_symbol_exact_injection() {
    let mut f = Fixture::new();
    let mut tx = f.db.immediate().unwrap();
    let slots = ken_store::allocate(&mut tx, VectorSpace::Files, 513).unwrap();
    tx.commit().unwrap();
    let store = VectorStore::open(&f.paths.vectors(), VectorSpace::Files, 2, None).unwrap();
    let rows = (0..513)
        .map(|i| if i == 512 { vec![0., 1.] } else { vec![1., 0.] })
        .collect::<Vec<_>>();
    store.write(&slots, &rows, true).unwrap();
    for (i, &slot) in slots.iter().enumerate() {
        let path = if i == 512 {
            "target.py".into()
        } else {
            format!("f{i}.py")
        };
        let id = f.file(&path, None);
        f.db.connection()
            .execute(
                "UPDATE ci_files SET vec_slot=? WHERE id=?",
                params![slot, id],
            )
            .unwrap();
    }
    let hits = legacy(&f, "target", "files", 600);
    assert_eq!(hits.as_array().unwrap().len(), 512);
    assert!(
        hits.as_array()
            .unwrap()
            .iter()
            .all(|r| r["path"] != "target.py")
    );
    let exact_id: i64 =
        f.db.connection()
            .query_row("SELECT id FROM ci_files WHERE path='target.py'", [], |r| {
                r.get(0)
            })
            .unwrap();
    f.symbol(exact_id, "target", "target", 1, None);
    let symbols = legacy(&f, "target", "symbols", 600);
    assert_eq!(symbols.as_array().unwrap().len(), 1);
    assert_eq!(symbols[0]["match"], "exact");
    assert_eq!(symbols[0]["score"], Value::Null);
}
#[test]
fn legacy_infers_mapped_directory_without_enabling_optional_live_path_filter() {
    let mut f = Fixture::new();
    let file = f.file("gone.py", Some(&[0., 1.]));
    let mut tx = f.db.immediate().unwrap();
    let slots = ken_store::allocate(&mut tx, VectorSpace::Files, 1).unwrap();
    tx.commit().unwrap();
    VectorStore::open(&f.paths.vectors(), VectorSpace::Files, 2, None)
        .unwrap()
        .write(&slots, &[vec![1., 0.]], true)
        .unwrap();
    f.db.connection()
        .execute(
            "UPDATE ci_files SET vec_slot=? WHERE id=?",
            params![slots[0], file],
        )
        .unwrap();
    std::fs::remove_file(f.paths.root().join("gone.py")).unwrap();
    let hits = value(
        f.owner()
            .legacy(
                f.db.connection(),
                None,
                &"semantic question".into(),
                "files",
                10,
            )
            .unwrap(),
    );
    assert_eq!(hits[0]["path"], "gone.py");
    assert_eq!(hits[0]["score"], 1.0);
    assert_eq!(legacy(&f, "semantic question", "files", 10), json!([]));
}
#[test]
fn legacy_empty_live_slot_result_does_not_fall_back_to_inline_embeddings() {
    let mut f = Fixture::new();
    f.file("live.py", Some(&[1., 0.]));
    let mut tx = f.db.immediate().unwrap();
    let slots = ken_store::allocate(&mut tx, VectorSpace::Files, 1).unwrap();
    tx.commit().unwrap();
    VectorStore::open(&f.paths.vectors(), VectorSpace::Files, 2, None)
        .unwrap()
        .write(&slots, &[vec![0., 1.]], true)
        .unwrap();
    f.db.connection()
        .execute(
            "INSERT INTO ci_vec_free(space,slot)VALUES('ci_files',?)",
            [slots[0]],
        )
        .unwrap();
    assert_eq!(legacy(&f, "semantic question", "files", 10), json!([]));
}
#[test]
fn legacy_declines_nonfinite_file_vectors_with_an_error_instead_of_forging_json_null() {
    let f = Fixture::new();
    f.file("invalid.py", Some(&[f32::NAN, 0.]));
    let error = f
        .owner()
        .legacy(
            f.db.connection(),
            Some(f.paths.root()),
            &"semantic question".into(),
            "files",
            10,
        )
        .unwrap_err()
        .to_string();
    assert!(error.contains("finite"), "{error}");
}
struct Docs;
impl DocumentEncoder for Docs {
    fn dim(&self) -> Result<usize> {
        Ok(2)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        Ok(text.split_whitespace().count())
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        Ok(texts
            .iter()
            .map(|s| {
                if s.contains("beta") {
                    vec![0.6, 0.8]
                } else {
                    vec![1., 0.]
                }
            })
            .collect())
    }
}
struct Loader;
impl EncoderLoader for Loader {
    fn load(&self, _: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
        Ok(Rc::new(Docs))
    }
}
fn profile(extra: Value) -> RetrievalProfile {
    let spec = json!({"model_id":"test/compat","revision":"a".repeat(40),"backend":"provided"});
    let mut p = json!({"identity":spec,"behavior":spec});
    for (k, v) in extra.as_object().unwrap() {
        p[k] = v.clone();
    }
    RetrievalProfile::from_json(&p.to_string()).unwrap()
}
fn passages(f: &Fixture) -> Vec<Passage> {
    let source = std::fs::read(f.paths.root().join("source.py")).unwrap();
    let hash = format!("{:x}", Sha256::digest(&source));
    [("alpha", 1), ("beta", 4)]
        .into_iter()
        .map(|(name, line)| Passage {
            entity: EntityKey {
                path: "source.py".into(),
                kind: "function".into(),
                qualname: Some(name.into()),
                owner: None,
                definition_ordinal: 0,
            },
            span: Span::new(line, line + 1).unwrap(),
            entity_span: Span::new(line, line + 1).unwrap(),
            fields: PassageFields {
                identity: format!("function {name}").into(),
                signature: format!("def {name}():").into(),
                documentation: "".into(),
                body: format!(
                    "def {name}():\n    return {}",
                    if name == "alpha" { 1 } else { 2 }
                )
                .into(),
                path: "source.py".into(),
            },
            source_hash: hash.clone(),
            language: "python".into(),
            role: "definition".into(),
            split_reason: None,
            signals: BTreeMap::new(),
            implementation_start_line: Some(line + 1),
        })
        .collect()
}
fn evidence_fixture(p: &RetrievalProfile, prepare: bool) -> Fixture {
    let mut f = Fixture::new();
    let id = f.file("source.py", None);
    f.symbol(id, "alpha", "alpha", 1, None);
    f.symbol(id, "beta", "beta", 4, None);
    let passages = passages(&f);
    let tx = f.db.immediate().unwrap();
    replace_file_passages(
        &tx,
        id,
        &passages,
        Some(&passages[0].source_hash),
        &PassagePolicy::default(),
    )
    .unwrap();
    tx.commit().unwrap();
    f.db.set_meta("retrieval_profile", &serde_json::to_string(p).unwrap())
        .unwrap();
    if prepare {
        index_embeddings(&mut f.db, p.clone(), runtime(), Rc::new(Loader)).unwrap();
    }
    f
}
fn request(query: &str, purpose: &str, budget: isize) -> SearchRequest {
    SearchOptions {
        query: query.into(),
        purpose: purpose.into(),
        max_chars: budget,
        explain: true,
        ..Default::default()
    }
    .try_into()
    .unwrap()
}
#[test]
fn evidence_exact_locator_is_cold_and_exposes_verified_owned_ranges_with_profile_identity() {
    let p = profile(json!({}));
    let f = evidence_fixture(&p, false);
    let r = f
        .owner()
        .evidence(
            f.db.connection(),
            &f.paths,
            &request("source.py::alpha", "implementation", 12000),
        )
        .unwrap();
    assert!(r.is_success());
    let v = value(&r);
    assert_eq!(v["query"], "source.py::alpha");
    assert_eq!(v["profile_version"], p.fingerprint(&runtime()).unwrap());
    assert_eq!(v["results"][0]["entity"]["qualname"], "alpha");
    assert_eq!(v["results"][0]["source_hash"], passages(&f)[0].source_hash);
    assert_eq!(v["results"][0]["stale"], false);
    assert_eq!(v["results"][0]["evidence"][0]["start_line"], 1);
    assert_eq!(v["results"][0]["evidence"][0]["end_line"], 2);
    assert!(r.render(false).contains("return 1"));
    assert!(f.models.calls.borrow().is_empty());
    assert_eq!(f.models.judges.get(), 0);
}
#[test]
fn evidence_missing_preparation_is_structured_and_does_not_load_bestsearch_or_models() {
    let f = Fixture::new();
    let r = f
        .owner()
        .evidence(
            f.db.connection(),
            &f.paths,
            &request("source search", "auto", 12000),
        )
        .unwrap();
    assert!(!r.is_success());
    let v = value(&r);
    assert_eq!(v["ok"], false);
    assert_eq!(v["code"], "retrieval_index_required");
    assert_eq!(v["results"], json!([]));
    assert!(
        v["next_action"]
            .as_str()
            .unwrap()
            .contains("ken retrieval index")
    );
    assert!(!r.render(false).contains("search_preparation_required"));
    assert!(f.models.calls.borrow().is_empty());
    assert!(
        !SearchCompatibility::evidence_requirement(f.db.connection())
            .unwrap()
            .unwrap()
            .is_success()
    );
}
#[test]
fn evidence_changed_source_is_reported_stale_without_quoting_old_or_replacement_content() {
    let p = profile(json!({}));
    let f = evidence_fixture(&p, false);
    std::fs::write(f.paths.root().join("source.py"), "unrelated replacement\n").unwrap();
    let r = f
        .owner()
        .evidence(
            f.db.connection(),
            &f.paths,
            &request("source.py::alpha", "auto", 12000),
        )
        .unwrap();
    let v = value(&r);
    assert_eq!(v["results"][0]["stale"], true);
    assert_eq!(v["results"][0]["evidence"], json!([]));
    assert!(!v["warnings"].as_array().unwrap().is_empty());
    assert!(!r.render(false).contains("return 1"));
    assert!(!r.render(false).contains("unrelated replacement"));
    assert!(f.models.calls.borrow().is_empty());
}
#[test]
fn evidence_nonexact_uses_pinned_profile_encoders_and_joint_ordering_not_bestsearch() {
    let p = profile(
        json!({"joint":{"model":{"model_id":"test/joint","revision":"b".repeat(40),"backend":"provided"},"rank_unit":"entity","evidence_results":0}}),
    );
    let f = evidence_fixture(&p, true);
    let r = f
        .owner()
        .evidence(
            f.db.connection(),
            &f.paths,
            &request("return values", "implementation", 12000),
        )
        .unwrap();
    let v = value(&r);
    assert_eq!(v["results"][0]["entity"]["qualname"], "beta");
    assert_eq!(f.models.judges.get(), 1);
    assert!(!f.models.calls.borrow().is_empty());
    assert!(
        f.models
            .calls
            .borrow()
            .iter()
            .all(|call| call.starts_with("test/compat:"))
    );
}
#[test]
fn evidence_full_envelope_budget_and_missing_pinned_owner_ranker_remain_honest() {
    let p = profile(json!({}));
    let f = evidence_fixture(&p, false);
    let r = f
        .owner()
        .evidence(
            f.db.connection(),
            &f.paths,
            &request("source.py::alpha", "auto", 300),
        )
        .unwrap();
    let EvidenceResponse::Matches(response) = r else {
        panic!("prepared exact source should produce matches")
    };
    assert!(response.python_characters() <= 300);
    assert!(response.truncated);
    assert!(response.results.is_empty());
    let p = profile(
        json!({"evidence":{"model_revision":"c".repeat(64),"word_model":{"model_id":"test/words","revision":"d".repeat(40),"backend":"provided"}}}),
    );
    let f = evidence_fixture(&p, true);
    let error = f
        .owner()
        .evidence(
            f.db.connection(),
            &f.paths,
            &request("return values", "auto", 12000),
        )
        .unwrap_err()
        .to_string();
    assert!(error.contains("pinned owner ranker"), "{error}");
    assert_eq!(f.models.judges.get(), 0);
    assert!(
        f.owner()
            .evidence(
                f.db.connection(),
                &f.paths,
                &request("source.py::alpha", "auto", 12000)
            )
            .unwrap()
            .is_success()
    );
}
