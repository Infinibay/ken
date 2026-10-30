//! Native package operations; explicit source identity and prefix are required.
use crate::status::CommandOutput;
use clap::Subcommand;
use ken_application::package::PackageApplication;
use ken_core::project::DiscoveryContext;
use std::path::{Path, PathBuf};
#[derive(Debug, Subcommand)]
pub enum PackageCommand {
    /// Authenticate and manage versioned native releases
    Package {
        #[command(subcommand)]
        command: PackageAction,
    },
}
#[derive(Debug, Subcommand)]
pub enum PackageAction {
    Authenticate {
        bundle: PathBuf,
        #[arg(long)]
        json: bool,
    },
    Install {
        bundle: PathBuf,
        #[arg(long)]
        manifest_sha256: String,
        #[arg(long)]
        prefix: PathBuf,
        #[arg(long)]
        json: bool,
    },
    Rollback {
        #[arg(long)]
        prefix: PathBuf,
        #[arg(long)]
        json: bool,
    },
    Status {
        #[arg(long)]
        prefix: PathBuf,
        #[arg(long)]
        json: bool,
    },
}
fn absolute(path: &Path, context: &DiscoveryContext) -> PathBuf {
    if path.is_absolute() {
        path.into()
    } else {
        context.cwd.join(path)
    }
}
pub fn run(
    command: PackageCommand,
    context: &DiscoveryContext,
) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    let result = (|| -> Result<CommandOutput, Box<dyn std::error::Error>> {
        let PackageCommand::Package { command } = command;
        let (value, json) = match command {
            PackageAction::Authenticate { bundle, json } => {
                let app = PackageApplication::new(&context.cwd)?;
                (
                    serde_json::to_value(app.authenticate(&absolute(&bundle, context))?)?,
                    json,
                )
            }
            PackageAction::Install {
                bundle,
                manifest_sha256,
                prefix,
                json,
            } => {
                let app = PackageApplication::new(&absolute(&prefix, context))?;
                (
                    serde_json::to_value(
                        app.install(&absolute(&bundle, context), &manifest_sha256)?,
                    )?,
                    json,
                )
            }
            PackageAction::Rollback { prefix, json } => {
                let app = PackageApplication::new(&absolute(&prefix, context))?;
                (serde_json::to_value(app.rollback()?)?, json)
            }
            PackageAction::Status { prefix, json } => {
                let app = PackageApplication::new(&absolute(&prefix, context))?;
                (serde_json::to_value(app.status()?)?, json)
            }
        };
        let stdout = if json {
            serde_json::to_string_pretty(&value)? + "\n"
        } else if let Some(digest) = value["manifest_sha256"].as_str() {
            format!("authenticated native package {digest}\n")
        } else if let Some(digest) = value["current_release"].as_str() {
            format!("active native release {digest}\n")
        } else {
            "no owned native release is active\n".into()
        };
        Ok(CommandOutput {
            code: 0,
            stdout,
            stderr: String::new(),
        })
    })();
    Ok(result.unwrap_or_else(|error| CommandOutput {
        code: 1,
        stdout: String::new(),
        stderr: format!("error: {error}\n"),
    }))
}
