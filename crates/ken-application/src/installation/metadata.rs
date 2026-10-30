//! Durable project identity is independent of database/model/assistant setup.
use super::{Error, Result};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use ken_core::project_files::ProjectFiles;
use serde_json::{Value, json};
use std::{fs::File, io::Read, path::Path};
pub(super) fn validate(value: &Value) -> Result<String> {
    let id = value["project_id"]
        .as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 1024)
        .ok_or_else(|| Error::Invalid("project_id must be a nonempty string".into()))?;
    let token = value["auth_token"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 4096 && !s.contains(['\0', '\r', '\n']))
        .ok_or_else(|| Error::Invalid("auth_token must be a nonempty header-safe string".into()))?;
    let _ = token;
    Ok(id.into())
}
pub(super) fn provision(
    files: &ProjectFiles,
    root: &Path,
    now: i64,
) -> Result<(String, bool, Vec<u8>)> {
    if let Some(bytes) = files.read(".ken/meta.json")? {
        let value: Value = serde_json::from_slice(&bytes)?;
        return Ok((validate(&value)?, false, bytes));
    }
    let mut entropy = [0u8; 48];
    File::open("/dev/urandom")?.read_exact(&mut entropy)?;
    entropy[6] = (entropy[6] & 0x0f) | 0x40;
    entropy[8] = (entropy[8] & 0x3f) | 0x80;
    let raw = entropy[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let id = format!(
        "{}-{}-{}-{}-{}",
        &raw[..8],
        &raw[8..12],
        &raw[12..16],
        &raw[16..20],
        &raw[20..]
    );
    let token = URL_SAFE_NO_PAD.encode(&entropy[16..]);
    let value = json!({"project_id":id,"auth_token":token,"created_at_ms":now,"project_path":root});
    let mut bytes = serde_json::to_vec_pretty(&value)?;
    bytes.push(b'\n');
    files.write(".ken/meta.json", &bytes)?;
    Ok((id, true, bytes))
}
pub(super) fn gitignore(files: &ProjectFiles) -> Result<bool> {
    let Some(mut bytes) = files.read(".gitignore")? else {
        return Ok(false);
    };
    let text = String::from_utf8_lossy(&bytes);
    let lines = ken_text::unicode::splitlines(&text);
    if lines.iter().any(|s| {
        matches!(
            s.trim_matches(ken_text::unicode::whitespace),
            ".ken" | ".ken/"
        )
    }) {
        return Ok(false);
    }
    let separator = if lines
        .last()
        .is_some_and(|line| line.trim_matches(ken_text::unicode::whitespace).is_empty())
    {
        ""
    } else {
        "\n"
    };
    let addition = format!("{separator}\n# ken — local index, daemon socket, logs\n.ken/\n");
    bytes.extend_from_slice(addition.as_bytes());
    files.write(".gitignore", &bytes)?;
    Ok(true)
}
