//! Thin native installation commands; package, project and host policy have owners.
use crate::status::CommandOutput;
use clap::{Args, Subcommand};
use ken_application::installation::{
    self as project, DaemonLifecycle, InstallOptions, ProjectInstallation, UninstallOptions,
};
use ken_core::project::DiscoveryContext;
use ken_hosts::{HostSelection, NativeCommand};
use ken_retrieval::project_embeddings::{ProjectEmbeddings, TransformerOverrides};
use ken_syntax::GrammarCatalog;
use std::{
    collections::BTreeMap,
    ffi::OsString,
    path::{Path, PathBuf},
    process::Command,
    rc::Rc,
    sync::Arc,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[derive(Debug, Subcommand)]
pub enum InstallationCommand {
    /// Provision a native project and index sources; model inference is optional
    Install(InstallArgs),
    /// Remove unchanged owned host configuration and optionally project data
    Uninstall(UninstallArgs),
    /// Authenticate and activate a native bundle, then reapply project installation
    Reinstall(ReinstallArgs),
}
#[derive(Clone, Debug, Default, Args)]
pub struct InstallFlags {
    #[arg(long)]
    pub claude: bool,
    #[arg(long)]
    pub codex: bool,
    #[arg(long)]
    pub opencode: bool,
    #[arg(long)]
    pub deepseek: bool,
    #[arg(long)]
    pub embed: bool,
    #[arg(long, allow_hyphen_values = true)]
    pub embed_limit: Option<i64>,
    #[arg(long)]
    pub no_wire: bool,
    #[arg(long, conflicts_with = "no_agents_md")]
    pub agents_md: bool,
    #[arg(long, conflicts_with = "agents_md")]
    pub no_agents_md: bool,
}
#[derive(Debug, Args)]
pub struct InstallArgs {
    #[arg(default_value = ".")]
    pub path: PathBuf,
    #[arg(short = 'q', long)]
    pub quiet: bool,
    #[arg(long)]
    pub json: bool,
    #[command(flatten)]
    pub flags: InstallFlags,
}
#[derive(Debug, Args)]
pub struct UninstallArgs {
    #[arg(default_value = ".")]
    pub path: PathBuf,
    #[arg(long)]
    pub keep_db: bool,
    #[arg(short = 'q', long)]
    pub quiet: bool,
    #[arg(long)]
    pub json: bool,
}
#[derive(Debug, Args)]
pub struct ReinstallArgs {
    #[arg(default_value = ".")]
    pub path: PathBuf,
    #[arg(short = 'q', long)]
    pub quiet: bool,
    #[arg(long)]
    pub json: bool,
    #[arg(long)]
    pub no_project: bool,
    /// Native directory bundle containing FILES.json
    #[arg(long)]
    pub bundle: PathBuf,
    /// Expected SHA-256 of the immutable native bundle manifest
    #[arg(long)]
    pub manifest_sha256: String,
    /// Explicit native package installation prefix
    #[arg(long)]
    pub prefix: PathBuf,
    #[command(flatten)]
    pub flags: InstallFlags,
}
fn output(code: u8, stdout: String, stderr: String) -> CommandOutput {
    CommandOutput {
        code,
        stdout,
        stderr,
    }
}
fn input(path: &Path, context: &DiscoveryContext) -> PathBuf {
    context.cwd.join(path)
}
fn options(flags: &InstallFlags) -> InstallOptions {
    InstallOptions {
        hosts: ken_hosts::InstallOptions {
            hosts: HostSelection {
                claude: flags.claude,
                codex: flags.codex,
                opencode: flags.opencode,
                deepseek: flags.deepseek,
            },
            no_wire: flags.no_wire,
            instructions: if flags.agents_md {
                Some(true)
            } else if flags.no_agents_md {
                Some(false)
            } else {
                None
            },
            force_codex: flags.codex,
        },
        embed: flags.embed,
        embed_limit: flags.embed_limit,
    }
}
fn native(resources: &Path, environment: &BTreeMap<String, String>) -> Result<NativeCommand> {
    let executable = match environment.get("KEN_NATIVE_INSTALL_EXECUTABLE") {
        Some(path) => {
            if !Path::new(path).is_absolute() || path.contains('\0') {
                return Err("KEN_NATIVE_INSTALL_EXECUTABLE must be an absolute NUL-free native launcher path".into());
            }
            path.clone()
        }
        None => std::env::current_exe()?
            .into_os_string()
            .into_string()
            .map_err(|_| "native executable path must be Unicode for host configuration")?,
    };
    let resources = match environment.get("KEN_NATIVE_INSTALL_RESOURCES") {
        Some(path) => {
            if !Path::new(path).is_absolute() || path.contains('\0') {
                return Err("KEN_NATIVE_INSTALL_RESOURCES must be an absolute NUL-free resource manifest path".into());
            }
            path.as_str()
        }
        None => resources
            .to_str()
            .ok_or("resource manifest path must be Unicode for host configuration")?,
    };
    Ok(NativeCommand::new(
        executable,
        vec!["--resources".into(), resources.into()],
    )?)
}
fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(i64::MAX)
}
fn install(
    args: InstallArgs,
    resources: &Path,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    let root = input(&args.path, context);
    let environment = crate::runtime::environment();
    let command = native(resources, &environment)?;
    let grammar = ken_search::SearchInstallation::grammar_manifest(resources)?;
    let catalog = Arc::new(GrammarCatalog::prepared(&grammar)?);
    let app = ProjectInstallation::new(
        &root,
        catalog,
        command,
        ken_hosts::catalog::bundled_skills()?,
        crate::runtime::user_config(&environment),
        environment.get("KEN_EMBED_MODEL").cloned(),
    )?;
    let mut provider = |_: &rusqlite::Connection,
                        model: &str|
     -> project::Result<Rc<dyn ken_index::DocumentEncoder>> {
        let factory = crate::runtime::model_factory(resources, &environment)
            .map_err(|error| project::Error::Invalid(format!("native model resources: {error}")))?;
        Ok(Rc::new(ProjectEmbeddings::new(
            factory,
            model,
            TransformerOverrides {
                sequence_length: environment.get("KEN_EMBED_MAX_SEQ").cloned(),
                batch_size: environment.get("KEN_EMBED_BATCH").cloned(),
            },
        )))
    };
    let report = app.install_with_provider(&options(&args.flags), now(), &mut provider)?;
    if args.json {
        return Ok(output(
            0,
            serde_json::to_string_pretty(&report)? + "\n",
            String::new(),
        ));
    }
    let mut text = if args.quiet {
        String::new()
    } else {
        format!(
            "✓ ken installed in {}\n  indexed {} files, {} symbols; model: {}\n",
            report.project_root.display(),
            report.files_indexed,
            report.symbols,
            report.model
        )
    };
    // This host requires an explicit overlay even when ordinary progress is quiet.
    let deepseek = if args.flags.no_wire {
        false
    } else {
        ken_hosts::detect(&report.project_root, options(&args.flags).hosts.hosts)?.deepseek
    };
    if deepseek {
        text.push_str(&format!(
            "[deepseek] next: {}\n",
            ken_hosts::deepseek::launch_command(&report.project_root)
        ));
    }
    let mut notices = report.warnings;
    notices.extend(
        report
            .hosts
            .preserved
            .into_iter()
            .map(|(path, reason)| format!("preserved {path}: {reason}")),
    );
    let stderr = if args.quiet {
        String::new()
    } else {
        notices.into_iter().map(|notice| notice + "\n").collect()
    };
    Ok(output(0, text, stderr))
}
struct ExistingDaemon;
impl DaemonLifecycle for ExistingDaemon {
    fn stop_existing(&self, root: &Path) -> project::Result<()> {
        let client = ken_daemon::client::Client::new(
            root,
            ken_daemon::client::Program::new(std::env::current_exe()?),
            ken_daemon::client::ClientOptions::default(),
        );
        client.stop_existing().map_err(|error| {
            project::Error::Invalid(format!("existing daemon shutdown failed: {error}"))
        })
    }
}
fn remove(
    args: UninstallArgs,
    resources: &Path,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    let environment = crate::runtime::environment();
    let command = native(resources, &environment)?;
    let report = project::uninstall(
        &input(&args.path, context),
        command,
        &UninstallOptions {
            keep_db: args.keep_db,
        },
        &ExistingDaemon,
    )?;
    if args.json {
        return Ok(output(
            0,
            serde_json::to_string_pretty(&report)? + "\n",
            String::new(),
        ));
    }
    let stdout = if args.quiet {
        String::new()
    } else {
        format!(
            "✓ ken uninstalled from {}\n{}",
            report.project_root.display(),
            if args.keep_db {
                "[db] keeping .ken/\n"
            } else {
                "[db] removed .ken/\n"
            }
        )
    };
    let stderr = if args.quiet {
        String::new()
    } else {
        report
            .hosts
            .preserved
            .into_iter()
            .map(|(path, reason)| format!("preserved {path}: {reason}\n"))
            .collect()
    };
    Ok(output(0, stdout, stderr))
}
fn install_arguments(args: &ReinstallArgs, root: &Path) -> Vec<OsString> {
    let mut values = vec!["install".into(), root.as_os_str().to_owned()];
    for (enabled, flag) in [
        (args.quiet, "--quiet"),
        (args.json, "--json"),
        (args.flags.claude, "--claude"),
        (args.flags.codex, "--codex"),
        (args.flags.opencode, "--opencode"),
        (args.flags.deepseek, "--deepseek"),
        (args.flags.embed, "--embed"),
        (args.flags.no_wire, "--no-wire"),
        (args.flags.agents_md, "--agents-md"),
        (args.flags.no_agents_md, "--no-agents-md"),
    ] {
        if enabled {
            values.push(flag.into());
        }
    }
    if let Some(limit) = args.flags.embed_limit {
        values.extend(["--embed-limit".into(), limit.to_string().into()]);
    }
    values
}
fn reinstall(args: ReinstallArgs, context: &DiscoveryContext) -> Result<CommandOutput> {
    let package = ken_application::package::PackageApplication::new(&input(&args.prefix, context))?;
    let report = package.install(&input(&args.bundle, context), &args.manifest_sha256)?;
    if args.no_project {
        let stdout = if args.json {
            serde_json::to_string_pretty(&report)? + "\n"
        } else if args.quiet {
            String::new()
        } else {
            format!("✓ native package activated: {}\n", report.current_release)
        };
        return Ok(output(0, stdout, String::new()));
    }
    // Reapply using the activated release's code and resources, not this process's
    // older implementation. The authenticated stable launcher becomes host wiring.
    let result = Command::new(report.release_root.join("ken"))
        .arg("--resources")
        .arg(report.release_root.join("resources/search.json"))
        .args(install_arguments(&args, &input(&args.path, context)))
        .env("KEN_NATIVE_INSTALL_EXECUTABLE", &report.executable)
        .env("KEN_NATIVE_INSTALL_RESOURCES", &report.resources)
        .output()?;
    let code = result.status.code().unwrap_or(1).clamp(0, 255) as u8;
    Ok(output(
        code,
        String::from_utf8(result.stdout)?,
        String::from_utf8(result.stderr)?,
    ))
}
pub fn run(
    command: InstallationCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    let installation = input(&installation, context);
    match command {
        InstallationCommand::Install(args) => install(args, &installation, context),
        InstallationCommand::Uninstall(args) => remove(args, &installation, context),
        InstallationCommand::Reinstall(args) => reinstall(args, context),
    }
}
