use clap::{Args, Parser, Subcommand, ValueEnum};
use std::{ffi::OsString, path::PathBuf};

#[derive(Parser)]
#[command(name = "ken-rs", version, about = "Explore an indexed Ken project")]
struct Cli {
    /// Native search resource manifest
    #[arg(long, global = true)]
    resources: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}
#[derive(Debug, Subcommand)]
pub enum Command {
    #[command(flatten)]
    Analysis(crate::analysis::AnalysisCommand),
    #[command(flatten)]
    Installation(crate::installation::InstallationCommand),
    #[command(flatten)]
    Package(crate::package::PackageCommand),
    #[command(flatten)]
    Memory(crate::memory::MemoryCommand),
    #[command(flatten)]
    Runtime(crate::runtime::RuntimeCommand),
    #[command(flatten)]
    Maintenance(crate::maintenance::MaintenanceCommand),
    /// Report project, index and local daemon status
    Status(StatusArgs),
    /// Search indexed files using the complete native search engine
    SearchFiles(SearchArgs),
    /// Search indexed symbols using the complete native search engine
    SearchSymbols(SearchArgs),
    /// Run native search and index navigation over MCP stdio
    Mcp(McpArgs),
    /// Read indexed code and relationships through the native tool surface
    Tools(ToolsArgs),
}
#[derive(Debug, Args)]
pub struct ToolsArgs {
    /// Project to discover before selecting a tool (default: current directory).
    #[arg(long, value_name = "PROJECT")]
    pub path: Option<PathBuf>,
    #[arg(long, global = true)]
    pub json: bool,
    #[arg(long, global = true)]
    pub compact: bool,
    #[arg(long)]
    pub list: bool,
    #[command(subcommand)]
    pub command: Option<ToolCommand>,
}
/// Compatibility project selection on tools which have no domain path parameter.
#[derive(Debug, Default, Args)]
pub struct ToolProjectPath {
    #[arg(long = "path", value_name = "PROJECT")]
    pub project_path: Option<PathBuf>,
}
#[derive(Debug, Subcommand)]
pub enum ToolCommand {
    #[command(flatten)]
    Knowledge(crate::tool_args::KnowledgeCommand),
    #[command(alias = "ken_read")]
    Read(ReadArgs),
    #[command(alias = "ken_related")]
    Related(RelatedArgs),
    #[command(alias = "ken_find")]
    Find(ToolFindArgs),
    /// Summarize project layout, import architecture or Git worktree changes
    #[command(alias = "ken_rank")]
    Rank(ToolRankArgs),
    /// Save and discover reusable KQL2 modules
    #[command(alias = "ken_query")]
    Query(QueryModuleArgs),
    /// Evaluate exact, bounded rational arithmetic
    #[command(alias = "ken_calculate")]
    Calculate(CalculateArgs),
    #[command(alias = "ken_rule")]
    Rule(RuleArgs),
    #[command(alias = "ken_check")]
    Check(CheckArgs),
}
#[derive(Debug, Args)]
pub struct RuleArgs {
    #[command(flatten)]
    pub project: ToolProjectPath,
    #[arg(long, default_value = "list")]
    pub action: String,
    #[arg(long, default_value = "")]
    pub rule_id: String,
    #[arg(long)]
    pub definition: Option<String>,
    #[arg(long, num_args=0..=1, default_missing_value="true", overrides_with="no_automatic")]
    pub automatic: Option<bool>,
    #[arg(long, overrides_with = "automatic")]
    pub no_automatic: bool,
    #[arg(long, default_value_t = 30000)]
    pub timeout_ms: u64,
    #[arg(long, overrides_with = "no_full")]
    pub full: bool,
    #[arg(long, overrides_with = "full")]
    pub no_full: bool,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct CheckArgs {
    #[arg(long,num_args=0..)]
    pub rules: Option<Vec<String>>,
    #[arg(long = "path", alias = "source-path", default_value = ".")]
    pub source_path: String,
    #[arg(long, default_value = "project")]
    pub scope: String,
    #[arg(long, default_value = "")]
    pub compare: String,
    #[arg(long, default_value = "")]
    pub run_id: String,
    #[arg(long, default_value_t = 10000)]
    pub timeout_ms: u64,
    #[arg(long, default_value_t = 100)]
    pub max_rows: u64,
    #[arg(long, overrides_with = "no_full")]
    pub full: bool,
    #[arg(long, overrides_with = "full")]
    pub no_full: bool,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct QueryModuleArgs {
    #[command(flatten)]
    pub project: ToolProjectPath,
    #[arg(long, default_value = "list")]
    pub action: String,
    #[arg(long, default_value = "")]
    pub module: String,
    #[arg(long, default_value = "")]
    pub source: String,
    #[arg(long)]
    pub description: Option<String>,
    #[arg(long)]
    pub expected_revision: Option<String>,
    #[arg(long, default_value = "")]
    pub prefix: String,
    #[arg(long, default_value_t = 50, allow_hyphen_values = true)]
    pub limit: i64,
    #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
    pub offset: i64,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct CalculateArgs {
    #[command(flatten)]
    pub project: ToolProjectPath,
    #[arg(allow_hyphen_values = true)]
    pub expression: String,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct ToolRankArgs {
    #[command(flatten)]
    pub project: ToolProjectPath,
    #[arg(long, default_value = "project")]
    pub scope: String,
    #[arg(default_value = "")]
    pub query: String,
    #[arg(long, default_value_t = 1, allow_hyphen_values = true)]
    pub verbose: i64,
    #[arg(long, overrides_with = "no_explain")]
    pub explain: bool,
    #[arg(long, overrides_with = "explain")]
    pub no_explain: bool,
    #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
    pub max_chars: i64,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct ReadArgs {
    #[command(flatten)]
    pub project: ToolProjectPath,
    pub file: String,
    #[arg(long,num_args=0..)]
    pub include: Option<Vec<String>>,
    #[arg(long, default_value = "")]
    pub qualname: String,
    #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
    pub start_line: i64,
    #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
    pub end_line: i64,
    #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
    pub max_chars: i64,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct RelatedArgs {
    pub target: String,
    pub relation: String,
    #[arg(long="path", aliases=["analysis-path","source-path"], default_value = ".")]
    pub analysis_path: String,
    #[arg(long, default_value = "")]
    pub from_path: String,
    #[arg(long, default_value_t = 10000.)]
    pub timeout_ms: f64,
    #[arg(long, default_value_t = 0.0, allow_hyphen_values = true)]
    pub min_confidence: f64,
    #[arg(long, default_value_t = 10, allow_hyphen_values = true)]
    pub limit: i64,
    #[arg(long, default_value_t = 1, allow_hyphen_values = true)]
    pub depth: i64,
    #[arg(long, overrides_with = "no_full")]
    pub full: bool,
    #[arg(long, overrides_with = "full")]
    pub no_full: bool,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct ToolFindArgs {
    #[arg(overrides_with = "query_flag")]
    pub query: Option<String>,
    #[arg(long = "query", overrides_with = "query")]
    pub query_flag: Option<String>,
    #[arg(long = "path", alias = "source-path", default_value = ".")]
    pub source_path: String,
    #[arg(long)]
    pub cache_mb: Option<f64>,
    #[arg(long)]
    pub timeout_ms: Option<u64>,
    #[arg(long, num_args=0..)]
    pub rules: Option<Vec<String>>,
    #[arg(long, num_args=0..)]
    pub collections: Option<Vec<String>>,
    #[arg(long, num_args=0..)]
    pub tags: Option<Vec<String>>,
    #[arg(long, num_args=0..)]
    pub rule_files: Option<Vec<String>>,
    #[arg(long)]
    pub saved_query: Option<String>,
    #[arg(long)]
    pub query_name: Option<String>,
    #[arg(long, default_value = "strict")]
    pub evidence_mode: String,
    #[arg(long)]
    pub libraries: Option<String>,
    #[arg(long, default_value = "files")]
    pub scope: String,
    #[arg(long, allow_hyphen_values = true)]
    pub limit: Option<isize>,
    #[arg(long, overrides_with = "no_literal")]
    pub literal: bool,
    #[arg(long, overrides_with = "literal")]
    pub no_literal: bool,
    #[arg(long, default_value = "")]
    pub language: String,
    #[arg(long, overrides_with = "no_full")]
    pub full: bool,
    #[arg(long, overrides_with = "full")]
    pub no_full: bool,
    #[arg(long, default_value = "auto")]
    pub purpose: String,
    #[arg(long, default_value_t = 12000, allow_hyphen_values = true)]
    pub max_chars: isize,
    #[arg(long, default_value = "auto")]
    pub piece_kind: String,
    #[arg(long, default_value = "auto")]
    pub response_format: String,
    #[arg(long, default_value = "kenql/1")]
    pub query_language: String,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
impl ToolCommand {
    pub(crate) fn project_path(&self) -> Option<&std::path::Path> {
        let project = match self {
            Self::Knowledge(command) => return command.project_path(),
            Self::Rule(a) => &a.project,
            Self::Query(a) => &a.project,
            Self::Calculate(a) => &a.project,
            Self::Read(a) => &a.project,
            Self::Rank(a) => &a.project,
            Self::Check(_) | Self::Related(_) | Self::Find(_) => return None,
        };
        project.project_path.as_deref()
    }
    pub(crate) fn source_path(&self) -> Option<&str> {
        match self {
            Self::Knowledge(command) => command.source_path(),
            Self::Check(a) => Some(&a.source_path),
            Self::Related(a) => Some(&a.analysis_path),
            Self::Find(a) => Some(&a.source_path),
            _ => None,
        }
    }
}
#[derive(Debug, Args)]
pub struct McpArgs {
    #[arg(default_value = ".")]
    pub path: PathBuf,
}
#[derive(Debug, Args)]
pub struct StatusArgs {
    #[arg(default_value = ".")]
    pub path: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum ResponseFormat {
    Auto,
    Legacy,
    Evidence,
    Compact,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum Purpose {
    Auto,
    Implementation,
    Usage,
    Tests,
    Documentation,
}
impl Purpose {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Implementation => "implementation",
            Self::Usage => "usage",
            Self::Tests => "tests",
            Self::Documentation => "documentation",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum PieceKind {
    Auto,
    Class,
    Module,
    Symbol,
    File,
}
impl PieceKind {
    pub fn as_str(self) -> Option<&'static str> {
        match self {
            Self::Auto => None,
            Self::Class => Some("class"),
            Self::Module => Some("module"),
            Self::Symbol => Some("symbol"),
            Self::File => Some("file"),
        }
    }
}
fn positive_budget(input: &str) -> Result<isize, String> {
    let value = input.parse::<isize>().map_err(|e| e.to_string())?;
    if value <= 0 {
        return Err("a positive output budget is required".into());
    }
    Ok(value)
}
#[derive(Debug, Args)]
pub struct SearchArgs {
    #[arg(required = true, num_args = 1..)]
    pub query: Vec<String>,
    #[arg(long, default_value = ".")]
    pub path: PathBuf,
    #[arg(short = 'n', long, default_value_t = 10, allow_hyphen_values = true)]
    pub limit: isize,
    #[arg(long)]
    pub json: bool,
    #[arg(long, value_enum, default_value = "auto")]
    pub response_format: ResponseFormat,
    #[arg(long, value_enum, default_value = "auto")]
    pub purpose: Purpose,
    #[arg(long, default_value="12000", value_parser=positive_budget, allow_hyphen_values=true)]
    pub max_chars: isize,
    #[arg(long, value_enum, default_value = "auto")]
    pub piece_kind: PieceKind,
}
pub struct Invocation {
    pub command: Command,
    pub resources: Option<PathBuf>,
}
pub fn parse_command_from(
    args: impl IntoIterator<Item = OsString>,
) -> Result<Invocation, clap::Error> {
    let cli = Cli::try_parse_from(args)?;
    Ok(Invocation {
        command: cli.command,
        resources: cli.resources,
    })
}

pub fn parse_from(args: impl IntoIterator<Item = OsString>) -> Result<StatusArgs, clap::Error> {
    match parse_command_from(args)?.command {
        Command::Status(args) => Ok(args),
        _ => Err(clap::Error::raw(
            clap::error::ErrorKind::InvalidSubcommand,
            "the status argument adapter requires the status command",
        )),
    }
}
