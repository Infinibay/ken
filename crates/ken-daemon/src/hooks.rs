//! Host payload projection. Hook failures remain successful host commands.
use crate::client::Client;
use serde_json::{Value, json};
use std::{
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    path::Path,
};
#[derive(Clone, Copy, Debug)]
pub enum HookCommand {
    SessionStart,
    SessionEnd,
    UserPrompt,
    ToolPre,
    ToolPost,
    Stop,
}
pub struct HookRequest {
    pub path: &'static str,
    pub payload: Value,
}
pub struct HookOutcome {
    pub stdout: String,
    pub diagnostic: Option<String>,
    pub exit_code: i32,
}
pub fn truth(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
fn first<'a>(payload: &'a Value, keys: &[&str]) -> &'a Value {
    keys.iter()
        .find_map(|k| payload.get(*k).filter(|v| truth(v)))
        .unwrap_or(&Value::Null)
}
pub fn normalize(command: HookCommand, payload: &Value) -> Option<HookRequest> {
    let session = payload["session_id"].as_str().filter(|s| !s.is_empty())?;
    let (path, body) = match command {
        HookCommand::SessionStart => (
            "/sessions/start",
            json!({"session_id":session,"cwd":payload["cwd"]}),
        ),
        HookCommand::SessionEnd => ("/sessions/end", json!({"session_id":session})),
        HookCommand::UserPrompt => (
            "/prompts",
            json!({"session_id":session,"prompt":payload.get("prompt").cloned().unwrap_or(json!(""))}),
        ),
        HookCommand::ToolPre | HookCommand::ToolPost => {
            let mut body = json!({"session_id":session,"tool":first(payload,&["tool_name","tool"]).as_str().unwrap_or(""),"input":first(payload,&["tool_input","input"])});
            if body["input"].is_null() {
                body["input"] = json!({});
            }
            if matches!(command, HookCommand::ToolPost) {
                body["output"] = first(payload, &["tool_response", "output"]).clone();
                body["success"] = json!(payload.get("success").map(truth).unwrap_or(true));
            }
            (
                if matches!(command, HookCommand::ToolPre) {
                    "/tools/pre"
                } else {
                    "/tools/post"
                },
                body,
            )
        }
        HookCommand::Stop => {
            let text = payload["last_assistant_message"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_owned)
                .unwrap_or_else(|| {
                    payload["transcript_path"]
                        .as_str()
                        .map(|p| extract_last_assistant_text(Path::new(p), 50_000))
                        .unwrap_or_default()
                });
            (
                "/turn-end",
                json!({"session_id":session,"assistant_text":text}),
            )
        }
    };
    Some(HookRequest {
        path,
        payload: body,
    })
}
pub fn dispatch(command: HookCommand, payload: &Value, client: &Client) -> HookOutcome {
    let Some(request) = normalize(command, payload) else {
        return HookOutcome {
            stdout: String::new(),
            diagnostic: Some("ken: hook payload missing session_id; skipping".into()),
            exit_code: 0,
        };
    };
    match client.post(request.path, &request.payload) {
        Ok(response) => {
            let stdout = if matches!(command, HookCommand::SessionStart | HookCommand::UserPrompt) {
                response
                    .as_ref()
                    .and_then(|r| r["context_block"].as_str())
                    .filter(|s| !s.trim().is_empty())
                    .unwrap_or("")
                    .to_owned()
            } else {
                String::new()
            };
            HookOutcome {
                stdout,
                diagnostic: None,
                exit_code: 0,
            }
        }
        Err(error) => HookOutcome {
            stdout: String::new(),
            diagnostic: Some(format!("ken: hook error: {error}")),
            exit_code: 0,
        },
    }
}
pub fn extract_last_assistant_text(path: &Path, max_bytes: u64) -> String {
    (|| -> std::io::Result<String> {
        let file = std::fs::File::open(path)?;
        let size = file.metadata()?.len();
        let mut reader = BufReader::new(file);
        if size > max_bytes {
            reader.seek(SeekFrom::Start(size - max_bytes))?;
            let mut discarded = Vec::new();
            reader.read_until(b'\n', &mut discarded)?;
        }
        // Keep the same reader: read_until can prefetch complete later lines.
        let mut bytes = Vec::new();
        reader.take(max_bytes).read_to_end(&mut bytes)?;
        let decoded = String::from_utf8_lossy(&bytes);
        for line in decoded.lines().rev() {
            let Ok(entry) = serde_json::from_str::<Value>(line.trim()) else {
                continue;
            };
            if entry["type"] != "assistant" {
                continue;
            }
            let content = &entry["message"]["content"];
            return Ok(if let Some(text) = content.as_str() {
                text.to_owned()
            } else if let Some(blocks) = content.as_array() {
                blocks
                    .iter()
                    .filter(|b| b["type"] == "text")
                    .filter_map(|b| b["text"].as_str())
                    .collect::<Vec<_>>()
                    .join("\n")
            } else {
                String::new()
            });
        }
        Ok(String::new())
    })()
    .unwrap_or_default()
}
pub fn canonical_tool_name(tool: &str) -> String {
    tool.trim().rsplit('.').next().unwrap_or("").to_lowercase()
}
pub struct ClassifiedTool {
    pub event: String,
    pub target: Option<String>,
}
pub fn extract_target(input: &Value) -> Option<String> {
    if let Some(text) = input.as_str() {
        return first_path(text);
    }
    if !input.is_object() {
        return None;
    }
    for key in ["file_path", "path"] {
        if let Some(path) = input[key].as_str() {
            return Some(path.into());
        }
    }
    for key in ["cmd", "command", "patch"] {
        if let Some(path) = input[key].as_str().and_then(first_path) {
            return Some(path);
        }
    }
    input["workdir"].as_str().map(str::to_owned)
}
fn first_path(text: &str) -> Option<String> {
    ken_context::channels::source_path_mentions(&text.into())
        .into_iter()
        .next()
}
pub fn classify_tool(tool: &str, input: &Value) -> ClassifiedTool {
    let name = canonical_tool_name(tool);
    let target = extract_target(input);
    let words = name.split('_').collect::<Vec<_>>();
    let read = [
        "read", "grep", "glob", "search", "list", "find", "view", "get", "cat", "show", "inspect",
        "analyze", "analyse", "iter", "project",
    ];
    let edit = [
        "edit", "write", "create", "replace", "add", "insert", "remove", "delete", "rename",
        "move", "patch", "apply", "update",
    ];
    let event = if ["read", "glob", "grep"].contains(&name.as_str()) {
        "read"
    } else if ["edit", "write", "multiedit", "apply_patch"].contains(&name.as_str()) {
        "edit"
    } else if ["bash", "exec_command"].contains(&name.as_str()) {
        if target.is_some() { "read" } else { "neutral" }
    } else if target.is_some() && words.first().is_some_and(|w| edit.contains(w)) {
        "edit"
    } else if target.is_some() && words.iter().any(|w| read.contains(w)) {
        "read"
    } else {
        "neutral"
    };
    ClassifiedTool {
        event: event.into(),
        target,
    }
}
