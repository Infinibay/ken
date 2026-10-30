use serde_json::Value;
use sha2::{Digest, Sha256};
/// Python json.dumps(default separators, sorted keys, ensure_ascii=False).
/// Hashes are shared with the existing immutable receipts/checkpoints.
pub fn json(value: &Value) -> String {
    match value {
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(json).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(map) => {
            let mut keys = map.keys().collect::<Vec<_>>();
            keys.sort();
            format!(
                "{{{}}}",
                keys.into_iter()
                    .map(|k| format!("{}: {}", serde_json::to_string(k).unwrap(), json(&map[k])))
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
        _ => serde_json::to_string(value).unwrap(),
    }
}
pub fn hash(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}
pub fn digest(value: &Value) -> String {
    hash(json(value).as_bytes())
}
pub fn string(value: &Value, field: &str, limit: usize, empty: bool) -> crate::Result<String> {
    let Some(s) = value.as_str() else {
        return Err(crate::invalid(format!(
            "{field} must be {}..{limit} characters",
            if empty { 0 } else { 1 }
        )));
    };
    if s.chars().count() > limit || (!empty && s.trim().is_empty()) {
        return Err(crate::invalid(format!(
            "{field} must be {}..{limit} characters",
            if empty { 0 } else { 1 }
        )));
    }
    Ok(s.trim().to_owned())
}
pub fn fields(value: &Value, allowed: &[&str], message: &str) -> crate::Result<()> {
    if !value
        .as_object()
        .is_some_and(|m| m.keys().all(|k| allowed.contains(&k.as_str())))
    {
        return Err(crate::invalid(message));
    }
    Ok(())
}
pub fn round(value: f64, digits: i32) -> f64 {
    let factor = 10f64.powi(digits);
    (value * factor).round_ties_even() / factor
}
pub fn transaction<T>(
    db: &rusqlite::Connection,
    body: impl FnOnce() -> crate::Result<T>,
) -> crate::Result<T> {
    db.execute_batch("BEGIN IMMEDIATE")?;
    match body() {
        Ok(value) => {
            if let Err(e) = db.execute_batch("COMMIT") {
                let _ = db.execute_batch("ROLLBACK");
                Err(e.into())
            } else {
                Ok(value)
            }
        }
        Err(e) => {
            let _ = db.execute_batch("ROLLBACK");
            Err(e)
        }
    }
}
pub fn json_ascii(value: &Value) -> String {
    let mut out = String::new();
    for ch in json(value).chars() {
        if ch.is_ascii() {
            out.push(ch);
        } else {
            let code = ch as u32;
            if code <= 0xffff {
                out.push_str(&format!("\\u{code:04x}"));
            } else {
                let n = code - 0x10000;
                out.push_str(&format!(
                    "\\u{:04x}\\u{:04x}",
                    0xd800 + (n >> 10),
                    0xdc00 + (n & 1023)
                ));
            }
        }
    }
    out
}
