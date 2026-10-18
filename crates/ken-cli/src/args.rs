use clap::{Parser, Subcommand};
use std::{ffi::OsString, path::PathBuf};

#[derive(Parser)]
#[command(name = "ken-rs", version, about = "Inspect an existing Ken project")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    /// Report project, index and local daemon status
    Status {
        #[arg(default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        json: bool,
    },
}
#[derive(Debug)]
pub struct StatusArgs {
    pub path: PathBuf,
    pub json: bool,
}

pub fn parse_from(args: impl IntoIterator<Item = OsString>) -> Result<StatusArgs, clap::Error> {
    match Cli::try_parse_from(args)?.command {
        Command::Status { path, json } => Ok(StatusArgs { path, json }),
    }
}
