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
    /// Report project, index and local daemon status
    Status(StatusArgs),
    /// Search indexed files using the complete native search engine
    SearchFiles(SearchArgs),
    /// Search indexed symbols using the complete native search engine
    SearchSymbols(SearchArgs),
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
