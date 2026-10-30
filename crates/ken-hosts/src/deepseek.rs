use crate::{NativeCommand, Result, invalid, model::shell_quote};
use serde_json::{Value, json};
use std::path::Path;
pub const OVERLAY: &str = ".dsh/ken.cordis.json";
pub const PLUGIN: &str = "@deepseek-ai/dsh-mcp-client";
pub fn entry(root: &Path, command: &NativeCommand) -> Result<Value> {
    let context = ken_core::project::DiscoveryContext::from_process()?;
    let paths = ken_core::project::ProjectPaths::at(root, &context)?;
    Ok(
        json!({"id":"ken-mcp","name":PLUGIN,"config":{"serverName":"ken","transport":"stdio","command":command.program,"args":command.mcp_args(Some(paths.root())),"cwd":paths.root()}}),
    )
}
pub fn launch_command(root: &Path) -> String {
    format!(
        "cd {} && dsh --profile web --patch {}",
        shell_quote(&root.to_string_lossy()),
        OVERLAY
    )
}
pub fn merge(existing: &Value, root: &Path, command: &NativeCommand) -> Result<Value> {
    let mut patches = existing
        .as_array()
        .cloned()
        .ok_or_else(|| invalid("Expected a Cordis patch list"))?;
    let desired = entry(root, command)?;
    let mut found = false;
    for patch in &mut patches {
        let patch = patch
            .as_object_mut()
            .ok_or_else(|| invalid("Cordis patches must be objects"))?;
        if let Some(insert) = patch.get_mut("insert") {
            for row in insert
                .as_array_mut()
                .ok_or_else(|| invalid("Expected an insert list"))?
            {
                if row["id"] == "ken-mcp" {
                    if found {
                        return Err(invalid("Duplicate ken-mcp entries"));
                    }
                    if row["name"] != PLUGIN {
                        return Err(invalid("Conflicting ken-mcp entry"));
                    }
                    let config = row
                        .as_object_mut()
                        .ok_or_else(|| invalid("Cordis rows must be objects"))?
                        .entry("config")
                        .or_insert_with(|| json!({}))
                        .as_object_mut()
                        .ok_or_else(|| invalid("Expected a config object"))?;
                    config.extend(
                        desired["config"]
                            .as_object()
                            .expect("generated config")
                            .clone(),
                    );
                    found = true;
                }
            }
        }
    }
    if !found {
        patches.push(json!({"insert":[desired]}));
    }
    Ok(json!(patches))
}
pub(crate) fn has_ken(existing: &Value) -> bool {
    existing.as_array().into_iter().flatten().any(|patch| {
        patch["insert"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|row| row["id"] == "ken-mcp")
    })
}
