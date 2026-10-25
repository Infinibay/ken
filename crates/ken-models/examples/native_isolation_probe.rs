//! Exercise the actual macOS process/network restrictions, independently of models.
use serde::Deserialize;
use serde_json::json;
use std::{
    io::{self, Read},
    net::TcpStream,
    process::Command,
    time::Duration,
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
}
fn parse(raw: &[u8]) -> Result<Request, Box<dyn std::error::Error>> {
    let request: Request = serde_json::from_slice(raw)?;
    if request.format != "ken-native-isolation-request/1" {
        return Err("unsupported isolation request".into());
    }
    Ok(request)
}
fn denied<T>(result: io::Result<T>) -> bool {
    matches!(result, Err(error) if error.kind() == io::ErrorKind::PermissionDenied)
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    if std::env::args().nth(1).as_deref() == Some("--child") {
        return Ok(());
    }
    let mut raw = Vec::new();
    io::stdin().take(1025).read_to_end(&mut raw)?;
    if raw.len() > 1024 {
        return Err("isolation request exceeds1KiB".into());
    }
    parse(&raw)?;
    let self_child_blocked = denied(
        Command::new(std::env::current_exe()?)
            .arg("--child")
            .output(),
    );
    let absolute_child_blocked = denied(Command::new("/usr/bin/true").output());
    let network_blocked = denied(TcpStream::connect_timeout(
        &"127.0.0.1:9".parse()?,
        Duration::from_millis(500),
    ));
    println!(
        "{}",
        json!({"format":"ken-native-isolation-observation/1", "self_child_blocked":self_child_blocked,"absolute_child_blocked":absolute_child_blocked,"network_blocked":network_blocked})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn isolation_witness_accepts_only_its_versioned_input() {
        assert!(super::parse(br#"{"format":"ken-native-isolation-request/1"}"#).is_ok());
        assert!(
            super::parse(br#"{"format":"ken-native-isolation-request/1","expected":true}"#)
                .is_err()
        );
        assert!(super::parse(br#"{"format":"other"}"#).is_err());
    }
}
