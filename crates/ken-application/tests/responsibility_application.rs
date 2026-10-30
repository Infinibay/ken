use ken_application::knowledge::EmbeddingResources;
use ken_application::responsibility::{
    NativeVerification, Verification, WhoApplication, WhoOptions, who_with,
};
use ken_maintenance::{ConfigEnvironment, UserConfig};
use ken_models::{
    AcquisitionPolicy, ArtifactCache, ModelCatalog, ModelFactory, PreparedModelResources,
};
use ken_responsibility::{
    self as domain, Candidate, CurrentSources, IndexedCandidate, LiveScores, NativeSources,
    Preview, RankedRows, ResponsibilityVectors, Snippet, Symbol, WhoOutput, WhoReport, WhoRequest,
};
use ken_retrieval::project_embeddings::TransformerOverrides;
use ken_syntax::GrammarCatalog;
use ken_text::PythonText;
use rusqlite::{Connection, params};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
};
fn catalog() -> Arc<GrammarCatalog> {
    Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("explicit prepared grammars"),
        ))
        .unwrap(),
    )
}
fn source() -> &'static str {
    "def emit():\n return 42\ndef store():\n \"\"\"Store reusable findings.\"\"\"\n return emit()\n"
}
fn setup(root: &Path) -> Connection {
    std::fs::create_dir(root.join(".ken")).unwrap();
    std::fs::write(root.join("store.py"), source()).unwrap();
    let path = root.join(".ken/ken.db");
    let mut store = ken_store::ProjectDatabase::open(&path).unwrap();
    store.initialize().unwrap();
    drop(store);
    let conn = Connection::open(path).unwrap();
    conn.execute(
        "INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at)VALUES(1,'store.py',?,0,0)",
        [vec![0u8; 32]],
    )
    .unwrap();
    conn.execute("INSERT INTO ci_symbols(id,file_id,qualname,name,kind,line_start,line_end,docstring)VALUES(1,1,'store','store','function',3,5,'Old indexed description')",[]).unwrap();
    conn.execute("INSERT INTO ci_intent_sources(file_id,symbol_id,source_kind,text,embedding,updated_at)VALUES(1,1,'symbol_docstring','Old indexed description',?,0)",[[1f32.to_le_bytes(),0f32.to_le_bytes()].concat()]).unwrap();
    conn
}
struct Vectors;
impl ResponsibilityVectors for Vectors {
    fn embed_query(&mut self, _: &str) -> domain::Result<Vec<f32>> {
        Ok(vec![1., 0.])
    }
    fn embed_passages(&mut self, texts: &[String]) -> domain::Result<Vec<Vec<f32>>> {
        Ok(texts.iter().map(|_| vec![0.9, 0.]).collect())
    }
    fn live_scores(
        &mut self,
        _: &Connection,
        _: &Path,
        _: &[f32],
    ) -> domain::Result<Option<LiveScores>> {
        Ok(None)
    }
    fn rank_against(&mut self, _: &[f32], blobs: &[Vec<u8>]) -> domain::Result<RankedRows> {
        Ok(RankedRows {
            kept: (0..blobs.len()).collect(),
            scores: vec![0.8; blobs.len()],
        })
    }
    fn cosine(&mut self, _: &[f32], _: &[f32], rows: usize, _: usize) -> domain::Result<Vec<f32>> {
        Ok(vec![0.9; rows])
    }
}
struct ForbiddenVerification;
impl Verification for ForbiddenVerification {
    fn enrich(&mut self, _: &Path, _: &mut WhoReport, _: f64) -> domain::Result<()> {
        panic!("verify=false must not acquire structural queries")
    }
}
fn request() -> WhoRequest {
    WhoRequest {
        question: "Store reusable findings".into(),
        ..Default::default()
    }
}
#[test]
fn public_who_ranks_current_documentation_and_omits_verification_when_disabled() {
    let root = tempfile::tempdir().unwrap();
    let conn = setup(root.path());
    let mut sources = NativeSources::new(root.path(), catalog()).unwrap();
    let options = WhoOptions {
        full: true,
        verify: false,
        ..Default::default()
    };
    let first = who_with(
        &conn,
        root.path(),
        &request(),
        &options,
        &mut Vectors,
        &mut sources,
        &mut ForbiddenVerification,
    )
    .unwrap();
    let first = first.to_json().unwrap();
    assert_eq!(
        first["candidates"][0]["documentation"],
        "Store reusable findings."
    );
    assert_eq!(first["candidates"][0]["source"]["index_changed"], true);
    assert!(first["candidates"][0].get("structure").is_none());
    std::fs::write(
        root.path().join("store.py"),
        source().replace(
            "Store reusable findings.",
            "Does not store reusable findings.",
        ),
    )
    .unwrap();
    let second = who_with(
        &conn,
        root.path(),
        &request(),
        &options,
        &mut Vectors,
        &mut sources,
        &mut ForbiddenVerification,
    )
    .unwrap()
    .to_json()
    .unwrap();
    assert!(second["candidates"].as_array().unwrap().is_empty());
    assert_eq!(second["counterevidence"][0]["symbol"], "store");
}
#[test]
fn public_who_optional_native_verification_adds_observation_without_changing_heuristic_scores() {
    let root = tempfile::tempdir().unwrap();
    let conn = setup(root.path());
    let catalog = catalog();
    let mut sources = NativeSources::new(root.path(), catalog.clone()).unwrap();
    let plain = who_with(
        &conn,
        root.path(),
        &request(),
        &WhoOptions {
            full: true,
            verify: false,
            ..Default::default()
        },
        &mut Vectors,
        &mut sources,
        &mut ForbiddenVerification,
    )
    .unwrap()
    .to_json()
    .unwrap();
    let packaged = ken_structural::application::catalog::Catalog::packaged()
        .unwrap()
        .libraries()
        .clone();
    let mut verification = NativeVerification::new(catalog, packaged);
    let observed = who_with(
        &conn,
        root.path(),
        &request(),
        &WhoOptions {
            full: true,
            verify: true,
            timeout_ms: 10000.,
        },
        &mut Vectors,
        &mut sources,
        &mut verification,
    )
    .unwrap()
    .to_json()
    .unwrap();
    assert_eq!(
        observed["candidates"][0]["confidence"],
        plain["candidates"][0]["confidence"]
    );
    assert!(observed["candidates"][0]["structure"]["observations"].is_object());
    assert!(observed["responsibility_map"].is_object());
}
struct SurrogatePreview(NativeSources);
impl CurrentSources for SurrogatePreview {
    fn begin_request(&mut self) -> domain::Result<()> {
        self.0.begin_request()
    }
    fn resolve(&mut self, row: &IndexedCandidate) -> domain::Result<Symbol> {
        self.0.resolve(row)
    }
    fn preview(&mut self, _: &Candidate) -> domain::Result<Preview> {
        Ok(Preview {
            end_line: 5,
            snippets: vec![Snippet {
                start_line: 3,
                end_line: 5,
                content: PythonText::from_codepoints(vec![0xd800]).unwrap(),
            }],
            truncated: false,
            preview_unavailable: None,
        })
    }
}
#[test]
fn who_keeps_typed_python_text_through_public_serialization_in_both_presentations() {
    let root = tempfile::tempdir().unwrap();
    let conn = setup(root.path());
    let mut sources = SurrogatePreview(NativeSources::new(root.path(), catalog()).unwrap());
    for full in [true, false] {
        let output: WhoOutput = who_with(
            &conn,
            root.path(),
            &request(),
            &WhoOptions {
                full,
                verify: false,
                ..Default::default()
            },
            &mut Vectors,
            &mut sources,
            &mut ForbiddenVerification,
        )
        .unwrap();
        let encoded = output.to_json_string().unwrap();
        assert!(encoded.contains("\\ud800"));
        assert!(
            output.to_json().is_err(),
            "typed output must not be forced through lossy serde_json::Value"
        );
    }
}
#[test]
fn native_who_rejects_invalid_request_without_model_pin_or_assets() {
    let root = tempfile::tempdir().unwrap();
    let conn = setup(root.path());
    let factory = Arc::new(ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&root.path().join("cache")).unwrap(),
        PreparedModelResources::new(
            &root.path().join("private"),
            &root.path().join("missing.npz"),
        )
        .unwrap(),
        AcquisitionPolicy::Offline,
    ));
    let config = UserConfig::new(&ConfigEnvironment {
        config_dir: None,
        xdg_config_home: None,
        home: root.path().into(),
    });
    let resources = EmbeddingResources::new(factory, config, None, TransformerOverrides::default());
    let app = WhoApplication::new(root.path(), resources, catalog(), BTreeMap::new()).unwrap();
    for request in [
        WhoRequest::default(),
        WhoRequest {
            question: "valid".into(),
            path: "..".into(),
            ..Default::default()
        },
        WhoRequest {
            question: "valid".into(),
            limit: 0,
            ..Default::default()
        },
    ] {
        assert!(
            app.who(
                &conn,
                &request,
                &WhoOptions {
                    verify: false,
                    ..Default::default()
                }
            )
            .is_err()
        );
    }
    assert_eq!(
        conn.query_row(
            "SELECT count(*) FROM meta WHERE key='embed_model'",
            params![],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
    assert!(!root.path().join("private").exists());
}
