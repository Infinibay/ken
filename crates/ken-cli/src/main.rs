use ken_cli::{
    args::{Command, Invocation, StatusArgs, parse_command_from},
    status::{CommandOutput, render},
};
use ken_core::{health::DaemonHealthClient, project::DiscoveryContext, status::read_status};
use std::{
    io::{self, Write},
    process::ExitCode,
};

fn status(args: StatusArgs) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    let context = DiscoveryContext::from_process()?;
    let report = read_status(&args.path, &context, &DaemonHealthClient::new())?;
    Ok(render(&report, args.json)?)
}
fn run(invocation: Invocation) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    if let Command::Status(args) = invocation.command {
        return status(args);
    }
    let context = DiscoveryContext::from_process()?;
    let installation = invocation
        .resources
        .or_else(|| std::env::var_os("KEN_NATIVE_RESOURCES").map(Into::into))
        .map_or_else(
            || {
                std::env::current_exe().map(|exe| {
                    exe.parent()
                        .expect("executable parent")
                        .join("resources/search.json")
                })
            },
            Ok,
        )?;
    match invocation.command {
        Command::SearchFiles(args) => ken_cli::search::run(args, "file", installation, &context),
        Command::SearchSymbols(args) => {
            ken_cli::search::run(args, "symbol", installation, &context)
        }
        Command::Status(_) => unreachable!("status handled above"),
    }
}
fn main() -> ExitCode {
    let args = match parse_command_from(std::env::args_os()) {
        Ok(args) => args,
        Err(error) => {
            let code = error.exit_code() as u8;
            return if error.print().is_ok() {
                ExitCode::from(code)
            } else {
                ExitCode::FAILURE
            };
        }
    };
    let label = match &args.command {
        Command::Status(_) => "status",
        Command::SearchFiles(_) => "search-files",
        Command::SearchSymbols(_) => "search-symbols",
    };
    let output = run(args).unwrap_or_else(|error| CommandOutput {
        code: 1,
        stdout: String::new(),
        stderr: format!("ken-rs {label}: {error}\n"),
    });
    let written = io::stdout()
        .lock()
        .write_all(output.stdout.as_bytes())
        .and_then(|_| io::stderr().lock().write_all(output.stderr.as_bytes()));
    if written.is_ok() {
        ExitCode::from(output.code)
    } else {
        ExitCode::FAILURE
    }
}
