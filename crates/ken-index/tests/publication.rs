use ken_index::{
    DocumentEncoder, DocumentTarget, IndexWriter, LegacyStores, PreparedFile, SourceMetadata,
    WriterOptions, delete_file, delete_path, encode_pending, intents::plain_text_intents,
    rebuild_name_tokens,
};
use ken_retrieval::{LexicalCounter, Passage, PassagePolicy};
use ken_store::{ProjectDatabase, VectorSpace, high_water};
use ken_syntax::ParsedFile;
use rusqlite::{Connection, types::ValueRef};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{cell::RefCell, collections::BTreeSet};
#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
    intents: Vec<Intent>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    encoder_calls: Vec<Vec<String>>,
    steps: Vec<Step>,
}
#[derive(Deserialize)]
struct Input {
    path: String,
    source_hex: String,
    language: Option<String>,
    parsed: Option<ParsedFile>,
    content_hash_hex: String,
    mtime_ns: i64,
    source_hash: String,
    passages: Vec<Passage>,
    intent_texts: Vec<String>,
    documents: Value,
    extra_stopwords: BTreeSet<String>,
}
#[derive(Deserialize)]
struct Step {
    action: String,
    tables: Value,
}
#[derive(Deserialize)]
struct Intent {
    path: String,
    source_hex: String,
    result: Vec<String>,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/publication-reference.json")).unwrap()
}
fn bytes(text: &str) -> Vec<u8> {
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
        .collect()
}
fn prepare(i: &Input) -> PreparedFile {
    PreparedFile::new(
        SourceMetadata {
            path: i.path.clone(),
            language: i.language.clone(),
            content_hash: bytes(&i.content_hash_hex).try_into().unwrap(),
            mtime_ns: i.mtime_ns,
            order: 0,
        },
        &bytes(&i.source_hex),
        i.parsed.clone(),
        &PassagePolicy::default(),
        &LexicalCounter,
    )
    .unwrap()
}
fn database() -> (tempfile::TempDir, ProjectDatabase) {
    let dir = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&dir.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    (dir, db)
}
fn snapshot(conn: &Connection) -> Value {
    let mut map = serde_json::Map::new();
    for (table, order) in [
        ("ci_files", "id"),
        ("ci_symbols", "id"),
        ("ci_imports", "id"),
        ("ci_intent_sources", "id"),
        ("ci_name_tokens", "kind,token,row_id"),
        ("ci_passages", "id"),
        ("ci_passage_terms", "passage_id,field,term"),
        ("ci_passage_lengths", "passage_id,field"),
        ("ci_retrieval_files", "file_id"),
        ("meta", "key"),
    ] {
        let mut statement = conn
            .prepare(&format!("SELECT * FROM {table} ORDER BY {order}"))
            .unwrap();
        let rows=statement.query_map([],|row|(0..row.as_ref().column_count()).map(|i|Ok(match row.get_ref(i)?{ValueRef::Null=>Value::Null,ValueRef::Integer(v)=>json!(v),ValueRef::Real(v)=>json!(v),ValueRef::Text(v)=>json!(std::str::from_utf8(v).unwrap()),ValueRef::Blob(v)=>json!({"blob_hex":v.iter().map(|b|format!("{b:02x}")).collect::<String>()})})).collect::<rusqlite::Result<Vec<_>>>()).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
        map.insert(table.into(), json!(rows));
    }
    Value::Object(map)
}
#[derive(Default)]
struct Encoder {
    calls: RefCell<Vec<Vec<String>>>,
}
impl DocumentEncoder for Encoder {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        Ok(3)
    }
    fn token_count(&self, text: &str) -> ken_retrieval::Result<usize> {
        use ken_retrieval::TokenCounter;
        LexicalCounter.count(text)
    }
    fn embed_passages(&self, texts: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.calls
            .borrow_mut()
            .push(texts.iter().map(|s| s.to_string()).collect());
        Ok(texts
            .iter()
            .map(|text| {
                let b = text.as_bytes();
                let mut v = vec![
                    (b.iter().map(|&n| n as u64).sum::<u64>() % 31 + 1) as f32,
                    (b.len() % 23 + 1) as f32,
                    (b.iter()
                        .enumerate()
                        .map(|(i, &n)| (i + 1) as u64 * n as u64)
                        .sum::<u64>()
                        % 19
                        + 1) as f32,
                ];
                let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
                v.iter_mut().for_each(|x| *x /= norm);
                v
            })
            .collect())
    }
}
fn target(t: &DocumentTarget) -> Value {
    match t {
        DocumentTarget::File => json!(["file"]),
        DocumentTarget::Symbol(i) => json!(["symbol", i]),
        DocumentTarget::SymbolDoc(i) => json!(["symbol_doc", i]),
        DocumentTarget::ModuleDoc => json!(["module_doc"]),
        DocumentTarget::PlainIntent(i) => json!(["plain_intent", i]),
    }
}
#[test]
fn canonical_publication_matches_original() {
    let f = fixture();
    assert_eq!(f.cases.len(), 31);
    for c in f.cases {
        let (_dir, mut db) = database();
        let mut file = prepare(&c.input);
        assert_eq!(file.passages, c.input.passages, "{} passages", c.id);
        assert_eq!(file.source_sha256, c.input.source_hash);
        assert_eq!(file.intent_texts, c.input.intent_texts);
        let documents: Vec<_> = file
            .documents
            .iter()
            .map(|d| json!({"target":target(&d.target),"text":d.text}))
            .collect();
        assert_eq!(json!(documents), c.input.documents, "{} documents", c.id);
        let encoder = Encoder::default();
        encode_pending(std::slice::from_mut(&mut file), &encoder).unwrap();
        assert_eq!(*encoder.calls.borrow(), c.encoder_calls);
        let options = WriterOptions {
            stores: None,
            stopwords: &c.input.extra_stopwords,
            policy: &PassagePolicy::default(),
            now_ms: &|| 1700000000000,
            parser_version: 10,
        };
        for step in c.steps {
            match step.action.as_str() {
                "publish" | "repeat" => {
                    assert_eq!(IndexWriter::publish(&mut db, &file, &options).unwrap(), 1);
                }
                "rebuild" => {
                    rebuild_name_tokens(db.connection(), &c.input.extra_stopwords).unwrap();
                }
                "delete" => {
                    assert!(delete_file(db.connection(), &c.input.path).unwrap());
                }
                _ => panic!("unexpected action"),
            }
            assert_eq!(
                snapshot(db.connection()),
                step.tables,
                "{} {}",
                c.id,
                step.action
            );
        }
    }
}
#[test]
fn plain_intent_limits_and_document_inputs() {
    for i in fixture().intents {
        assert_eq!(
            plain_text_intents(&i.path, &bytes(&i.source_hex)),
            i.result,
            "{}",
            i.path
        );
    }
}
#[test]
fn compact_outline_merges_all_canonical_scopes() {
    let mut c = fixture()
        .cases
        .into_iter()
        .find(|c| {
            c.input
                .parsed
                .as_ref()
                .is_some_and(|p| !p.scopes.is_empty())
        })
        .unwrap();
    let expected = prepare(&c.input).parsed.unwrap().symbols;
    c.input.parsed.as_mut().unwrap().symbols.clear();
    assert_eq!(prepare(&c.input).parsed.unwrap().symbols, expected);
}
#[test]
fn delete_path_is_exact_subtree() {
    let (_dir, db) = database();
    for p in [
        "pkg/a.py",
        "pkg/b.py",
        "pkgA/a.py",
        "pkg_extra.py",
        "pkg%/x.py",
    ] {
        db.connection()
            .execute(
                "INSERT INTO ci_files(path,content_hash,mtime,indexed_at)VALUES(?1,x'00',0,0)",
                [p],
            )
            .unwrap();
    }
    assert_eq!(delete_path(db.connection(), "pkg/").unwrap(), 2);
    assert_eq!(delete_path(db.connection(), "pkg%").unwrap(), 1);
    assert!(!delete_file(db.connection(), "missing").unwrap());
    let count: i64 = db
        .connection()
        .query_row("SELECT count(*) FROM ci_files", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 2);
}
#[test]
fn legacy_vectors_survive_rollback_and_reuse_bounded_slots() {
    let c = fixture()
        .cases
        .into_iter()
        .find(|c| c.input.language.as_deref() == Some("python"))
        .unwrap();
    let (dir, mut db) = database();
    let stores = LegacyStores::open(
        &dir.path().join("vectors"),
        3,
        Some("provided-deterministic"),
    )
    .unwrap();
    let mut file = prepare(&c.input);
    let encoder = Encoder::default();
    encode_pending(std::slice::from_mut(&mut file), &encoder).unwrap();
    let stops = BTreeSet::new();
    let policy = PassagePolicy::default();
    let options = WriterOptions {
        stores: Some(&stores),
        stopwords: &stops,
        policy: &policy,
        now_ms: &|| 1700000000000,
        parser_version: 10,
    };
    IndexWriter::publish(&mut db, &file, &options).unwrap();
    let slot: i64 = db
        .connection()
        .query_row("SELECT vec_slot FROM ci_files", [], |r| r.get(0))
        .unwrap();
    let before = stores.get(VectorSpace::Files).read(&[slot]).unwrap();
    let snapshot_before = snapshot(db.connection());
    let mut invalid = file.clone();
    invalid
        .vectors
        .insert(DocumentTarget::File, vec![0., 1., 0.]);
    invalid.passages[0].source_hash = "mixed".into();
    assert!(IndexWriter::publish(&mut db, &invalid, &options).is_err());
    assert_eq!(snapshot(db.connection()), snapshot_before);
    assert_eq!(
        stores.get(VectorSpace::Files).read(&[slot]).unwrap(),
        before
    );
    for _ in 0..10 {
        IndexWriter::publish(&mut db, &file, &options).unwrap();
    }
    assert!(high_water(db.connection(), VectorSpace::Files).unwrap() <= 2);
    let symbols: i64 = db
        .connection()
        .query_row("SELECT count(*) FROM ci_symbols", [], |r| r.get(0))
        .unwrap();
    assert!(high_water(db.connection(), VectorSpace::Symbols).unwrap() <= 2 * symbols);
    assert!(
        db.connection()
            .query_row("SELECT embedding IS NULL FROM ci_files", [], |r| r
                .get::<_, bool>(0))
            .unwrap()
    );
    assert_eq!(
        db.connection()
            .query_row(
                "SELECT count(*) FROM ci_symbols WHERE vec_slot IS NULL",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
}
