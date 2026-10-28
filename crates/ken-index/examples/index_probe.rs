//! Input-only process for independent incremental-index histories and raw effects.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{
    DocumentEncoder, IndexError, IndexOptions, Indexer, Progress, VectorStorage, delete_file,
    delete_path,
};
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, ModelError, RetrievalProfile};
use ken_retrieval::{
    LexicalCounter, PassagePolicy, Result as RetrievalResult, RetrievalError, TokenCounter,
    encoder::EncoderLoader, projections::index_embeddings, storage::load_passage_map,
};
use ken_store::{ProjectDatabase, VectorSpace, VectorStore};
use ken_syntax::{GrammarCatalog, ParserRegistry};
use rusqlite::{Connection, types::ValueRef};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fs,
    io::{self, Read},
    path::{Component, Path, PathBuf},
    rc::Rc,
    time::{Duration, UNIX_EPOCH},
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
    grammar_manifest: PathBuf,
    legacy_runtime: Value,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    operations: Vec<Operation>,
}
fn max_bytes() -> u64 {
    1024 * 1024
}
fn chunk_files() -> usize {
    128
}
#[derive(Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Race {
    Source { path: String, source_hex: String },
    Profile { fingerprint: String },
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Operation {
    Write {
        path: String,
        source_hex: String,
    },
    Remove {
        path: String,
    },
    Delete {
        path: String,
        #[serde(default)]
        subtree: bool,
    },
    Invalidate {
        parser_version: Option<i64>,
        name_token_version: Option<String>,
        extractor_version: Option<i64>,
        #[serde(default)]
        clear_tokens: bool,
    },
    BlockVectors {
        blocked: bool,
    },
    Index {
        paths: Vec<String>,
        #[serde(default = "max_bytes")]
        max_file_bytes: u64,
        #[serde(default = "chunk_files")]
        chunk_files: usize,
        #[serde(default)]
        workers: usize,
        #[serde(default)]
        embed: bool,
        #[serde(default)]
        mapped: bool,
        profile: Option<Value>,
        #[serde(default)]
        prepare: bool,
        policy: Option<Policy>,
        #[serde(default)]
        characters: bool,
        #[serde(default)]
        fail_encode: bool,
        #[serde(default)]
        fail_load: bool,
        #[serde(default)]
        nan_behavior: bool,
        race: Option<Race>,
    },
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    max_tokens: usize,
    tokenizer_version: String,
}
#[derive(Serialize)]
struct NativeError {
    kind: String,
    message: String,
}
fn retrieval_kind(error: &RetrievalError) -> &'static str {
    match error {
        RetrievalError::Numeric(e) => e.kind(),
        RetrievalError::Version(_) => "index_version",
        RetrievalError::Model(_) => "model",
        RetrievalError::Invalid(_) | RetrievalError::MissingField(_) => "invalid",
        RetrievalError::Sql(_) => "sqlite",
        RetrievalError::Store(_) => "store",
        RetrievalError::Json(_) => "invalid",
    }
}
fn error(error: &(dyn Error + 'static)) -> NativeError {
    let kind = if let Some(index) = error.downcast_ref::<IndexError>() {
        match index {
            IndexError::Retrieval(e) => retrieval_kind(e),
            IndexError::Io(_) => "io",
            IndexError::Parse(_) => "parse",
            IndexError::Import(_) => "invalid_config",
            IndexError::Store(_) => "store",
            IndexError::Sql(_) => "sqlite",
            IndexError::Invalid(_) => "invalid",
        }
    } else if let Some(error) = error.downcast_ref::<RetrievalError>() {
        retrieval_kind(error)
    } else if error.is::<io::Error>() {
        "io"
    } else {
        "invalid"
    };
    NativeError {
        kind: kind.into(),
        message: error.to_string(),
    }
}
fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}
fn relative(root: &Path, path: &str) -> io::Result<PathBuf> {
    let path = Path::new(path);
    if path
        .components()
        .any(|p| !matches!(p, Component::Normal(_) | Component::CurDir))
        || path.as_os_str().is_empty()
    {
        return Err(invalid(
            "fixture paths must stay inside their private project",
        ));
    }
    Ok(root.join(path))
}
fn unhex(text: &str) -> io::Result<Vec<u8>> {
    if !text.len().is_multiple_of(2) || text.len() > 2 * 1024 * 1024 {
        return Err(invalid("invalid or oversized source_hex"));
    }
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).map_err(|_| invalid("invalid source_hex")))
        .collect()
}
fn write(root: &Path, path: &str, source: &str) -> io::Result<()> {
    let path = relative(root, path)?;
    fs::create_dir_all(
        path.parent()
            .ok_or_else(|| invalid("file parent required"))?,
    )?;
    fs::write(&path, unhex(source)?)?;
    fs::File::open(path)?.set_times(
        fs::FileTimes::new()
            .set_modified(UNIX_EPOCH + Duration::from_nanos(1_234_567_890_000_000_000)),
    )?;
    Ok(())
}
struct Encoder {
    calls: RefCell<Vec<Vec<String>>>,
    loads: Cell<usize>,
    characters: Cell<bool>,
    fail_encode: Cell<bool>,
    fail_load: Cell<bool>,
    nan_behavior: Cell<bool>,
    race: RefCell<Option<Race>>,
    root: PathBuf,
    db: PathBuf,
}
impl DocumentEncoder for Encoder {
    fn dim(&self) -> RetrievalResult<usize> {
        Ok(3)
    }
    fn token_count(&self, text: &str) -> RetrievalResult<usize> {
        if self.characters.get() {
            Ok(text.chars().count())
        } else {
            LexicalCounter.count(text)
        }
    }
    fn embed_passages(&self, texts: &[&str]) -> RetrievalResult<Vec<Vec<f32>>> {
        self.calls
            .borrow_mut()
            .push(texts.iter().map(|s| s.to_string()).collect());
        if self.fail_encode.get() {
            return Err(ModelError::Inference("encoding unavailable".into()).into());
        }
        let vectors = texts
            .iter()
            .map(|s| {
                if self.nan_behavior.get() && s.contains("\nSource:\n") {
                    return vec![f32::NAN, 1., 0.];
                }
                let b = s.as_bytes();
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
                let norm = v.iter().map(|n| n * n).sum::<f32>().sqrt();
                for n in &mut v {
                    *n /= norm
                }
                v
            })
            .collect();
        if let Some(race) = self.race.borrow_mut().take() {
            match race {
                Race::Source { path, source_hex } => write(&self.root, &path, &source_hex)
                    .map_err(|e| ModelError::Inference(e.to_string()))?,
                Race::Profile { fingerprint } => {
                    let db = ProjectDatabase::open(&self.db)?;
                    db.set_meta("retrieval_profile_fingerprint", &fingerprint)?;
                }
            }
        }
        Ok(vectors)
    }
}
struct Loader(Rc<Encoder>);
impl EncoderLoader for Loader {
    fn load(&self, _: &EncoderSpec) -> RetrievalResult<Rc<dyn DocumentEncoder>> {
        self.0.loads.set(self.0.loads.get() + 1);
        if self.0.fail_load.get() {
            return Err(ModelError::Inference("encoder load unavailable".into()).into());
        }
        Ok(self.0.clone())
    }
}
#[derive(Default)]
struct Events {
    events: Vec<(String, String)>,
    warnings: Vec<String>,
}
impl Progress for Events {
    fn file(&mut self, p: &str, s: &str) {
        self.events.push((p.into(), s.into()));
    }
    fn warning(&mut self, s: &str) {
        self.warnings.push(s.into());
    }
}
fn snapshot(conn: &Connection, paths: &ProjectPaths) -> std::result::Result<Value, Box<dyn Error>> {
    let mut tables = BTreeMap::new();
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
        ("ci_retrieval_embeddings", "id"),
        ("ci_passage_vectors", "passage_id,view"),
        ("ci_vec_alloc", "space"),
        ("ci_vec_free", "space,slot"),
        ("meta", "key"),
    ] {
        let mut query = conn.prepare(&format!("SELECT * FROM {table} ORDER BY {order}"))?;
        let rows=query.query_map([],|r|(0..r.as_ref().column_count()).map(|i|Ok(match r.get_ref(i)?{ValueRef::Null=>Value::Null,ValueRef::Integer(v)=>json!(v),ValueRef::Real(v)=>json!(v),ValueRef::Text(v)=>json!(std::str::from_utf8(v).map_err(|_|rusqlite::Error::InvalidQuery)?),ValueRef::Blob(v)=>json!({"blob_hex":v.iter().map(|b|format!("{b:02x}")).collect::<String>()})})).collect::<rusqlite::Result<Vec<_>>>())?.collect::<rusqlite::Result<Vec<_>>>()?;
        tables.insert(table, rows);
    }
    let mut legacy_vectors = BTreeMap::new();
    for space in VectorSpace::ALL {
        let mut query = conn.prepare(&format!(
            "SELECT id,vec_slot,embedding FROM {} ORDER BY id",
            space.as_str()
        ))?;
        let rows = query
            .query_map([], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, Option<i64>>(1)?,
                    r.get::<_, Option<Vec<u8>>>(2)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let mut output = Vec::new();
        for (id, slot, blob) in rows {
            let vector = if let Some(slot) = slot {
                match VectorStore::open(&paths.vectors(), space, 3, Some("provided-deterministic"))
                {
                    Ok(store) => match store.read(&[slot]) {
                        Ok(vectors) => json!({"vector":vectors[0]}),
                        Err(e) => json!({"error":e.to_string()}),
                    },
                    Err(e) => json!({"error":e.to_string()}),
                }
            } else if let Some(blob) = blob {
                if !blob.len().is_multiple_of(4) {
                    json!({"error":"invalid inline bytes"})
                } else {
                    json!({"vector":blob.chunks_exact(4).map(|b|f32::from_le_bytes(b.try_into().expect("four bytes"))).collect::<Vec<_>>()})
                }
            } else {
                json!({"vector":Value::Null})
            };
            output.push(json!({"id":id,"slot":slot,"value":vector}));
        }
        legacy_vectors.insert(space.as_str(), output);
    }
    let loaded = match load_passage_map(conn, None) {
        Ok(p) => json!({"passages":p}),
        Err(e) => json!({"error":error(&e)}),
    };
    Ok(json!({"tables":tables,"legacy_vectors":legacy_vectors,"loaded":loaded}))
}
fn run(
    case: Case,
    parsers: &ParserRegistry,
    legacy: &LegacyRuntimeIdentity,
) -> std::result::Result<Value, Box<dyn Error>> {
    let private = tempfile::tempdir()?;
    let root = private.path().join("IndexProject");
    fs::create_dir_all(&root)?;
    let context = DiscoveryContext {
        cwd: root.clone(),
        home: Some(root.clone()),
        forced_root: None,
    };
    let paths = ProjectPaths::at(&root, &context)?;
    fs::create_dir_all(
        paths
            .db()
            .parent()
            .ok_or_else(|| invalid("database parent required"))?,
    )?;
    let mut db = ProjectDatabase::open(&paths.db())?;
    db.initialize()?;
    let encoder = Rc::new(Encoder {
        calls: RefCell::new(vec![]),
        loads: Cell::new(0),
        characters: Cell::new(false),
        fail_encode: Cell::new(false),
        fail_load: Cell::new(false),
        nan_behavior: Cell::new(false),
        race: RefCell::new(None),
        root: root.clone(),
        db: paths.db(),
    });
    let loader = Rc::new(Loader(encoder.clone()));
    let indexer = Indexer::new(parsers);
    let mut steps = Vec::new();
    for operation in case.operations {
        let mut events = Events::default();
        let outcome = (|| -> std::result::Result<Value, Box<dyn Error>> {
            match operation {
                Operation::Write { path, source_hex } => {
                    write(&root, &path, &source_hex)?;
                    Ok(json!({"written":true}))
                }
                Operation::Remove { path } => {
                    let p = relative(&root, &path)?;
                    if p.is_dir() {
                        fs::remove_dir_all(p)?;
                    } else {
                        fs::remove_file(p)?;
                    }
                    Ok(json!({"removed":true}))
                }
                Operation::Delete { path, subtree } => {
                    if subtree {
                        Ok(json!({"deleted":delete_path(db.connection(),&path)?}))
                    } else {
                        Ok(json!({"deleted":delete_file(db.connection(),&path)?}))
                    }
                }
                Operation::Invalidate {
                    parser_version,
                    name_token_version,
                    extractor_version,
                    clear_tokens,
                } => {
                    if let Some(version) = parser_version {
                        db.connection()
                            .execute("UPDATE ci_files SET parser_version=?1", [version])?;
                    }
                    if let Some(version) = name_token_version {
                        db.set_meta("name_token_version", &version)?;
                    }
                    if let Some(version) = extractor_version {
                        db.connection().execute(
                            "UPDATE ci_retrieval_files SET extractor_version=?1",
                            [version],
                        )?;
                    }
                    if clear_tokens {
                        db.connection().execute("DELETE FROM ci_name_tokens", [])?;
                    }
                    Ok(json!({"invalidated":true}))
                }
                Operation::BlockVectors { blocked } => {
                    if blocked {
                        if paths.vectors().exists() {
                            fs::rename(paths.vectors(), root.join(".ken/vectors.saved"))?;
                        }
                        fs::write(paths.vectors(), b"not a directory")?;
                    } else {
                        fs::remove_file(paths.vectors())?;
                        let saved = root.join(".ken/vectors.saved");
                        if saved.exists() {
                            fs::rename(saved, paths.vectors())?;
                        }
                    }
                    Ok(json!({"blocked":blocked}))
                }
                Operation::Index {
                    paths: files,
                    max_file_bytes,
                    chunk_files,
                    workers,
                    embed,
                    mapped,
                    profile,
                    prepare,
                    policy,
                    characters,
                    fail_encode,
                    fail_load,
                    nan_behavior,
                    race,
                } => {
                    for path in &files {
                        relative(&root, path)?;
                    }
                    if let Some(Race::Source { path, .. }) = &race {
                        relative(&root, path)?;
                    }
                    encoder.calls.borrow_mut().clear();
                    encoder.loads.set(0);
                    encoder.characters.set(characters);
                    encoder.fail_encode.set(fail_encode);
                    encoder.fail_load.set(fail_load);
                    encoder.nan_behavior.set(nan_behavior);
                    *encoder.race.borrow_mut() = race;
                    let profile = profile
                        .map(|p| RetrievalProfile::from_json(&p.to_string()))
                        .transpose()?;
                    let policy = policy
                        .map(|p| PassagePolicy::new(p.max_tokens, p.tokenizer_version))
                        .transpose()?;
                    let options = IndexOptions {
                        max_file_bytes,
                        chunk_files,
                        workers: Some(workers),
                        legacy_encoder: embed.then_some(encoder.as_ref()),
                        legacy_model: Some("provided-deterministic"),
                        vector_storage: if mapped {
                            VectorStorage::Automatic
                        } else {
                            VectorStorage::Inline
                        },
                        retrieval_profile: profile.clone(),
                        retrieval_loader: Some(loader.clone()),
                        legacy_runtime: Some(legacy.clone()),
                        retrieval_policy: policy,
                        now_ms: Some(&|| 1_700_000_000_000),
                        ..Default::default()
                    };
                    let files: Vec<_> = files.into_iter().map(PathBuf::from).collect();
                    let stats =
                        indexer.index_files(&mut db, &paths, &files, &options, &mut events)?;
                    if prepare {
                        let profile = profile
                            .ok_or_else(|| invalid("explicit profile required for prepare"))?;
                        index_embeddings(&mut db, profile, legacy.clone(), loader.clone())?;
                    }
                    Ok(
                        json!({"stats":stats,"events":events.events,"encoder_calls":*encoder.calls.borrow(),"encoder_loads":encoder.loads.get(),"storage_fallback":!events.warnings.is_empty(),"warnings":events.warnings}),
                    )
                }
            }
        })();
        let mut step = match outcome {
            Ok(result) => json!({"result":result}),
            Err(e) => {
                json!({"error":error(e.as_ref()),"events":events.events,"encoder_calls":*encoder.calls.borrow(),"encoder_loads":encoder.loads.get(),"warnings":events.warnings})
            }
        };
        step["snapshot"] = snapshot(db.connection(), &paths)?;
        steps.push(step);
    }
    Ok(json!({"id":case.id,"steps":steps}))
}
fn main() -> std::result::Result<(), Box<dyn Error>> {
    let started = std::time::Instant::now();
    let mut bytes = Vec::new();
    io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err(invalid("request exceeds 8 MiB").into());
    }
    let request: Request = serde_json::from_slice(&bytes)?;
    if request.format != "ken-index-probe/1" || request.cases.len() > 128 {
        return Err(invalid("invalid native index request").into());
    }
    let mut ids = BTreeSet::new();
    for c in &request.cases {
        if c.id.is_empty() || !ids.insert(&c.id) || c.operations.len() > 512 {
            return Err(invalid("invalid or duplicate native case").into());
        }
    }
    let legacy = LegacyRuntimeIdentity::from_json(&request.legacy_runtime.to_string())?;
    let parsers = ParserRegistry::new(GrammarCatalog::prepared(&request.grammar_manifest)?);
    let mut cases = Vec::new();
    for case in request.cases {
        cases.push(run(case, &parsers, &legacy)?);
    }
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    let rss = (usage.ru_maxrss as u64) * if cfg!(target_os = "macos") { 1 } else { 1024 };
    let output = serde_json::to_vec(
        &json!({"format":"ken-index-probe/1","platform":std::env::consts::OS,"cases":cases,"metrics":{"max_rss_bytes":rss,"elapsed_s":started.elapsed().as_secs_f64(),"scope":"whole native process, all requested histories and grammar caches"}}),
    )?;
    if output.len() > 32 * 1024 * 1024 {
        return Err(invalid("native response exceeds 32 MiB").into());
    }
    use std::io::Write;
    io::stdout().write_all(&output)?;
    Ok(())
}
