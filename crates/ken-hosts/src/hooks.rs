use crate::{HookHost, NativeCommand, Result, invalid};
use serde_json::{Value, json};
use std::collections::BTreeSet;
fn templates(host: HookHost, command: &NativeCommand) -> Vec<(&'static str, Value)> {
    let entry = |matcher: Option<&str>, args: &[&str]| {
        let mut value = json!({"hooks":[{"type":"command","command":command.hook(args)}]});
        if let Some(matcher) = matcher {
            value["matcher"] = json!(matcher);
        }
        value
    };
    match host {
        HookHost::Claude => vec![
            (
                "SessionStart",
                entry(Some("startup|resume|clear|compact"), &["session-start"]),
            ),
            ("SessionEnd", entry(Some("*"), &["session-end"])),
            ("UserPromptSubmit", entry(Some("*"), &["user-prompt"])),
            (
                "PreToolUse",
                entry(
                    Some("Read|Edit|Write|MultiEdit|Glob|Grep|Bash"),
                    &["tool-call", "--phase", "pre"],
                ),
            ),
            (
                "PostToolUse",
                entry(
                    Some("Read|Edit|Write|MultiEdit|Glob|Grep|Bash"),
                    &["tool-call", "--phase", "post"],
                ),
            ),
            ("Stop", entry(Some("*"), &["stop"])),
        ],
        HookHost::Codex => vec![
            (
                "SessionStart",
                entry(Some("startup|resume|clear|compact"), &["session-start"]),
            ),
            ("UserPromptSubmit", entry(None, &["user-prompt"])),
            (
                "PreToolUse",
                entry(
                    Some(
                        "Bash|apply_patch|functions.exec_command|functions.apply_patch|functions.view_image",
                    ),
                    &["tool-call", "--phase", "pre"],
                ),
            ),
            (
                "PostToolUse",
                entry(
                    Some(
                        "Bash|apply_patch|functions.exec_command|functions.apply_patch|functions.view_image",
                    ),
                    &["tool-call", "--phase", "post"],
                ),
            ),
            ("Stop", entry(None, &["stop"])),
        ],
    }
}
fn commands(entries: &[Value]) -> Result<BTreeSet<String>> {
    let mut out = BTreeSet::new();
    for entry in entries {
        let entry = entry
            .as_object()
            .ok_or_else(|| invalid("hook groups must be objects"))?;
        if let Some(handlers) = entry.get("hooks").filter(|v| !v.is_null()) {
            for handler in handlers
                .as_array()
                .ok_or_else(|| invalid("hook handlers must be an array"))?
            {
                let handler = handler
                    .as_object()
                    .ok_or_else(|| invalid("hook handlers must be objects"))?;
                if let Some(command) = handler.get("command").and_then(Value::as_str) {
                    out.insert(command.into());
                }
            }
        }
    }
    Ok(out)
}
pub fn merge(
    existing: Option<&Value>,
    host: HookHost,
    command: &NativeCommand,
) -> Result<(Value, Vec<String>)> {
    let mut value = existing.cloned().unwrap_or_else(|| json!({}));
    let object = value
        .as_object_mut()
        .ok_or_else(|| invalid("hook configuration must be an object"))?;
    let hooks = object
        .entry("hooks")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .ok_or_else(|| invalid("hooks must be an object"))?;
    let mut touched = Vec::new();
    for (event, entry) in templates(host, command) {
        let entries = hooks
            .entry(event)
            .or_insert_with(|| json!([]))
            .as_array_mut()
            .ok_or_else(|| invalid("hook events must be arrays"))?;
        let current = commands(entries)?;
        let desired = commands(std::slice::from_ref(&entry))?;
        if !desired.iter().any(|c| current.contains(c)) {
            entries.push(entry);
            touched.push(event.into());
        }
    }
    Ok((value, touched))
}
pub fn remove_generated(
    existing: &Value,
    host: HookHost,
    command: &NativeCommand,
) -> Result<Value> {
    let mut out = existing.clone();
    let Some(hooks) = out.get_mut("hooks") else {
        return Ok(out);
    };
    let hooks = hooks
        .as_object_mut()
        .ok_or_else(|| invalid("hooks must be an object"))?;
    for (event, entry) in templates(host, command) {
        if let Some(entries) = hooks.get_mut(event) {
            let entries = entries
                .as_array_mut()
                .ok_or_else(|| invalid("hook events must be arrays"))?;
            entries.retain(|v| v != &entry);
            if entries.is_empty() {
                hooks.remove(event);
            }
        }
    }
    if hooks.is_empty() {
        out.as_object_mut().expect("hooks object").remove("hooks");
    }
    Ok(out)
}
pub(crate) fn has_ken(existing: &Value, host: HookHost, command: &NativeCommand) -> Result<bool> {
    let Some(hooks) = existing.get("hooks") else {
        return Ok(false);
    };
    let hooks = hooks
        .as_object()
        .ok_or_else(|| invalid("hooks must be an object"))?;
    let mut all = BTreeSet::new();
    for entries in hooks.values() {
        all.extend(commands(
            entries
                .as_array()
                .ok_or_else(|| invalid("hook events must be arrays"))?,
        )?);
    }
    let desired = templates(host, command)
        .into_iter()
        .map(|(_, v)| v)
        .collect::<Vec<_>>();
    Ok(all.iter().any(|c| c.starts_with("ken hook"))
        || commands(&desired)?.iter().any(|c| all.contains(c)))
}
