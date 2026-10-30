//! Native daemon invocation is shared by hooks, session tools and terminal commands.
use crate::status::CommandOutput;
use clap::{Subcommand, ValueEnum};
use ken_core::project::{DiscoveryContext, ProjectPaths, locate_project};
use ken_daemon::{
    client::{Client, ClientOptions, Program},
    hooks::{self, HookCommand},
};
use serde_json::{Value, json};
use std::{
    io::Read,
    path::{Path, PathBuf},
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub fn environment() -> std::collections::BTreeMap<String, String> {
    std::env::vars_os()
        .filter_map(|(key, value)| Some((key.into_string().ok()?, value.into_string().ok()?)))
        .collect()
}
pub fn user_config(
    environment: &std::collections::BTreeMap<String, String>,
) -> ken_maintenance::UserConfig {
    let path = |name: &str| environment.get(name).map(PathBuf::from);
    ken_maintenance::UserConfig::new(&ken_maintenance::ConfigEnvironment {
        config_dir: path("KEN_CONFIG_DIR"),
        xdg_config_home: path("XDG_CONFIG_HOME"),
        home: path("HOME").unwrap_or_default(),
    })
}
pub fn model_factory(
    installation: &Path,
    environment: &std::collections::BTreeMap<String, String>,
) -> Result<std::sync::Arc<ken_models::ModelFactory>> {
    let (fastembed, transformer) = ken_daemon::native::device_requests(environment);
    Ok(
        ken_search::SearchInstallation::open_model_factory_with_devices(
            installation,
            fastembed,
            transformer,
        )?,
    )
}
#[derive(Debug, Subcommand)]
pub enum RuntimeCommand {
    /// Serve authenticated sessions, ranking and live indexing for a project
    Serve {
        #[arg(default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        background: bool,
    },
    /// Receive a coding agent event on stdin
    Hook {
        #[command(subcommand)]
        command: Hook,
    },
    /// Render the current session context or rank a different intent
    Rank {
        query: Vec<String>,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(short='v',long,default_value_t=1,value_parser=clap::value_parser!(u8).range(0..=2))]
        verbose: u8,
        #[arg(long)]
        max_chars: Option<i64>,
        #[arg(long)]
        stats: bool,
        #[arg(long)]
        json: bool,
    },
    /// Explain the session ranker's channels and score contributions
    Explain {
        query: Vec<String>,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        json: bool,
    },
}
#[derive(Debug, Subcommand)]
pub enum Hook {
    SessionStart,
    SessionEnd,
    UserPrompt,
    Stop,
    ToolCall {
        #[arg(long, value_enum)]
        phase: Phase,
    },
}
#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum Phase {
    Pre,
    Post,
}
impl Hook {
    fn event(&self) -> HookCommand {
        match self {
            Self::SessionStart => HookCommand::SessionStart,
            Self::SessionEnd => HookCommand::SessionEnd,
            Self::UserPrompt => HookCommand::UserPrompt,
            Self::Stop => HookCommand::Stop,
            Self::ToolCall { phase: Phase::Pre } => HookCommand::ToolPre,
            Self::ToolCall { phase: Phase::Post } => HookCommand::ToolPost,
        }
    }
}
pub fn client(paths: &ProjectPaths, installation: &Path) -> Result<Client> {
    let installation = std::path::absolute(installation)?;
    let mut program = Program::new(std::env::current_exe()?);
    program.arguments = vec![
        "--resources".into(),
        installation.into_os_string(),
        "serve".into(),
        paths.root().as_os_str().to_owned(),
        "--background".into(),
    ];
    Ok(Client::new(paths.root(), program, ClientOptions::default()))
}
pub(crate) fn check_worker() -> Result<PathBuf> {
    Ok(std::env::current_exe()?
        .parent()
        .ok_or("native executable directory missing")?
        .join("ken-check-worker"))
}
pub fn session_rank(
    paths: &ProjectPaths,
    installation: &Path,
    query: &str,
    verbose: i64,
    max_chars: i64,
    explain: bool,
) -> Result<Value> {
    let body = if explain {
        json!({"query":query})
    } else {
        json!({"query":query,"verbose":verbose,"max_chars":max_chars})
    };
    Ok(client(paths, installation)?
        .post(if explain { "/explain" } else { "/rank" }, &body)?
        .unwrap_or_else(|| json!({"ok":false,"error":"daemon unreachable"})))
}
fn paths(start: &Path, context: &DiscoveryContext) -> Result<ProjectPaths> {
    locate_project(start, context)?.ok_or_else(|| {
        format!(
            "no ken project at {} — run `ken install .` first",
            start.display()
        )
        .into()
    })
}
fn hook(command: Hook, installation: &Path, context: &DiscoveryContext) -> CommandOutput {
    let result = (|| -> Result<CommandOutput> {
        let paths = paths(Path::new("."), context)?;
        let mut bytes = Vec::new();
        std::io::stdin()
            .lock()
            .take(8 * 1024 * 1024 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > 8 * 1024 * 1024 {
            return Err("hook input exceeds 8MiB".into());
        }
        let payload: Value = serde_json::from_slice(&bytes)?;
        let response = hooks::dispatch(command.event(), &payload, &client(&paths, installation)?);
        Ok(CommandOutput {
            code: 0,
            stdout: response.stdout,
            stderr: response.diagnostic.map(|s| s + "\n").unwrap_or_default(),
        })
    })();
    result.unwrap_or_else(|error| CommandOutput {
        code: 0,
        stdout: String::new(),
        stderr: format!("ken: hook error: {error}\n"),
    })
}
pub fn run(
    command: RuntimeCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    match command {
        RuntimeCommand::Hook { command } => Ok(hook(command, &installation, context)),
        RuntimeCommand::Serve { path, background } => {
            let paths = paths(&path, context)?;
            if background {
                redirect_daemon_log(&paths)?;
            }
            let environment = environment();
            ken_daemon::native::run(
                paths.root(),
                &installation,
                Some(check_worker()?),
                &environment,
            )?;
            Ok(CommandOutput {
                code: 0,
                stdout: String::new(),
                stderr: String::new(),
            })
        }
        RuntimeCommand::Rank {
            query,
            path,
            verbose,
            max_chars,
            stats,
            json,
        } => {
            let paths = paths(&path, context)?;
            let value = session_rank(
                &paths,
                &installation,
                &query.join(" "),
                verbose.into(),
                max_chars.unwrap_or(0),
                false,
            )?;
            let failed = value["ok"] == false;
            let stderr = if stats {
                format!(
                    "context: {} files, {} symbols, {} findings, {} chars, ~{} tokens\n",
                    value["files"],
                    value["symbols"],
                    value["findings"],
                    value["context_chars"],
                    value["context_est_tokens"]
                )
            } else {
                String::new()
            };
            let stdout = if json {
                serde_json::to_string_pretty(&value)? + "\n"
            } else if let Some(text) = value["context_block"].as_str() {
                text.to_owned() + "\n"
            } else {
                value.to_string() + "\n"
            };
            Ok(CommandOutput {
                code: u8::from(failed),
                stdout,
                stderr,
            })
        }
        RuntimeCommand::Explain {
            query,
            path,
            json: _,
        } => {
            let paths = paths(&path, context)?;
            let value = session_rank(&paths, &installation, &query.join(" "), 1, 0, true)?;
            Ok(CommandOutput {
                code: u8::from(value["ok"] == false),
                stdout: serde_json::to_string_pretty(&value)? + "\n",
                stderr: String::new(),
            })
        }
    }
}

fn redirect_daemon_log(paths: &ProjectPaths) -> std::io::Result<()> {
    use std::os::{
        fd::{AsRawFd, FromRawFd},
        unix::fs::MetadataExt,
    };
    let directory = ken_core::source_reader::open_directory(&paths.root().join(".ken"))?;
    // This fixed leaf is opened relative to the held project directory.
    // SAFETY: the owned directory descriptor and static NUL-terminated leaf are valid.
    let fd = unsafe {
        libc::openat(
            directory.as_raw_fd(),
            c"daemon.log".as_ptr(),
            libc::O_WRONLY
                | libc::O_APPEND
                | libc::O_CREAT
                | libc::O_CLOEXEC
                | libc::O_NOFOLLOW
                | libc::O_NONBLOCK,
            0o600,
        )
    };
    if fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: successful openat transferred one newly owned descriptor.
    let log = unsafe { std::fs::File::from_raw_fd(fd) };
    let metadata = log.metadata()?;
    if !metadata.is_file() || metadata.nlink() != 1 {
        return Err(std::io::Error::other(
            "daemon log must be an independent regular file",
        ));
    }
    // SAFETY: dup2 uses a live owned source and the two standard output descriptors.
    for target in [libc::STDOUT_FILENO, libc::STDERR_FILENO] {
        if unsafe { libc::dup2(log.as_raw_fd(), target) } < 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}
