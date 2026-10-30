//! Parse TOML to recognize real registrations; append without rewriting users.
use crate::{NativeCommand, Result};
fn desired(command: &NativeCommand) -> Result<String> {
    Ok(format!(
        "[mcp_servers.ken]\ncommand = {}\nargs = {}\n",
        serde_json::to_string(&command.program)?,
        serde_json::to_string(&command.mcp_args(None))?
    ))
}
pub fn has_registration(text: &str) -> Result<bool> {
    let value: toml::Value = text.parse()?;
    Ok(value
        .get("mcp_servers")
        .and_then(|v| v.get("ken"))
        .is_some())
}
pub fn append(text: &str, command: &NativeCommand) -> Result<String> {
    if has_registration(text)? {
        return Ok(text.into());
    }
    let separator = if text.is_empty() || text.ends_with("\n\n") {
        ""
    } else if text.ends_with('\n') {
        "\n"
    } else {
        "\n\n"
    };
    let output = format!("{text}{separator}{}", desired(command)?);
    output.parse::<toml::Value>()?;
    Ok(output)
}
pub fn remove_owned(text: &str, command: &NativeCommand) -> Result<String> {
    let value: toml::Value = text.parse()?;
    let expected: toml::Value = desired(command)?.parse()?;
    if value.get("mcp_servers").and_then(|v| v.get("ken"))
        != expected.get("mcp_servers").and_then(|v| v.get("ken"))
    {
        return Ok(text.into());
    }
    let block = desired(command)?;
    Ok(text.strip_suffix(&block).unwrap_or(text).to_owned())
}
