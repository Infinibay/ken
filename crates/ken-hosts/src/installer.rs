//! Coordinate host configuration, bundle reconciliation and optional guidance.
//! Model/index/project setup and user-level host trust remain caller-owned.
use crate::{
    Bundles, HookHost, HostPlan, HostSelection, InstallOptions, NativeCommand, Result, codex,
    deepseek, digest, hex, hooks, instructions, invalid, json_bytes, jsonc,
    local::{MAX_BYTES, Root},
    plan::Builder,
    skills, unhex,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};
const STATE: &str = ".ken/installed-hosts.json";
const HOST_FILES: [&str; 8] = [
    ".claude/settings.json",
    ".mcp.json",
    ".codex/hooks.json",
    ".codex/config.toml",
    "opencode.json",
    "opencode.jsonc",
    deepseek::OVERLAY,
    ".codex/hooks.json.ken-backup",
];
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    sha256: String,
    before: Option<String>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Ownership {
    version: u32,
    files: BTreeMap<String, Receipt>,
}
struct Base {
    original: Option<Vec<u8>>,
    owned: bool,
}
impl Ownership {
    fn load(builder: &mut Builder) -> Result<Self> {
        let Some(bytes) = builder.read(STATE)? else {
            return Ok(Self {
                version: 1,
                files: BTreeMap::new(),
            });
        };
        let state: Self = serde_json::from_slice(&bytes)
            .map_err(|e| invalid(format!("Invalid host ownership: {e}")))?;
        if state.version != 1 {
            return Err(invalid("Invalid host ownership version"));
        }
        for (path, record) in &state.files {
            if !HOST_FILES.contains(&path.as_str())
                || record.sha256.len() != 64
                || !record
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err(invalid("Invalid managed host ownership"));
            }
            if let Some(before) = &record.before {
                if before.len() > MAX_BYTES * 2 {
                    return Err(invalid("host ownership byte budget exhausted"));
                }
                unhex(before)?;
            }
        }
        Ok(state)
    }
    fn save(&self, builder: &mut Builder) -> Result<()> {
        builder.write(
            STATE,
            if self.files.is_empty() {
                None
            } else {
                Some(json_bytes(self)?)
            },
        )
    }
    fn base(&self, builder: &mut Builder, path: &str) -> Result<Option<Base>> {
        let current = builder.read(path)?;
        if let Some(record) = self.files.get(path) {
            let before = record.before.as_deref().map(unhex).transpose()?;
            if current.as_ref().is_some_and(|b| digest(b) == record.sha256) || current == before {
                return Ok(Some(Base {
                    original: before,
                    owned: true,
                }));
            }
            builder.preserve(
                path,
                "locally modified host configuration; preserving the whole file",
            );
            return Ok(None);
        }
        Ok(Some(Base {
            original: current,
            owned: false,
        }))
    }
    fn publish(
        &mut self,
        builder: &mut Builder,
        path: &str,
        base: Base,
        content: Vec<u8>,
    ) -> Result<()> {
        self.files.insert(
            path.into(),
            Receipt {
                sha256: digest(&content),
                before: base.original.as_deref().map(hex),
            },
        );
        builder.write(path, Some(content))
    }
}
pub struct HostInstaller {
    root: Root,
    command: NativeCommand,
    bundles: Bundles,
}
impl HostInstaller {
    pub fn new(root: &Path, command: NativeCommand, bundles: Bundles) -> Result<Self> {
        let command = NativeCommand::new(command.program, command.prefix_args)?;
        Ok(Self {
            root: Root::new(root)?,
            command,
            bundles,
        })
    }
    pub fn plan_install(&self, options: &InstallOptions) -> Result<HostPlan> {
        let mut builder = Builder::new(self.root.duplicate()?);
        if options.no_wire {
            return Ok(builder.finish());
        }
        let selection = detect_local(&builder.root, options.hosts)?;
        let mut ownership = Ownership::load(&mut builder)?;
        if selection.claude {
            self.plan_hooks(
                &mut builder,
                &mut ownership,
                ".claude/settings.json",
                HookHost::Claude,
                false,
            )?;
            self.plan_claude_mcp(&mut builder, &mut ownership)?;
        }
        if selection.codex {
            if options.force_codex {
                if builder.root.exists(".codex")? && !builder.root.is_directory(".codex")? {
                    return Err(invalid(".codex exists and is not a directory"));
                }
                builder.owner_write(".codex");
            }
            self.plan_hooks(
                &mut builder,
                &mut ownership,
                ".codex/hooks.json",
                HookHost::Codex,
                options.force_codex,
            )?;
            self.plan_codex_mcp(&mut builder, &mut ownership)?;
        }
        if selection.opencode {
            self.plan_opencode(&mut builder, &mut ownership)?;
        }
        if selection.deepseek {
            self.plan_deepseek(&mut builder, &mut ownership)?;
        }
        ownership.save(&mut builder)?;
        builder.write_ahead();
        let skills = skills::plan_install(&mut builder, selection, &self.bundles)?;
        builder.report.preserved.extend(skills.preserved.clone());
        builder.report.skills = skills;
        let instructions =
            instructions::plan_install(&mut builder, options.instructions, selection.claude)?;
        builder
            .report
            .preserved
            .extend(instructions.preserved.clone());
        builder.report.instructions = instructions;
        Ok(builder.finish())
    }
    pub fn plan_uninstall(&self) -> Result<HostPlan> {
        let mut builder = Builder::new(self.root.duplicate()?);
        let mut ownership = Ownership::load(&mut builder)?;
        let records = ownership.files.clone();
        for (path, record) in &records {
            let current = builder.read(path)?;
            let before = record.before.as_deref().map(unhex).transpose()?;
            if current.as_ref().is_some_and(|b| digest(b) == record.sha256) {
                builder.write(path, before)?;
                ownership.files.remove(path);
            } else if current == before {
                ownership.files.remove(path);
            } else {
                builder.preserve(
                    path,
                    "locally modified host configuration; preserving the whole file",
                );
            }
        }
        self.report_unowned(&mut builder, &records)?;
        ownership.save(&mut builder)?;
        let skills = skills::plan_uninstall(&mut builder)?;
        builder.report.preserved.extend(skills.preserved.clone());
        builder.report.skills = skills;
        let instructions = instructions::plan_uninstall(&mut builder)?;
        builder
            .report
            .preserved
            .extend(instructions.preserved.clone());
        builder.report.instructions = instructions;
        Ok(builder.finish())
    }
    fn plan_hooks(
        &self,
        builder: &mut Builder,
        ownership: &mut Ownership,
        path: &str,
        host: HookHost,
        force: bool,
    ) -> Result<()> {
        let Some(base) = ownership.base(builder, path)? else {
            return Ok(());
        };
        let existing = match object(base.original.as_deref()) {
            Ok(value) => value,
            Err(error) if force || base.owned => {
                let backup = ".codex/hooks.json.ken-backup";
                let Some(backup_base) = ownership.base(builder, backup)? else {
                    return Err(error);
                };
                if backup_base.original.is_some() && !backup_base.owned {
                    return Err(invalid(
                        "Codex backup is user-owned; refusing to replace it",
                    ));
                }
                ownership.publish(
                    builder,
                    backup,
                    backup_base,
                    base.original.clone().unwrap_or_default(),
                )?;
                json!({})
            }
            Err(error) => return Err(error),
        };
        if !base.owned && hooks::has_ken(&existing, host, &self.command)? {
            builder.preserve(
                path,
                "existing Ken hooks are not managed by this installation",
            );
            return Ok(());
        }
        let (value, _) = hooks::merge(Some(&existing), host, &self.command)?;
        ownership.publish(builder, path, base, json_bytes(&value)?)
    }
    fn plan_claude_mcp(&self, builder: &mut Builder, ownership: &mut Ownership) -> Result<()> {
        let path = ".mcp.json";
        let Some(base) = ownership.base(builder, path)? else {
            return Ok(());
        };
        let mut value = object(base.original.as_deref())?;
        let servers = value
            .as_object_mut()
            .expect("object")
            .entry("mcpServers")
            .or_insert_with(|| json!({}))
            .as_object_mut()
            .ok_or_else(|| invalid("mcpServers must be an object"))?;
        if !base.owned && servers.contains_key("ken") {
            builder.preserve(
                path,
                "existing Ken MCP entry is not managed by this installation",
            );
            return Ok(());
        }
        servers.insert(
            "ken".into(),
            json!({"command":self.command.program,"args":self.command.mcp_args(None)}),
        );
        ownership.publish(builder, path, base, json_bytes(&value)?)
    }
    fn plan_codex_mcp(&self, builder: &mut Builder, ownership: &mut Ownership) -> Result<()> {
        let path = ".codex/config.toml";
        let Some(base) = ownership.base(builder, path)? else {
            return Ok(());
        };
        let text = utf8(base.original.as_deref().unwrap_or(&[]))?;
        if codex::has_registration(text)? {
            builder.preserve(
                path,
                "existing Ken TOML registration is not managed by this installation",
            );
            return Ok(());
        }
        let content = codex::append(text, &self.command)?;
        ownership.publish(builder, path, base, content.into_bytes())
    }
    fn plan_opencode(&self, builder: &mut Builder, ownership: &mut Ownership) -> Result<()> {
        let one = builder.read("opencode.json")?;
        let two = builder.read("opencode.jsonc")?;
        if one.is_some() && two.is_some() {
            for name in ["opencode.json", "opencode.jsonc"] {
                builder.preserve(name, "both OpenCode configs exist; leaving them alone");
            }
            return Ok(());
        }
        let path = if two.is_some() {
            "opencode.jsonc"
        } else {
            "opencode.json"
        };
        let Some(base) = ownership.base(builder, path)? else {
            return Ok(());
        };
        let text = utf8(base.original.as_deref().unwrap_or(b"{}"))?;
        let value = jsonc::parse(text)?;
        if !value.is_object() {
            return Err(invalid("OpenCode configuration must be an object"));
        }
        if let Some(mcp) = value.get("mcp") {
            let mcp = mcp
                .as_object()
                .ok_or_else(|| invalid("OpenCode mcp must be an object"))?;
            if mcp.contains_key("ken") {
                builder.preserve(
                    path,
                    "existing Ken OpenCode registration is not managed by this installation",
                );
                return Ok(());
            }
        }
        let desired = json!({"type":"local","command":std::iter::once(self.command.program.clone()).chain(self.command.mcp_args(None)).collect::<Vec<_>>(),"enabled":true});
        let output = if value.get("mcp").is_some() {
            jsonc::insert(text, &["mcp"], "ken", &desired)?
        } else {
            jsonc::insert(text, &[], "mcp", &json!({"ken":desired}))?
        };
        ownership.publish(builder, path, base, output.into_bytes())
    }
    fn plan_deepseek(&self, builder: &mut Builder, ownership: &mut Ownership) -> Result<()> {
        let path = deepseek::OVERLAY;
        let Some(base) = ownership.base(builder, path)? else {
            return Ok(());
        };
        let existing = match &base.original {
            Some(bytes) => serde_json::from_slice(bytes)?,
            None => json!([]),
        };
        let output = deepseek::merge(&existing, &builder.root.path, &self.command)?;
        if !base.owned && deepseek::has_ken(&existing) {
            builder.preserve(
                path,
                "existing Ken DeepSeek row is not managed by this installation",
            );
            return Ok(());
        }
        ownership.publish(builder, path, base, json_bytes(&output)?)
    }
    fn report_unowned(
        &self,
        builder: &mut Builder,
        known: &BTreeMap<String, Receipt>,
    ) -> Result<()> {
        for path in HOST_FILES {
            if known.contains_key(path) || path.ends_with(".ken-backup") {
                continue;
            }
            let Some(bytes) = builder.read(path)? else {
                continue;
            };
            let result = (|| -> Result<bool> {
                match path {
                    ".mcp.json" => Ok(object(Some(&bytes))?["mcpServers"].get("ken").is_some()),
                    ".claude/settings.json" => {
                        hooks::has_ken(&object(Some(&bytes))?, HookHost::Claude, &self.command)
                    }
                    ".codex/hooks.json" => {
                        hooks::has_ken(&object(Some(&bytes))?, HookHost::Codex, &self.command)
                    }
                    ".codex/config.toml" => codex::has_registration(utf8(&bytes)?),
                    "opencode.json" | "opencode.jsonc" => {
                        Ok(jsonc::parse(utf8(&bytes)?)?["mcp"].get("ken").is_some())
                    }
                    _ => Ok(deepseek::has_ken(&serde_json::from_slice(&bytes)?)),
                }
            })();
            match result {
                Ok(true) => builder.preserve(path, "unowned Ken host configuration left intact"),
                Ok(false) => {}
                Err(error) => {
                    builder.preserve(path, format!("unreadable host config left intact: {error}"))
                }
            }
        }
        Ok(())
    }
}
fn utf8(bytes: &[u8]) -> Result<&str> {
    std::str::from_utf8(bytes).map_err(|_| invalid("host configuration must be UTF8"))
}
fn object(bytes: Option<&[u8]>) -> Result<Value> {
    let Some(bytes) = bytes else {
        return Ok(json!({}));
    };
    let value: Value = serde_json::from_slice(bytes)?;
    if !value.is_object() {
        return Err(invalid("host configuration must be an object"));
    }
    jsonc::parse(utf8(bytes)?)?;
    Ok(value)
}
fn detect_local(root: &Root, forced: HostSelection) -> Result<HostSelection> {
    if forced.any() {
        return Ok(forced);
    }
    let mut selection = HostSelection {
        claude: root.exists(".claude")? || root.is_file(".mcp.json")?,
        codex: root.exists(".codex")?,
        opencode: root.is_file("opencode.json")?
            || root.is_file("opencode.jsonc")?
            || root.nonempty_directory(".opencode")?,
        deepseek: root.is_directory(".dsh")?,
    };
    if !selection.any() {
        selection.claude = true;
    }
    Ok(selection)
}
pub fn detect(root: &Path, forced: HostSelection) -> Result<HostSelection> {
    detect_local(&Root::new(root)?, forced)
}
