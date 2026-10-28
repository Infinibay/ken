//! MCP 2025-11-25 stdio lifecycle; domain search and framing have separate owners.
mod framing;
use crate::tools::{ToolService, definitions};
use framing::Frame;
use ken_core::project::{DiscoveryContext, ProjectPaths, locate_project};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::{
    collections::BTreeMap,
    io::{self, BufRead, Write},
    path::{Path, PathBuf},
};
const VERSION: &str = "2025-11-25";

fn error(id: Value, code: i32, message: impl ToString) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message.to_string()}})
}
fn result(id: Value, value: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":value})
}
fn tool_result(text: impl ToString, is_error: bool) -> Value {
    json!({"content":[{"type":"text","text":text.to_string()}],"isError":is_error})
}
#[derive(PartialEq)]
enum Phase {
    New,
    Initializing,
    Ready,
}
#[derive(Deserialize)]
struct Initialize {
    #[serde(rename = "protocolVersion")]
    _protocol_version: String,
    #[serde(rename = "capabilities")]
    _capabilities: BTreeMap<String, Value>,
    #[serde(rename = "clientInfo")]
    _client_info: ClientInfo,
}
#[derive(Deserialize)]
struct ClientInfo {
    #[serde(rename = "name")]
    _name: String,
    #[serde(rename = "version")]
    _version: String,
}
#[derive(Deserialize)]
struct Call {
    name: String,
    arguments: Option<Box<RawValue>>,
}
struct Server {
    phase: Phase,
    tools: ToolService,
}
impl Server {
    fn handle(&mut self, bytes: &[u8]) -> Option<Value> {
        let checked: Box<RawValue> = match serde_json::from_slice(bytes) {
            Ok(value) => value,
            Err(e) => return Some(error(Value::Null, -32700, e)),
        };
        let fields: BTreeMap<String, Box<RawValue>> = match serde_json::from_str(checked.get()) {
            Ok(value) => value,
            Err(e) => return Some(error(Value::Null, -32600, e)),
        };
        let id = match fields.get("id") {
            None => None,
            Some(raw) => match serde_json::from_str::<Value>(raw.get()) {
                Ok(id)
                    if id.is_string()
                        || id.as_number().is_some_and(|n| n.is_i64() || n.is_u64()) =>
                {
                    Some(id)
                }
                _ => {
                    return Some(error(
                        Value::Null,
                        -32600,
                        "request ID must be a string or integer",
                    ));
                }
            },
        };
        let id_value = id.clone().unwrap_or(Value::Null);
        let version = fields
            .get("jsonrpc")
            .and_then(|v| serde_json::from_str::<String>(v.get()).ok());
        if version.as_deref() != Some("2.0") {
            return Some(error(id_value, -32600, "jsonrpc must be 2.0"));
        }
        let method = match fields
            .get("method")
            .and_then(|v| serde_json::from_str::<String>(v.get()).ok())
        {
            Some(method) => method,
            None if id.is_some()
                && (fields.contains_key("result") || fields.contains_key("error")) =>
            {
                return None;
            }
            None => return Some(error(id_value, -32600, "request method required")),
        };
        if id.is_none() {
            let valid_params = fields.get("params").is_none_or(|raw| {
                raw.get() == "null"
                    || serde_json::from_str::<BTreeMap<String, Value>>(raw.get()).is_ok()
            });
            if method == "notifications/initialized"
                && self.phase == Phase::Initializing
                && valid_params
            {
                self.phase = Phase::Ready;
            }
            return None;
        }
        let params = fields.get("params").map(|v| v.get()).unwrap_or("{}");
        if method == "ping" {
            return Some(result(id_value, json!({})));
        }
        if method == "initialize" {
            if self.phase != Phase::New {
                return Some(error(id_value, -32600, "connection is already initialized"));
            }
            let _input: Initialize = match serde_json::from_str(params) {
                Ok(input) => input,
                Err(e) => return Some(error(id_value, -32602, e)),
            };
            self.phase = Phase::Initializing;
            return Some(result(
                id_value,
                json!({"protocolVersion":VERSION,"capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"ken-rs","version":env!("CARGO_PKG_VERSION")}}),
            ));
        }
        if !matches!(method.as_str(), "tools/list" | "tools/call") {
            return Some(error(id_value, -32601, "method not found"));
        }
        if self.phase != Phase::Ready {
            return Some(error(
                id_value,
                -32002,
                "initialize the connection before invoking tools",
            ));
        }
        if method == "tools/list" {
            let list: BTreeMap<String, Value> = match serde_json::from_str(params) {
                Ok(list) => list,
                Err(e) => return Some(error(id_value, -32602, e)),
            };
            if list.get("cursor").is_some_and(|v| !v.is_null()) {
                return Some(error(id_value, -32602, "no pagination cursor is available"));
            }
            return Some(result(id_value, json!({"tools":definitions()})));
        }
        let input: Call = match serde_json::from_str(params) {
            Ok(input) => input,
            Err(e) => return Some(error(id_value, -32602, e)),
        };
        if !ToolService::known(&input.name) {
            return Some(error(
                id_value,
                -32602,
                format!("Unknown tool: {}", input.name),
            ));
        }
        if input
            .arguments
            .as_deref()
            .is_some_and(|raw| !raw.get().trim_start().starts_with('{'))
        {
            return Some(error(id_value, -32602, "tool arguments must be an object"));
        }
        let empty = RawValue::from_string("{}".into()).expect("empty argument object");
        let output = match self
            .tools
            .call(&input.name, input.arguments.as_deref().unwrap_or(&empty))
        {
            Ok(text) => tool_result(text, false),
            Err(error) => tool_result(error, true),
        };
        Some(result(id_value, output))
    }
    fn serve(&mut self, input: &mut impl BufRead, output: &mut impl Write) -> io::Result<()> {
        while let Some(frame) = framing::read(input)? {
            let response = match frame {
                Frame::Bytes(bytes) => self.handle(&bytes),
                Frame::Oversized => Some(error(Value::Null, -32700, "MCP frame exceeds8MiB")),
            };
            if let Some(response) = response {
                serde_json::to_writer(&mut *output, &response)?;
                output.write_all(b"\n")?;
                output.flush()?;
            }
        }
        Ok(())
    }
}

pub fn run(
    start: &Path,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<(), Box<dyn std::error::Error>> {
    let paths = match locate_project(start, context)? {
        Some(paths) => paths,
        None => ProjectPaths::at(start, context)?,
    };
    if !paths.meta().is_file() {
        return Err(
            io::Error::other(format!("no .ken project at {}", paths.root().display())).into(),
        );
    }
    let mut server = Server {
        phase: Phase::New,
        tools: ToolService::new(paths, installation),
    };
    server.serve(&mut io::stdin().lock(), &mut io::stdout().lock())?;
    Ok(())
}
