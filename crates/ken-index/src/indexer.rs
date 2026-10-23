//! Chunk preparation precedes publication; file transactions remain the durability boundary.
use crate::{
    DocumentEncoder, IndexError, IndexWriter, LegacyStores, PreparedFile, Result, SourceMetadata,
    WriterOptions,
    changes::{content_hash, is_unchanged},
    encode_pending,
    imports::resolve_missing_edges,
    parse_batch::{self, ParseJob},
    rebuild_name_tokens,
};
use ken_core::{project::ProjectPaths, source_reader::SourceFileReader};
use ken_models::{LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    LexicalCounter, PassagePolicy, TokenCounter,
    encoder::EncoderLoader,
    projections::{ProjectionIndexer, stored_profile},
    vocabulary::{NAME_TOKEN_VERSION, name_tokens},
};
use ken_store::ProjectDatabase;
use ken_syntax::ParserRegistry;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    os::unix::fs::MetadataExt,
    path::{Component, Path, PathBuf},
    rc::Rc,
    time::{Instant, SystemTime, UNIX_EPOCH},
};
pub const PARSER_VERSION: i64 = 10;
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct IndexStats {
    pub visited: usize,
    pub parsed: usize,
    pub unchanged: usize,
    pub skipped_no_lang: usize,
    pub skipped_too_large: usize,
    pub skipped_io_error: usize,
    pub symbols: usize,
    pub imports: usize,
    pub elapsed_s: f64,
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum VectorStorage {
    #[default]
    Automatic,
    Inline,
}
pub struct IndexOptions<'a> {
    pub max_file_bytes: u64,
    pub chunk_files: usize,
    pub workers: Option<usize>,
    pub legacy_encoder: Option<&'a dyn DocumentEncoder>,
    pub legacy_model: Option<&'a str>,
    pub vector_storage: VectorStorage,
    pub retrieval_policy: Option<PassagePolicy>,
    pub token_counter: Option<&'a dyn TokenCounter>,
    pub retrieval_profile: Option<RetrievalProfile>,
    pub retrieval_loader: Option<Rc<dyn EncoderLoader>>,
    pub legacy_runtime: Option<LegacyRuntimeIdentity>,
    pub parser_version: i64,
    pub now_ms: Option<&'a dyn Fn() -> i64>,
}
impl Default for IndexOptions<'_> {
    fn default() -> Self {
        Self {
            max_file_bytes: 1024 * 1024,
            chunk_files: 128,
            workers: None,
            legacy_encoder: None,
            legacy_model: None,
            vector_storage: VectorStorage::Automatic,
            retrieval_policy: None,
            token_counter: None,
            retrieval_profile: None,
            retrieval_loader: None,
            legacy_runtime: None,
            parser_version: PARSER_VERSION,
            now_ms: None,
        }
    }
}
pub trait Progress {
    fn file(&mut self, path: &str, status: &str);
    fn warning(&mut self, _message: &str) {}
}
impl<F: FnMut(&str, &str)> Progress for F {
    fn file(&mut self, path: &str, status: &str) {
        self(path, status)
    }
}
pub struct Indexer<'a> {
    parsers: &'a ParserRegistry,
}
fn now_ms() -> i64 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(value) => value.as_millis() as i64,
        Err(error) => -(error.duration().as_millis() as i64),
    }
}
fn path_text(path: &Path) -> Result<String> {
    let mut out = String::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::RootDir => out.push('/'),
            Component::ParentDir => {
                if !out.is_empty() && !out.ends_with('/') {
                    out.push('/')
                }
                out.push_str("..");
            }
            Component::Normal(part) => {
                let part = part.to_str().ok_or_else(|| {
                    IndexError::Invalid("source path cannot be bound as SQLite Unicode text".into())
                })?;
                if !out.is_empty() && !out.ends_with('/') {
                    out.push('/')
                }
                out.push_str(part);
            }
            Component::Prefix(_) => {
                return Err(IndexError::Invalid("unsupported source path prefix".into()));
            }
        }
    }
    if out.is_empty() {
        out.push('.')
    }
    Ok(out)
}
fn projection(
    conn: &rusqlite::Connection,
    options: &IndexOptions<'_>,
) -> Result<Option<ProjectionIndexer>> {
    if options.retrieval_profile.is_none()
        && (options.retrieval_policy.is_some() || stored_profile(conn)?.profile.is_none())
    {
        return Ok(None);
    }
    let runtime = options.legacy_runtime.clone().ok_or_else(|| {
        IndexError::Invalid(
            "active retrieval indexing requires an explicit legacy runtime identity".into(),
        )
    })?;
    let loader = options.retrieval_loader.clone().ok_or_else(|| {
        IndexError::Invalid("active retrieval indexing requires an encoder loader".into())
    })?;
    Ok(if let Some(profile) = &options.retrieval_profile {
        Some(ProjectionIndexer::new(
            conn,
            profile.clone(),
            runtime,
            loader,
        )?)
    } else {
        ProjectionIndexer::for_active(conn, runtime, loader)?
    })
}
struct Event {
    order: usize,
    path: String,
    status: &'static str,
}
struct PreparedChunk {
    files: Vec<PreparedFile>,
    events: Vec<Event>,
}
struct Preparation<'a> {
    reader: &'a SourceFileReader,
    policy: &'a PassagePolicy,
    counter: &'a dyn TokenCounter,
    options: &'a IndexOptions<'a>,
    workers: usize,
}
impl Indexer<'_> {
    pub fn new(parsers: &ParserRegistry) -> Indexer<'_> {
        Indexer { parsers }
    }
    pub fn index_files(
        &self,
        db: &mut ProjectDatabase,
        paths: &ProjectPaths,
        files: &[PathBuf],
        options: &IndexOptions<'_>,
        progress: &mut dyn Progress,
    ) -> Result<IndexStats> {
        if options.chunk_files == 0 {
            return Err(IndexError::Invalid("chunk size must be positive".into()));
        }
        let started = Instant::now();
        let mut stats = IndexStats::default();
        let projection = projection(db.connection(), options)?;
        let policy = projection
            .as_ref()
            .map(ProjectionIndexer::policy)
            .transpose()?
            .unwrap_or_else(|| options.retrieval_policy.clone().unwrap_or_default());
        let counter: &dyn TokenCounter = if let Some(projection) = &projection {
            projection
        } else {
            options.token_counter.unwrap_or(&LexicalCounter)
        };
        let project_name = paths
            .root()
            .file_name()
            .and_then(|s| s.to_str())
            .ok_or_else(|| {
                IndexError::Invalid("project name must be representable as Unicode text".into())
            })?;
        let stopwords = name_tokens(project_name, &BTreeSet::new());
        let rebuild = db.get_meta("name_token_version")?.as_deref()
            != Some(&NAME_TOKEN_VERSION.to_string())
            && db
                .connection()
                .query_row("SELECT EXISTS(SELECT 1 FROM ci_files)", [], |r| {
                    r.get::<_, bool>(0)
                })?;
        let workers = options.workers.unwrap_or_else(|| {
            let cpus = unsafe { libc::sysconf(libc::_SC_NPROCESSORS_ONLN) }.max(1) as usize;
            parse_batch::worker_count(
                files.len(),
                cpus,
                std::env::var("KEN_INDEX_WORKERS").ok().as_deref(),
            )
        });
        let stores =
            if options.vector_storage == VectorStorage::Automatic {
                if let Some(encoder) = options.legacy_encoder {
                    match encoder.dim().map_err(IndexError::from).and_then(|dim| {
                        LegacyStores::open(&paths.vectors(), dim, options.legacy_model)
                    }) {
                        Ok(stores) => Some(stores),
                        Err(error) => {
                            progress.warning(&format!(
                                "vector store unavailable; writing inline embeddings: {error}"
                            ));
                            None
                        }
                    }
                } else {
                    None
                }
            } else {
                None
            };
        let reader = SourceFileReader::new(paths)?;
        let context = Preparation {
            reader: &reader,
            policy: &policy,
            counter,
            options,
            workers,
        };
        let writer = WriterOptions {
            stores: stores.as_ref(),
            stopwords: &stopwords,
            policy: &policy,
            now_ms: options.now_ms.unwrap_or(&now_ms),
            parser_version: options.parser_version,
        };
        for chunk in files.chunks(options.chunk_files) {
            let mut prepared = self.prepare(db, chunk, &context, &mut stats)?;
            if let Some(encoder) = options.legacy_encoder {
                encode_pending(&mut prepared.files, encoder)?;
            }
            if let Some(projection) = &projection
                && !prepared.files.is_empty()
            {
                let passages: Vec<_> = prepared
                    .files
                    .iter()
                    .map(|f| f.passages.as_slice())
                    .collect();
                let views = projection.prepare(db.connection(), &passages)?;
                for (file, view) in prepared.files.iter_mut().zip(views) {
                    file.projection = Some(view);
                    let current = reader.open(Path::new(&file.source.path))?.read()?;
                    if format!("{:x}", Sha256::digest(&current)) != file.source_sha256 {
                        return Err(ken_retrieval::RetrievalError::Version(
                            "source changed while encoding; retry indexing".into(),
                        )
                        .into());
                    }
                }
            }
            for file in prepared.files {
                IndexWriter::publish(db, &file, &writer)?;
                let status = if let Some(parsed) = &file.parsed {
                    stats.parsed += 1;
                    stats.symbols += parsed.symbols.len();
                    stats.imports += parsed.imports.len();
                    "indexed"
                } else {
                    stats.skipped_no_lang += 1;
                    "indexed:noparse"
                };
                prepared.events.push(Event {
                    order: file.source.order,
                    path: file.source.path,
                    status,
                });
            }
            if let Some(stores) = &stores {
                stores.flush()?;
            }
            prepared.events.sort_by_key(|e| e.order);
            for e in prepared.events {
                progress.file(&e.path, e.status);
            }
        }
        stats.elapsed_s = started.elapsed().as_secs_f64();
        resolve_missing_edges(db.connection(), Some(paths.root()))?;
        if rebuild {
            rebuild_name_tokens(db.connection(), &stopwords)?;
        } else {
            db.set_meta("name_token_version", &NAME_TOKEN_VERSION.to_string())?;
        }
        Ok(stats)
    }
    fn prepare(
        &self,
        db: &ProjectDatabase,
        chunk: &[PathBuf],
        context: &Preparation<'_>,
        stats: &mut IndexStats,
    ) -> Result<PreparedChunk> {
        let mut files = Vec::new();
        let mut events = Vec::new();
        let mut jobs = Vec::new();
        let mut awaiting = Vec::new();
        for (order, path) in chunk.iter().enumerate() {
            stats.visited += 1;
            let relative = path_text(path)?;
            let opened = match context.reader.open(path) {
                Ok(opened) => opened,
                Err(_) => {
                    stats.skipped_io_error += 1;
                    events.push(Event {
                        order,
                        path: relative,
                        status: "skipped:io_error",
                    });
                    continue;
                }
            };
            let metadata = match opened.metadata() {
                Ok(metadata) => metadata,
                Err(_) => {
                    stats.skipped_io_error += 1;
                    events.push(Event {
                        order,
                        path: relative,
                        status: "skipped:io_error",
                    });
                    continue;
                }
            };
            if metadata.len() > context.options.max_file_bytes {
                stats.skipped_too_large += 1;
                events.push(Event {
                    order,
                    path: relative,
                    status: "skipped:too_large",
                });
                continue;
            }
            let detected = self.parsers.detect(path, None)?;
            let bytes = match opened.read() {
                Ok(bytes) => bytes,
                Err(_) => {
                    stats.skipped_io_error += 1;
                    events.push(Event {
                        order,
                        path: relative,
                        status: "skipped:io_error",
                    });
                    continue;
                }
            };
            let hash = content_hash(&bytes);
            let language = if detected.is_some() {
                self.parsers.detect(path, Some(&bytes))?
            } else {
                None
            };
            if is_unchanged(
                db.connection(),
                &relative,
                &hash,
                context.options.legacy_encoder.is_some(),
                context.options.parser_version,
                context.policy,
            )? {
                stats.unchanged += 1;
                events.push(Event {
                    order,
                    path: relative,
                    status: "unchanged",
                });
                continue;
            }
            let mtime =
                (metadata.mtime() as i128) * 1_000_000_000 + (metadata.mtime_nsec() as i128);
            let source = SourceMetadata {
                path: relative.clone(),
                language: language.map(|l| l.as_str().into()),
                content_hash: hash,
                mtime_ns: i64::try_from(mtime).map_err(|_| {
                    IndexError::Invalid(
                        "source modification time exceeds SQLite integer range".into(),
                    )
                })?,
                order,
            };
            if let Some(language) = language {
                awaiting.push(source);
                jobs.push(ParseJob {
                    language,
                    path: relative,
                    bytes,
                });
            } else {
                files.push(PreparedFile::new(
                    source,
                    &bytes,
                    None,
                    context.policy,
                    context.counter,
                )?);
            }
        }
        let parsed = parse_batch::parse_all(self.parsers, &jobs, context.workers);
        for ((source, job), parsed) in awaiting.into_iter().zip(&jobs).zip(parsed) {
            if let Some(parsed) = parsed {
                files.push(PreparedFile::new(
                    source,
                    &job.bytes,
                    Some(parsed),
                    context.policy,
                    context.counter,
                )?);
            } else {
                stats.skipped_io_error += 1;
                events.push(Event {
                    order: source.order,
                    path: source.path,
                    status: "skipped:parse_error",
                });
            }
        }
        Ok(PreparedChunk { files, events })
    }
}
