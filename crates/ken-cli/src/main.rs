use ken_cli::{
    args::{StatusArgs, parse_from},
    status::{CommandOutput, render},
};
use ken_core::{health::DaemonHealthClient, project::DiscoveryContext, status::read_status};
use std::{
    io::{self, Write},
    process::ExitCode,
};

fn run(args: StatusArgs) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    let context = DiscoveryContext::from_process()?;
    let report = read_status(&args.path, &context, &DaemonHealthClient::new())?;
    Ok(render(&report, args.json)?)
}
fn main() -> ExitCode {
    let args = match parse_from(std::env::args_os()) {
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
    let output = run(args).unwrap_or_else(|error| CommandOutput {
        code: 1,
        stdout: String::new(),
        stderr: format!("ken-rs status: {error}\n"),
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
