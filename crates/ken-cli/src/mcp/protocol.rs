//! Wire validation and protocol-era ownership, independent of blocking tool work.
use super::ToolHandler;
use ken_query::execution::Cancellation;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::collections::BTreeMap;
const HANDSHAKE: &[&str] = &["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"];
const LATEST: &str = "2025-11-25";
const MODERN: &str = "2026-07-28";
const PROTOCOL: &str = "io.modelcontextprotocol/protocolVersion";
const CAPABILITIES: &str = "io.modelcontextprotocol/clientCapabilities";
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct RequestKey(String);
pub(super) fn request_id(raw: &RawValue) -> Option<(RequestKey, Value)> {
    let value: Value = serde_json::from_str(raw.get()).ok()?;
    let key = match &value {
        Value::String(text) => format!("s:{text}"),
        Value::Number(number) => {
            let text = number.to_string();
            let digits = text.strip_prefix('-').unwrap_or(&text);
            if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let normalized = if number.as_i64() == Some(0) {
                "0"
            } else {
                text.as_str()
            };
            format!("i:{normalized}")
        }
        _ => return None,
    };
    Some((RequestKey(key), value))
}
pub(super) struct Request {
    pub key: RequestKey,
    pub id: Value,
    pub method: String,
    pub params: Box<RawValue>,
    pub cancellation: Cancellation,
}
pub(super) enum Incoming {
    Request(Request),
    Cancel(RequestKey),
    Ignored,
    Error(Value),
}
pub(super) fn error(id: Value, code: i32, message: impl ToString) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message.to_string()}})
}
fn error_data(id: Value, code: i32, message: impl ToString, data: Value) -> Value {
    let mut result = error(id, code, message);
    result["error"]["data"] = data;
    result
}
fn result(id: Value, value: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":value})
}
fn server_info() -> Value {
    json!({"name":"ken-rs","version":env!("CARGO_PKG_VERSION")})
}
fn capabilities() -> Value {
    json!({"tools":{"listChanged":false}})
}
pub(super) fn decode(bytes: &[u8]) -> Incoming {
    let raw: Box<RawValue> = match serde_json::from_slice(bytes) {
        Ok(raw) => raw,
        Err(e) => return Incoming::Error(error(Value::Null, -32700, e)),
    };
    let fields: BTreeMap<String, Box<RawValue>> = match serde_json::from_str(raw.get()) {
        Ok(fields) => fields,
        Err(e) => return Incoming::Error(error(Value::Null, -32600, e)),
    };
    let id = match fields.get("id") {
        None => None,
        Some(raw) => match request_id(raw) {
            Some(id) => Some(id),
            None => {
                return Incoming::Error(error(
                    Value::Null,
                    -32600,
                    "request ID must be a string or integer",
                ));
            }
        },
    };
    let id_value = id.as_ref().map(|(_, id)| id.clone()).unwrap_or(Value::Null);
    if fields
        .get("jsonrpc")
        .and_then(|r| serde_json::from_str::<String>(r.get()).ok())
        .as_deref()
        != Some("2.0")
    {
        return Incoming::Error(error(id_value, -32600, "jsonrpc must be 2.0"));
    }
    let method = match fields
        .get("method")
        .and_then(|r| serde_json::from_str::<String>(r.get()).ok())
    {
        Some(method) => method,
        None if id.is_some() && (fields.contains_key("result") || fields.contains_key("error")) => {
            return Incoming::Ignored;
        }
        None => return Incoming::Error(error(id_value, -32600, "request method required")),
    };
    let params = fields
        .get("params")
        .map(|r| RawValue::from_string(r.get().to_owned()).expect("checked JSON"))
        .unwrap_or_else(|| RawValue::from_string("{}".into()).unwrap());
    if let Some((key, id)) = id {
        return Incoming::Request(Request {
            key,
            id,
            method,
            params,
            cancellation: Cancellation::default(),
        });
    }
    if method == "notifications/cancelled" {
        let fields = serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(params.get()).ok();
        if let Some(key) = fields
            .as_ref()
            .and_then(|f| f.get("requestId"))
            .and_then(|r| request_id(r))
            .map(|(key, _)| key)
        {
            return Incoming::Cancel(key);
        }
    }
    Incoming::Ignored
}
#[derive(Clone, Copy)]
enum Era {
    Undecided,
    Legacy { initialized: bool },
    Modern,
}
pub(super) struct Protocol {
    era: Era,
}
impl Default for Protocol {
    fn default() -> Self {
        Self {
            era: Era::Undecided,
        }
    }
}
#[derive(Deserialize)]
struct Initialize {
    #[serde(rename = "protocolVersion")]
    version: String,
    capabilities: BTreeMap<String, Value>,
    #[serde(rename = "clientInfo")]
    client: ClientInfo,
}
#[derive(Deserialize)]
struct ClientInfo {
    name: String,
    version: String,
}
#[derive(Deserialize)]
struct Call {
    name: String,
    arguments: Option<Box<RawValue>>,
}
fn metadata(params: &RawValue) -> Option<BTreeMap<String, Box<RawValue>>> {
    let fields: BTreeMap<String, Box<RawValue>> = serde_json::from_str(params.get()).ok()?;
    serde_json::from_str(fields.get("_meta")?.get()).ok()
}
impl Protocol {
    pub fn handle(&mut self, request: &Request, tools: &mut dyn ToolHandler) -> Value {
        let modern_envelope =
            metadata(&request.params).is_some_and(|meta| meta.contains_key(PROTOCOL));
        if matches!(self.era, Era::Undecided) {
            self.era = if request.method != "initialize" && modern_envelope {
                Era::Modern
            } else {
                Era::Legacy { initialized: false }
            };
        }
        let modern = matches!(self.era, Era::Modern);
        if modern {
            if request.method == "initialize" {
                let params: Value =
                    serde_json::from_str(request.params.get()).unwrap_or(Value::Null);
                let mut data = json!({"supported":[MODERN]});
                if let Some(version) = params["protocolVersion"].as_str() {
                    data["requested"] = json!(version);
                }
                return error_data(
                    request.id.clone(),
                    -32022,
                    "connection is serving the 2026-07-28 protocol; the initialize handshake is not accepted",
                    data,
                );
            }
            let Some(meta) = metadata(&request.params) else {
                return error(
                    request.id.clone(),
                    -32602,
                    "params._meta must be an object carrying the required protocol envelope keys",
                );
            };
            for key in [PROTOCOL, CAPABILITIES] {
                if !meta.contains_key(key) {
                    return error(
                        request.id.clone(),
                        -32602,
                        format!("params._meta is missing the required envelope key(s): {key}"),
                    );
                }
            }
            let version = match serde_json::from_str::<String>(meta[PROTOCOL].get()) {
                Ok(version) => version,
                Err(_) => {
                    return error(
                        request.id.clone(),
                        -32602,
                        "the protocol-version envelope value must be a string",
                    );
                }
            };
            if version != MODERN {
                return error_data(
                    request.id.clone(),
                    -32022,
                    "Unsupported protocol version",
                    json!({"supported":[MODERN],"requested":version}),
                );
            }
        } else if request.method != "initialize" && modern_envelope {
            return error(
                request.id.clone(),
                -32600,
                "this connection serves the handshake protocol era; requests carrying the 2026-07-28 envelope are not accepted on it",
            );
        }
        let response = self.dispatch(request, tools, modern);
        if modern && response.get("result").is_some() {
            let mut response = response;
            let value = &mut response["result"];
            value["resultType"] = json!("complete");
            value["_meta"] = json!({"io.modelcontextprotocol/serverInfo":server_info()});
            response
        } else {
            response
        }
    }
    fn dispatch(&mut self, request: &Request, tools: &mut dyn ToolHandler, modern: bool) -> Value {
        let id = request.id.clone();
        let params = if request.params.get() == "null" {
            "{}"
        } else {
            request.params.get()
        };
        if request.method == "initialize" {
            let input: Initialize = match serde_json::from_str(params) {
                Ok(input) => input,
                Err(e) => return error(id, -32602, e),
            };
            let _ = (
                &input.capabilities,
                &input.client.name,
                &input.client.version,
            );
            let version = if HANDSHAKE.contains(&input.version.as_str()) {
                input.version.as_str()
            } else {
                LATEST
            };
            self.era = Era::Legacy { initialized: true };
            return result(
                id,
                json!({"protocolVersion":version,"capabilities":capabilities(),"serverInfo":server_info()}),
            );
        }
        if !modern && request.method == "ping" {
            return result(id, json!({}));
        }
        if modern && request.method == "server/discover" {
            return result(
                id,
                json!({"supportedVersions":[MODERN],"capabilities":capabilities(),"ttlMs":0,"cacheScope":"private"}),
            );
        }
        if !matches!(request.method.as_str(), "tools/list" | "tools/call") {
            return error(id, -32601, "method not found");
        }
        if matches!(self.era, Era::Legacy { initialized: false }) {
            return error(
                id,
                -32002,
                "initialize the connection before invoking tools",
            );
        }
        if request.method == "tools/list" {
            let fields: BTreeMap<String, Box<RawValue>> = match serde_json::from_str(params) {
                Ok(fields) => fields,
                Err(e) => return error(id, -32602, e),
            };
            if fields.get("cursor").is_some_and(|r| r.get() != "null") {
                return error(id, -32602, "no pagination cursor is available");
            }
            let mut value = json!({"tools":tools.definitions()});
            if modern {
                value["ttlMs"] = json!(0);
                value["cacheScope"] = json!("private");
            }
            return result(id, value);
        }
        let input: Call = match serde_json::from_str(params) {
            Ok(input) => input,
            Err(e) => return error(id, -32602, e),
        };
        if !tools
            .definitions()
            .iter()
            .any(|definition| definition["name"] == input.name)
        {
            return error(id, -32602, format!("Unknown tool: {}", input.name));
        }
        if input
            .arguments
            .as_ref()
            .is_some_and(|raw| !raw.get().trim_start().starts_with('{'))
        {
            return error(id, -32602, "tool arguments must be an object");
        }
        let empty = RawValue::from_string("{}".into()).unwrap();
        let reply = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            tools.call(
                &input.name,
                input.arguments.as_deref().unwrap_or(&empty),
                request.cancellation.clone(),
            )
        }));
        let (text, is_error) = match reply {
            Ok(Ok(text)) => (text, false),
            Ok(Err(error)) => (error, true),
            Err(_) => ("internal tool error".into(), true),
        };
        result(
            id,
            json!({"content":[{"type":"text","text":text}],"isError":is_error}),
        )
    }
}
