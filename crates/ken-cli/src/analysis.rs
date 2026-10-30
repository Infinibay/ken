//! Query authoring and structural inspection compose the same native applications.
use crate::status::CommandOutput;
use clap::{Args, Subcommand, ValueEnum};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    tool_output::{Document, render},
};
use ken_structural::{
    NativeFrontend, ProjectAcquisition, ProjectBuilder, ScanLimits,
    application::{
        catalog::{Catalog, RuleLibrary, SavedRule},
        exploration::{ExplorationOptions, PatternBackend, PatternOptions, SyntaxExploration},
        modules::{ModuleRegistry, ModuleResolver, validate_entry},
        search::{SearchOptions, SearchRequest, StructuralApplication, present},
        sessions::{QueryApplication, QueryOptions, SessionOptions},
    },
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[derive(Debug, Subcommand)]
pub enum AnalysisCommand {
    Kql2(Kql2Args),
    Structural(StructuralArgs),
}
#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum Backend {
    Indexed,
    Exploration,
}
impl Backend {
    fn name(self) -> &'static str {
        match self {
            Self::Indexed => "indexed",
            Self::Exploration => "exploration",
        }
    }
}
#[derive(Debug, Args)]
pub struct Kql2Args {
    pub query_file: Option<PathBuf>,
    #[arg(long)]
    pub saved: Option<String>,
    #[arg(long)]
    pub save: bool,
    #[arg(long)]
    pub description: Option<String>,
    #[arg(long)]
    pub expected_revision: Option<String>,
    #[arg(long)]
    pub explain: bool,
    #[arg(long)]
    pub capabilities: bool,
    #[arg(long)]
    pub json: bool,
    #[arg(long, default_value = ".")]
    pub root: PathBuf,
    #[arg(long, default_value = ".")]
    pub path: PathBuf,
    #[arg(long)]
    pub query: Option<String>,
    #[arg(long)]
    pub cache_mb: Option<f64>,
    #[arg(long)]
    pub timeout_ms: Option<f64>,
    #[arg(long)]
    pub max_states: Option<u64>,
    #[arg(long)]
    pub max_rows: Option<u64>,
    #[arg(long = "library")]
    pub libraries: Vec<PathBuf>,
    #[arg(long)]
    pub reference: bool,
    #[arg(long, value_enum, default_value = "indexed")]
    pub backend: Backend,
    #[arg(long)]
    pub cache_directory: Option<PathBuf>,
    #[arg(long)]
    pub profile: bool,
}
#[derive(Debug, Args)]
pub struct StructuralArgs {
    #[arg(long, default_value = ".", global = true)]
    pub path: PathBuf,
    #[arg(long, default_value = ".", global = true)]
    pub scope: PathBuf,
    #[arg(long, global = true)]
    pub json: bool,
    #[arg(long, global = true)]
    pub cache_mb: Option<f64>,
    #[arg(long, global = true)]
    pub limit: Option<u64>,
    #[arg(long, global = true)]
    pub timeout_ms: Option<u64>,
    #[arg(long, global = true)]
    pub max_states: Option<u64>,
    #[arg(long, global = true)]
    pub max_rows: Option<u64>,
    #[arg(long, global = true)]
    pub max_files: Option<usize>,
    #[arg(long, default_value_t = 2_000_000, global = true)]
    pub max_file_bytes: u64,
    #[command(subcommand)]
    pub command: StructuralCommand,
}
#[derive(Debug, Default, Args)]
pub struct RuleSelection {
    #[arg(long = "rule")]
    pub rules: Vec<String>,
    #[arg(long = "collection")]
    pub collections: Vec<String>,
    #[arg(long = "tag")]
    pub tags: Vec<String>,
    #[arg(long = "rules-file")]
    pub rule_files: Vec<PathBuf>,
}
#[derive(Debug, Args)]
pub struct QuerySource {
    #[arg(long, conflicts_with = "query_file")]
    pub query: Option<String>,
    #[arg(long, conflicts_with = "query")]
    pub query_file: Option<PathBuf>,
    #[arg(long, default_value = "strict")]
    pub evidence_mode: String,
}
#[derive(Debug, Subcommand)]
pub enum StructuralCommand {
    Ir {
        #[arg(long, default_value = "query")]
        view: String,
        #[arg(long, default_value = "compact")]
        format: String,
        #[arg(long, default_value = "")]
        symbol: String,
    },
    Search {
        #[command(flatten)]
        source: QuerySource,
        #[command(flatten)]
        selection: RuleSelection,
        #[arg(long)]
        full: bool,
    },
    Patterns {
        #[arg(long = "pattern")]
        names: Vec<String>,
        #[arg(long, value_enum, default_value = "exploration")]
        backend: Backend,
        #[arg(long)]
        cache_directory: Option<PathBuf>,
        #[arg(long)]
        profile: bool,
        #[arg(long)]
        full: bool,
    },
    Bugs {
        #[arg(long)]
        full: bool,
    },
    Catalog,
    Rules {
        #[command(flatten)]
        selection: RuleSelection,
    },
    SaveRule {
        id: String,
        #[command(flatten)]
        source: QuerySource,
        #[arg(long, default_value = "")]
        name: String,
        #[arg(long, default_value = "")]
        description: String,
        #[arg(long = "tag")]
        tags: Vec<String>,
        #[arg(long = "collection")]
        collections: Vec<String>,
        #[arg(long)]
        severity: Option<String>,
        #[arg(long, default_value = "")]
        recommendation: String,
        #[arg(long)]
        overwrite: bool,
    },
}
fn document(value: Value) -> Document {
    match value {
        Value::Null => Document::Null,
        Value::Bool(v) => Document::Bool(v),
        Value::Number(v) => Document::Number(v),
        Value::String(v) => Document::String(v),
        Value::Array(v) => Document::Array(v.into_iter().map(document).collect()),
        Value::Object(v) => {
            Document::Object(v.into_iter().map(|(k, v)| (k, document(v))).collect())
        }
    }
}
fn emit(raw: String, json: bool, full: bool) -> CommandOutput {
    let text = if json {
        raw
    } else {
        match serde_json::from_str::<Value>(&raw) {
            Ok(value) => render(&document(value), "analysis", full),
            Err(_) => raw,
        }
    };
    CommandOutput {
        code: 0,
        stdout: text + "\n",
        stderr: String::new(),
    }
}
fn source_file(path: &Path) -> Result<String> {
    let limit = ken_query::ParseLimits::default().max_bytes;
    let mut source = String::new();
    std::fs::File::open(path)?
        .take(limit as u64 + 1)
        .read_to_string(&mut source)?;
    if source.len() > limit {
        return Err("query source byte budget exhausted".into());
    }
    Ok(source)
}
fn query_source(source: &QuerySource) -> Result<String> {
    match (&source.query, &source.query_file) {
        (Some(query), None) => Ok(query.clone()),
        (None, Some(path)) => source_file(path),
        (None, None) => Ok(String::new()),
        _ => Err("choose query or query-file, not both".into()),
    }
}
fn libraries(paths: &[PathBuf]) -> Result<BTreeMap<String, String>> {
    let mut libraries = BTreeMap::new();
    for path in paths {
        let source = source_file(path)?;
        let tree = ken_query::parse(&source, &path.to_string_lossy(), Default::default())?;
        if libraries.insert(tree.module.clone(), source).is_some() {
            return Err(format!("duplicate library module: {}", tree.module).into());
        }
    }
    Ok(libraries)
}
fn compiled(
    resolved: &ken_structural::application::modules::ResolvedQuery,
) -> Result<ken_query::CompiledQuery> {
    let tree = ken_query::parse(&resolved.source, "<query>", Default::default())?;
    let libraries = resolved
        .libraries()
        .iter()
        .map(|(name, source)| {
            Ok((
                name.clone(),
                ken_query::parse(source, name, Default::default())?,
            ))
        })
        .collect::<std::result::Result<BTreeMap<_, _>, ken_query::ParseError>>()?;
    Ok(ken_query::compile(
        &tree,
        resolved.query_name.as_deref(),
        &libraries,
        Default::default(),
    )?)
}
fn kql2(args: Kql2Args, installation: &Path, context: &DiscoveryContext) -> Result<CommandOutput> {
    if args.capabilities {
        return Ok(emit(
            ken_query::authoring::capabilities().to_string(),
            args.json,
            args.profile || args.explain,
        ));
    }
    let root = context.cwd.join(&args.root);
    let source = args.query_file.as_deref().map(source_file).transpose()?;
    validate_entry(source.as_deref(), args.saved.as_deref())?;
    if args.save {
        if source.is_none() || args.explain || !args.libraries.is_empty() {
            return Err("--save requires a module file and cannot be combined with --explain or --library; save imports first".into());
        }
        let saved = ModuleRegistry::new(&root)?.save(
            source.as_deref().unwrap(),
            args.description.as_deref(),
            args.expected_revision.as_deref(),
        )?;
        return Ok(emit(serde_json::to_string_pretty(&saved)?, true, false));
    }
    if args.description.is_some() || args.expected_revision.is_some() {
        return Err("--description and --expected-revision require --save".into());
    }
    let catalog = Catalog::packaged()?;
    let supplied = libraries(&args.libraries)?;
    let mut resolver = ModuleResolver::new(&root, catalog.libraries().clone());
    let resolved = resolver.resolve(
        source.as_deref(),
        args.saved.as_deref(),
        args.query.as_deref(),
        Some(&supplied),
    )?;
    resolver.close()?;
    let program = compiled(&resolved)?;
    let explanation = ken_query::authoring::explain(&program, args.backend.name())?;
    if args.explain {
        return Ok(emit(explanation.to_string(), args.json, true));
    }
    let grammars = Arc::new(ken_search::SearchInstallation::open_grammars(installation)?);
    let service = StructuralApplication::new(&root, grammars.clone())?;
    let capacity = service.cache_capacity(args.cache_mb)?;
    let raw = match args.backend {
        Backend::Exploration => SyntaxExploration::new(
            &root,
            grammars,
            catalog.libraries().clone(),
            args.cache_directory,
        )?
        .search_json(
            source.as_deref(),
            ExplorationOptions {
                path: args.path,
                cache_mb: capacity,
                saved_query: args.saved,
                query_name: args.query,
                libraries: Some(supplied),
                reference: args.reference,
                profile: args.profile,
                timeout_ms: args.timeout_ms,
                max_states: args.max_states,
                max_rows: args.max_rows,
                ..Default::default()
            },
        )?,
        Backend::Indexed => {
            let app = QueryApplication::new_with_cache_directory(
                &root,
                grammars,
                catalog.libraries().clone(),
                args.cache_directory,
            )?;
            let options = SessionOptions {
                path: args.path,
                cache_mb: capacity,
                ..Default::default()
            };
            let mut session = if capacity == 0. {
                app.open_transient(options)?
            } else {
                app.open(options)?
            };
            let raw = session.search_json(
                source.as_deref(),
                QueryOptions {
                    saved_query: args.saved,
                    query_name: args.query,
                    libraries: Some(supplied),
                    reference: args.reference,
                    profile: args.profile,
                    timeout_ms: args.timeout_ms,
                    max_states: args.max_states,
                    max_rows: args.max_rows,
                    ..Default::default()
                },
            )?;
            session.close()?;
            raw
        }
    };
    let observation = ken_contracts::checks::Observation::parse(&raw)?;
    let complete = observation.admission().complete == Some(true);
    let raw = if args.json || args.profile {
        raw
    } else {
        ken_contracts::checks::query_report(&observation, false)?
            .json()
            .to_owned()
    };
    let mut output = emit(raw, args.json, args.profile);
    output.code = if complete { 0 } else { 3 };
    Ok(output)
}
fn structural(
    args: StructuralArgs,
    installation: &Path,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    let root = context.cwd.join(&args.path);
    let catalog = Catalog::packaged()?;
    match &args.command {
        StructuralCommand::Catalog => {
            let patterns = catalog.pattern_catalog();
            let bugs = catalog
                .rules()
                .iter()
                .filter(|r| r.collections.iter().any(|c| c == "bugs"))
                .map(|r| {
                    (
                        r.id.clone(),
                        json!({"description":r.description,"severity":r.severity}),
                    )
                })
                .collect::<serde_json::Map<_, _>>();
            return Ok(emit(
                json!({"patterns":patterns,"bugs":bugs}).to_string(),
                args.json,
                false,
            ));
        }
        StructuralCommand::Rules { selection } => {
            let library = RuleLibrary::load(&root, &catalog, &selection.rule_files)?;
            let rules =
                library.select(&selection.rules, &selection.collections, &selection.tags)?;
            return Ok(emit(json!({"rules":rules}).to_string(), args.json, false));
        }
        StructuralCommand::SaveRule {
            id,
            source,
            name,
            description,
            tags,
            collections,
            severity,
            recommendation,
            overwrite,
        } => {
            let query = query_source(source)?;
            if query.is_empty() {
                return Err("save-rule requires --query or --query-file".into());
            }
            let rule = SavedRule {
                id: id.clone(),
                query,
                name: name.clone(),
                description: description.clone(),
                tags: tags.clone(),
                collections: collections.clone(),
                severity: severity.clone(),
                recommendation: recommendation.clone(),
                ..Default::default()
            };
            let path = RuleLibrary::packaged(&catalog)?.save(&root, &rule, *overwrite)?;
            return Ok(emit(
                json!({"ok":true,"path":path,"rule":rule}).to_string(),
                args.json,
                false,
            ));
        }
        _ => {}
    }
    let grammars = Arc::new(ken_search::SearchInstallation::open_grammars(installation)?);
    let cache_directory = if let StructuralCommand::Patterns {
        cache_directory, ..
    } = &args.command
    {
        cache_directory.clone()
    } else {
        None
    };
    let service = StructuralApplication::new_with_cache_directory(
        &root,
        grammars.clone(),
        cache_directory.clone(),
    )?;
    let capacity = service.cache_capacity(args.cache_mb)?;
    let mut options = SearchOptions {
        path: args.scope.clone(),
        cache_mb: Some(capacity),
        limits: ScanLimits {
            max_files: args.max_files,
            max_file_bytes: args.max_file_bytes,
        },
        ..Default::default()
    };
    options.budget.max_matches = args.limit;
    options.budget.timeout_ms = args.timeout_ms;
    options.budget.max_states = args.max_states;
    options.budget.max_rows = args.max_rows;
    let (response, kind, full) = match args.command {
        StructuralCommand::Search {
            source,
            selection,
            full,
        } => {
            options.evidence_mode = match source.evidence_mode.as_str() {
                "strict" => ken_query::execution::EvidenceMode::Strict,
                "possible" => ken_query::execution::EvidenceMode::Possible,
                _ => return Err("evidence-mode must be strict or possible".into()),
            };
            (
                service.search(
                    SearchRequest {
                        query: query_source(&source)?,
                        rules: selection.rules,
                        collections: selection.collections,
                        tags: selection.tags,
                        rule_files: selection.rule_files,
                    },
                    options,
                )?,
                "structure",
                full,
            )
        }
        StructuralCommand::Patterns {
            names,
            backend,
            profile,
            full,
            ..
        } => (
            service.patterns_with_options(
                &names,
                PatternOptions {
                    search: options,
                    backend: match backend {
                        Backend::Indexed => PatternBackend::Indexed,
                        Backend::Exploration => PatternBackend::Exploration,
                    },
                    profile,
                },
            )?,
            "patterns",
            full || profile,
        ),
        StructuralCommand::Bugs { full } => (service.bugs(options)?, "bugs", full),
        StructuralCommand::Ir {
            view,
            format,
            symbol,
        } => {
            if !matches!(view.as_str(), "source" | "query" | "instructions")
                || !matches!(format.as_str(), "compact" | "json" | "text")
            {
                return Err("invalid IR view or format".into());
            }
            if format == "text" && view != "instructions" {
                return Err("--format text requires --view instructions".into());
            }
            let paths = ProjectPaths::at(&root, context)?;
            let frontend = NativeFrontend::new(&grammars);
            let cache = ken_store::artifact_cache::ArtifactCache::open(
                &paths.root().join(".ken/structural-cache.sqlite"),
                capacity,
            )?;
            let mut builder = ProjectBuilder::new(paths.clone(), context.clone(), &frontend, cache);
            let project = ProjectAcquisition::new(
                &mut builder,
                &paths.root().join(".ken/structural/v2/ir.sqlite"),
                capacity > 0.,
            )
            .acquire(&args.scope, options.limits, || Ok(()))?;
            let source = project.source_graph(|| Ok(()))?;
            let analysis = project.analysis.clone();
            project.close()?;
            if view == "instructions" {
                let mut program = ken_program::instructions::lower(&source)?;
                if !symbol.is_empty() {
                    program.functions.retain(|f| f.name == symbol);
                }
                if !args.json && format != "json" {
                    return Ok(CommandOutput {
                        code: 0,
                        stdout: program.format()?,
                        stderr: String::new(),
                    });
                }
                return Ok(emit(
                    json!({"ok":true,"ir":program,"analysis":analysis}).to_string(),
                    true,
                    false,
                ));
            }
            let mut graph = if view == "query" {
                ken_program::query_view::normalize_query_graph(&source)?
            } else {
                source
            };
            if !symbol.is_empty() {
                let roots = graph
                    .entities
                    .iter()
                    .filter(|(_, e)| e.name == symbol)
                    .map(|(id, _)| id.clone())
                    .collect::<Vec<_>>();
                let selected = graph
                    .entities
                    .iter()
                    .filter(|(id, _)| {
                        roots
                            .iter()
                            .any(|r| id == r || id.starts_with(&format!("{r}/")))
                    })
                    .map(|(id, _)| id.clone())
                    .collect::<BTreeSet<_>>();
                graph.entities.retain(|(id, _)| selected.contains(id));
                graph.operations.retain(|op| selected.contains(&op.owner));
                graph.facts.retain(|fact| {
                    selected.contains(&fact.subject) || selected.contains(&fact.object)
                });
            }
            return Ok(emit(
                json!({"ok":true,"ir":graph,"analysis":analysis}).to_string(),
                args.json || format == "json",
                false,
            ));
        }
        _ => unreachable!("cold commands handled before grammar acquisition"),
    };
    let result = present(&response, kind, full);
    let mut output = emit(result.to_string(), args.json, full);
    if let Some(incomplete) = result.get("incomplete").and_then(Value::as_object)
        && !incomplete.is_empty()
    {
        output.stderr = format!(
            "warning: {} rule(s) did not finish and their result is incomplete: {}\n",
            incomplete.len(),
            incomplete.keys().cloned().collect::<Vec<_>>().join(", ")
        );
    }
    Ok(output)
}
pub fn run(
    command: AnalysisCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    let is_kql = matches!(&command, AnalysisCommand::Kql2(_));
    let json = match &command {
        AnalysisCommand::Kql2(a) => a.json,
        AnalysisCommand::Structural(a) => a.json,
    };
    let result = match command {
        AnalysisCommand::Kql2(args) => kql2(args, &installation, context),
        AnalysisCommand::Structural(args) => structural(args, &installation, context),
    };
    match result {
        Ok(output) => Ok(output),
        Err(error) if is_kql => Ok(CommandOutput {
            code: 2,
            stdout: String::new(),
            stderr: if json {
                json!({"error":error.to_string()}).to_string() + "\n"
            } else {
                format!("error: {error}\n")
            },
        }),
        Err(error) => Err(error),
    }
}
