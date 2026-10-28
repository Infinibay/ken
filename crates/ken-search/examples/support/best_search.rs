//! Input-only endpoint history caller. Controlled leaves never rank or prepare source.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{IndexOptions, Indexer};
use ken_models::{ContextModel, EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    DocumentEncoder, PassagePolicy, RetrievalError,
    context_preparation::ContextSourceEncoder,
    encoder::EncoderLoader,
    numeric_ranker::NumericRanker,
    owner_ranking::ExpansionConfig,
    paired_reranker::{NeuralScores, PairedReranker},
    projections::index_embeddings,
    query::SearchRequest,
    query_encoder::QueryEncoder,
    storage::generation,
    word_encoder::WordEncoder,
};
use ken_search::{
    BestSearch, SearchError, SearchResourceInputs, SearchResourceProvider, SearchResources,
    SearchWords,
};
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    path::PathBuf,
    rc::Rc,
    sync::Arc,
};
pub type ProbeResult<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    projects: Vec<Project>,
    actions: Vec<Action>,
    models: Models,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Project {
    id: String,
    files: BTreeMap<String, String>,
    seed: String,
    databases: BTreeMap<String, Vec<PathBuf>>,
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    Search {
        project: String,
        database: String,
        #[serde(deserialize_with = "search_request")]
        request: SearchRequest,
    },
    Prepare {
        project: String,
        database: String,
    },
    Write {
        project: String,
        path: String,
        text: String,
    },
    Reindex {
        project: String,
        database: String,
    },
    CorruptProfile {
        project: String,
        database: String,
    },
    OldExtractor {
        project: String,
        database: String,
    },
    ContextMode {
        mode: String,
    },
    NeuralMode {
        mode: String,
    },
    ExpansionMode {
        mode: String,
    },
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Models {
    kind: String,
    base_profile: RetrievalProfile,
    profile: RetrievalProfile,
    legacy_runtime: LegacyRuntimeIdentity,
    expansion: BTreeMap<String, String>,
    controls: Controls,
    native_model: Option<Value>,
    piece_model: Option<Value>,
    context_registration: Value,
    expansion_revision: String,
}
#[derive(Clone, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Controls {
    resource_failures: usize,
    context_mode: Option<String>,
    neural_mode: Option<String>,
    expansion_mode: Option<String>,
}
struct Control {
    calls: RefCell<Vec<Value>>,
    resource_failures: Cell<usize>,
    context_mode: RefCell<String>,
    neural_mode: RefCell<String>,
    expansion_mode: RefCell<String>,
    built: Cell<bool>,
}
impl Control {
    fn new(c: &Controls) -> Self {
        Self {
            calls: RefCell::new(vec![]),
            resource_failures: Cell::new(c.resource_failures),
            context_mode: RefCell::new(c.context_mode.clone().unwrap_or("basis".into())),
            neural_mode: RefCell::new(c.neural_mode.clone().unwrap_or("length".into())),
            expansion_mode: RefCell::new(c.expansion_mode.clone().unwrap_or("normal".into())),
            built: Cell::new(false),
        }
    }
    fn call(&self, v: Value) {
        self.calls.borrow_mut().push(v)
    }
}
struct Words {
    control: Rc<Control>,
    spec: EncoderSpec,
    inner: Option<Rc<dyn SearchWords>>,
}
impl Words {
    fn query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.control.call(json!({"op":"word_query","text":t}));
        if let Some(i) = &self.inner {
            return QueryEncoder::embed_query(i.as_ref(), t);
        }
        Ok(vec![1., 0., 0., 0.])
    }
    fn passages(&self, t: &[PythonText]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.control.call(json!({"op":"word_passages","texts":t}));
        if let Some(i) = &self.inner {
            return WordEncoder::embed_passages(i.as_ref(), t);
        }
        Ok(vec![vec![1., 0., 0., 0.]; t.len()])
    }
}
impl WordEncoder for Words {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn embed_query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.query(t)
    }
    fn embed_passages(&self, t: &[PythonText]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.passages(t)
    }
}
impl QueryEncoder for Words {
    fn embed_query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.query(t)
    }
}
impl DocumentEncoder for Words {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        self.inner.as_ref().map_or(Ok(4), |i| i.dim())
    }
    fn token_count(&self, t: &str) -> ken_retrieval::Result<usize> {
        self.inner.as_ref().map_or_else(
            || Ok(ken_retrieval::vocabulary::code_tokens_python(&t.into()).len()),
            |i| i.token_count(t),
        )
    }
    fn embed_passages(&self, t: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.passages(&t.iter().map(|s| PythonText::from(*s)).collect::<Vec<_>>())
    }
}
struct Context {
    control: Rc<Control>,
    spec: EncoderSpec,
    view: EncoderSpec,
    inner: Option<Rc<dyn ContextSourceEncoder>>,
}
fn basis(t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
    let t = t
        .to_utf8()
        .ok_or_else(|| RetrievalError::Invalid("scalar text required".into()))?;
    let mut v = vec![0.; 768];
    v[Sha256::digest(t.as_bytes())[0] as usize] = 2.;
    Ok(v)
}
impl QueryEncoder for Context {
    fn embed_query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.control.call(json!({"op":"context_query","text":t}));
        self.inner
            .as_ref()
            .map_or_else(|| basis(t), |i| i.embed_query(t))
    }
}
impl ContextSourceEncoder for Context {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn view_spec(&self) -> &EncoderSpec {
        &self.view
    }
    fn embed_passages(&self, t: &[PythonText]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.control
            .call(json!({"op":"context_passages","texts":t}));
        if *self.control.context_mode.borrow() == "error" {
            return Err(RetrievalError::Invalid(
                "context encoder unavailable".into(),
            ));
        }
        self.inner
            .as_ref()
            .map_or_else(|| t.iter().map(basis).collect(), |i| i.embed_passages(t))
    }
}
struct Neural {
    control: Rc<Control>,
    inner: Option<Rc<dyn PairedReranker>>,
}
impl PairedReranker for Neural {
    fn pair_fits(&self, q: &PythonText, t: &PythonText) -> ken_retrieval::Result<bool> {
        self.control
            .call(json!({"op":"pair_fits","query":q,"text":t}));
        self.inner.as_ref().map_or(
            Ok(q.codepoints().len() + t.codepoints().len() <= 10000),
            |i| i.pair_fits(q, t),
        )
    }
    fn score(&self, q: &PythonText, t: &[PythonText]) -> ken_retrieval::Result<NeuralScores> {
        self.control
            .call(json!({"op":"neural_score","query":q,"texts":t}));
        if *self.control.neural_mode.borrow() == "error" {
            return Err(RetrievalError::Invalid("neural unavailable".into()));
        }
        if let Some(i) = &self.inner {
            return i.score(q, t);
        }
        Ok(NeuralScores {
            scores: t
                .iter()
                .map(|s| (s.codepoints().len() % 19) as f64 / 4. - 9. / 4.)
                .collect(),
            details: json!({"model":"controlled-best-search","documents":t.len()}),
        })
    }
}
struct Provider {
    control: Rc<Control>,
    config: Models,
    real: Option<Rc<dyn Fn() -> ken_search::Result<SearchResourceInputs>>>,
    words: RefCell<Option<Rc<dyn SearchWords>>>,
}
impl SearchResourceProvider for Provider {
    fn build(&self) -> ken_search::Result<SearchResources> {
        self.control.call(json!({"op":"build_resources"}));
        let failures = self.control.resource_failures.get();
        if failures > 0 {
            self.control.resource_failures.set(failures - 1);
            return Err(RetrievalError::Invalid("resources unavailable".into()).into());
        }
        let m = &self.config;
        let mut inputs = if m.kind == "registered" {
            self.real
                .as_ref()
                .ok_or_else(|| RetrievalError::Invalid("registered provider required".into()))?(
            )?
        } else if m.kind == "controlled" {
            let identity = ContextModel::from_json(&m.context_registration.to_string())
                .map_err(RetrievalError::from)?
                .compatible_identity();
            let spec: EncoderSpec =
                serde_json::from_value(identity["spec"].clone()).map_err(RetrievalError::from)?;
            let context = m.profile.contextual.as_ref().expect("context policy");
            SearchResourceInputs {
                words: Rc::new(Words {
                    control: self.control.clone(),
                    spec: m.base_profile.identity.clone(),
                    inner: None,
                }),
                context: Rc::new(Context {
                    control: self.control.clone(),
                    spec,
                    view: context.view_model.clone().expect("views"),
                    inner: None,
                }),
                native_model: Arc::new(
                    NumericRanker::from_json(
                        &m.native_model.as_ref().expect("native forest").to_string(),
                    )
                    .map_err(RetrievalError::from)?,
                ),
                piece_model: Arc::new(
                    NumericRanker::from_json(
                        &m.piece_model.as_ref().expect("piece forest").to_string(),
                    )
                    .map_err(RetrievalError::from)?,
                ),
                neural: Rc::new(Neural {
                    control: self.control.clone(),
                    inner: None,
                }),
                expansion: ExpansionConfig {
                    expand_query: None,
                    revision: None,
                },
                base_profile: m.base_profile.clone(),
                profile: m.profile.clone(),
                legacy: m.legacy_runtime.clone(),
            }
        } else {
            return Err(RetrievalError::Invalid("unknown model control".into()).into());
        };
        if m.kind == "registered" {
            // The observer recorded config before replacing its controlled words.
            // Actual default_resources binds evidence to RegisteredStaticEncoder;
            // its immutable full fingerprint remains independently observed.
            let mut expected = m.profile.clone();
            expected
                .evidence
                .as_mut()
                .expect("evidence policy")
                .word_model = inputs.words.spec().clone();
            if inputs.base_profile != m.base_profile
                || inputs.profile != expected
                || inputs.legacy != m.legacy_runtime
            {
                return Err(
                    RetrievalError::Invalid("registered search policies differ".into()).into(),
                );
            }
            inputs.words = Rc::new(Words {
                control: self.control.clone(),
                spec: inputs.words.spec().clone(),
                inner: Some(inputs.words),
            });
            inputs.context = Rc::new(Context {
                control: self.control.clone(),
                spec: inputs.context.spec().clone(),
                view: inputs.context.view_spec().clone(),
                inner: Some(inputs.context),
            });
            inputs.neural = Rc::new(Neural {
                control: self.control.clone(),
                inner: Some(inputs.neural),
            });
        }
        let real = inputs.expansion.expand_query.take();
        let control = self.control.clone();
        let expansion = m.expansion.clone();
        inputs.expansion = ExpansionConfig {
            expand_query: Some(Rc::new(move |q| {
                control.call(json!({"op":"expand","query":q}));
                if *control.expansion_mode.borrow() == "error" {
                    return Err(RetrievalError::Invalid("expansion unavailable".into()));
                }
                if let Some(f) = &real {
                    f(q)
                } else {
                    Ok(expansion
                        .get(&q.to_utf8().unwrap_or_default())
                        .map_or(q.clone(), |s| s.as_str().into()))
                }
            })),
            revision: Some(m.expansion_revision.clone()),
        };
        *self.words.borrow_mut() = Some(inputs.words.clone());
        let resources = SearchResources::new(inputs)?;
        self.control.built.set(true);
        Ok(resources)
    }
}
struct Database {
    project: String,
    name: String,
    paths: ProjectPaths,
    db: ProjectDatabase,
}
struct Loader(Rc<dyn SearchWords>);
impl EncoderLoader for Loader {
    fn load(&self, s: &EncoderSpec) -> ken_retrieval::Result<Rc<dyn DocumentEncoder>> {
        if self.0.spec() != s {
            return Err(RetrievalError::Invalid("wrong source encoder".into()));
        }
        Ok(self.0.clone())
    }
}
fn error(e: SearchError) -> Value {
    let kind = match &e {
        SearchError::Retrieval(RetrievalError::Version(_))
        | SearchError::Index(ken_index::IndexError::Retrieval(RetrievalError::Version(_))) => {
            "IndexVersionError"
        }
        SearchError::Source(e) => e.kind(),
        _ => "ValueError",
    };
    json!({"type":kind,"message":e.to_string()})
}
pub fn observe(
    input: Input,
    grammars: Arc<GrammarCatalog>,
    real: Option<Rc<dyn Fn() -> ken_search::Result<SearchResourceInputs>>>,
) -> ProbeResult<Value> {
    let home = tempfile::tempdir()?;
    let control = Rc::new(Control::new(&input.models.controls));
    let provider = Rc::new(Provider {
        control: control.clone(),
        config: input.models.clone(),
        real,
        words: RefCell::new(None),
    });
    let mut engine = BestSearch::new(grammars.clone(), provider.clone());
    let registry = ParserRegistry::with_shared_catalog(grammars);
    let mut roots = BTreeMap::new();
    let mut databases = Vec::new();
    for p in input.projects {
        let root = home.path().join(&p.id);
        std::fs::create_dir_all(&root)?;
        let paths = ProjectPaths::at(
            &root,
            &DiscoveryContext {
                cwd: root.clone(),
                forced_root: None,
                home: None,
            },
        )?;
        for (path, text) in p.files {
            let path = root.join(path);
            std::fs::create_dir_all(path.parent().unwrap())?;
            std::fs::write(path, text)?;
        }
        roots.insert(p.id.clone(), root.clone());
        for (name, files) in p.databases {
            let mut db = ProjectDatabase::open(&root.join(format!("{name}.db")))?;
            db.initialize()?;
            if p.seed != "none" {
                Indexer::new(&registry).index_files(
                    &mut db,
                    &paths,
                    &files,
                    &IndexOptions {
                        retrieval_policy: Some(PassagePolicy::default()),
                        ..Default::default()
                    },
                    &mut |_: &str, _: &str| {},
                )?;
            }
            if p.seed == "files-only" {
                db.connection()
                    .execute_batch("DELETE FROM ci_passages; DELETE FROM ci_retrieval_files;")?;
            }
            databases.push(Database {
                project: p.id.clone(),
                name,
                paths: paths.clone(),
                db,
            });
        }
    }
    let mut events = Vec::new();
    for action in input.actions {
        control.calls.borrow_mut().clear();
        let result: ken_search::Result<Value> = (|| {
            Ok(match action {
                Action::Search {
                    project,
                    database,
                    request,
                } => {
                    let d = find(&mut databases, &project, &database)?;
                    serde_json::to_value(engine.search(&mut d.db, &d.paths, &request)?)
                        .map_err(RetrievalError::from)?
                }
                Action::Prepare { project, database } => {
                    let d = find(&mut databases, &project, &database)?;
                    serde_json::to_value(engine.prepare(&mut d.db, &d.paths)?)
                        .map_err(RetrievalError::from)?
                }
                Action::Write {
                    project,
                    path,
                    text,
                } => {
                    let path = roots[&project].join(path);
                    std::fs::create_dir_all(path.parent().unwrap())
                        .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
                    std::fs::write(path, text)
                        .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
                    Value::Null
                }
                Action::Reindex { project, database } => {
                    if !control.built.get() {
                        provider.build()?;
                    }
                    let d = find(&mut databases, &project, &database)?;
                    let config = &provider.config;
                    let loader = Rc::new(Loader(provider.words.borrow().as_ref().unwrap().clone()));
                    let files =
                        d.db.connection()
                            .prepare("SELECT path FROM ci_files ORDER BY path")?
                            .query_map([], |r| r.get::<_, String>(0).map(PathBuf::from))?
                            .collect::<rusqlite::Result<Vec<_>>>()?;
                    Indexer::new(&registry).index_files(
                        &mut d.db,
                        &d.paths,
                        &files,
                        &IndexOptions {
                            retrieval_profile: Some(config.base_profile.clone()),
                            retrieval_loader: Some(loader.clone()),
                            legacy_runtime: Some(config.legacy_runtime.clone()),
                            ..Default::default()
                        },
                        &mut |_: &str, _: &str| {},
                    )?;
                    index_embeddings(
                        &mut d.db,
                        config.base_profile.clone(),
                        config.legacy_runtime.clone(),
                        loader,
                    )?;
                    Value::Null
                }
                Action::CorruptProfile { project, database } => {
                    find(&mut databases, &project, &database)?
                        .db
                        .connection()
                        .execute(
                            "UPDATE meta SET value=?1 WHERE key='retrieval_profile_fingerprint'",
                            ["0".repeat(64)],
                        )?;
                    Value::Null
                }
                Action::OldExtractor { project, database } => {
                    find(&mut databases, &project, &database)?
                        .db
                        .connection()
                        .execute("UPDATE ci_retrieval_files SET extractor_version=0", [])?;
                    Value::Null
                }
                Action::ContextMode { mode } => {
                    *control.context_mode.borrow_mut() = mode;
                    Value::Null
                }
                Action::NeuralMode { mode } => {
                    *control.neural_mode.borrow_mut() = mode;
                    Value::Null
                }
                Action::ExpansionMode { mode } => {
                    *control.expansion_mode.borrow_mut() = mode;
                    Value::Null
                }
            })
        })();
        let mut event = match result {
            Ok(v) => json!({"result":v}),
            Err(e) => json!({"error":error(e)}),
        };
        event["calls"] = json!(control.calls.borrow().clone());
        let dbs=databases.iter().map(|d|->ProbeResult<Value>{
            let mut counts=BTreeMap::new();for table in ["ci_files","ci_passages","ci_passage_vectors","ci_retrieval_embeddings"] {counts.insert(table,d.db.connection().query_row(&format!("SELECT COUNT(*) FROM {table}"),[],|r|r.get::<_,i64>(0))?);}
            Ok(json!({"project":d.project,"database":d.name,"generation":generation(d.db.connection())?,"counts":counts,"profile_fingerprint":d.db.get_meta("retrieval_profile_fingerprint")?}))
        }).collect::<ProbeResult<Vec<_>>>()?;
        let prepared=engine.cached_projects().iter().map(|p|->ProbeResult<Value>{
            let d=databases.iter().find(|d|d.paths.root()==p.root && d.paths.root().join(format!("{}.db",d.name)).to_string_lossy()==p.database).ok_or("unknown prepared identity")?;
            Ok(json!({"project":d.project,"database":d.name,"generation":p.generation,"profile_fingerprint":p.profile_fingerprint,"descriptions":p.descriptions}))
        }).collect::<ProbeResult<Vec<_>>>()?;
        event["state"] = json!({"databases":dbs,"prepared":prepared});
        events.push(event);
    }
    Ok(json!(events))
}

fn find<'a>(
    databases: &'a mut [Database],
    p: &str,
    n: &str,
) -> ken_retrieval::Result<&'a mut Database> {
    databases
        .iter_mut()
        .find(|d| d.project == p && d.name == n)
        .ok_or_else(|| RetrievalError::Invalid("unknown history database".into()))
}

fn search_request<'de, D: serde::Deserializer<'de>>(
    d: D,
) -> std::result::Result<SearchRequest, D::Error> {
    let value = Value::deserialize(d)?;
    serde_json::from_str(&value.to_string()).map_err(serde::de::Error::custom)
}

#[cfg(test)]
#[allow(dead_code)]
pub fn controlled_provider(input: Input) -> Rc<dyn SearchResourceProvider> {
    let control = Rc::new(Control::new(&input.models.controls));
    Rc::new(Provider {
        control,
        config: input.models,
        real: None,
        words: RefCell::new(None),
    })
}

impl Input {
    #[allow(dead_code)]
    pub fn registered_runtime(&self) -> Option<LegacyRuntimeIdentity> {
        (self.models.kind == "registered").then(|| self.models.legacy_runtime.clone())
    }
}
