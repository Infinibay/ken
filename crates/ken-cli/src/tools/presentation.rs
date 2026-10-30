//! Keep transport data intact while applying the common compact projection.
use super::ToolReply;
use ken_core::tool_output::{Document, render};
pub(super) fn raw_json(
    raw: String,
    name: &str,
    format: &str,
    full: bool,
) -> Result<ToolReply, String> {
    match format {
        "json" => Ok(ToolReply::Json(raw)),
        "compact" => match Document::parse_json(&raw) {
            Ok(document) => Ok(ToolReply::Text(render(&document, name, full))),
            Err(_) => Ok(ToolReply::Json(raw)),
        },
        _ => Err("output_format must be compact or json".into()),
    }
}
