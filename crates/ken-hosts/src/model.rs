use crate::{Result, invalid};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::Path};
pub type Bundles = BTreeMap<String, BTreeMap<String, Vec<u8>>>;
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct HostSelection {
    pub claude: bool,
    pub codex: bool,
    pub opencode: bool,
    pub deepseek: bool,
}
impl HostSelection {
    pub fn flags(self) -> [bool; 4] {
        [self.claude, self.codex, self.opencode, self.deepseek]
    }
    pub fn any(self) -> bool {
        self.flags().iter().any(|b| *b)
    }
}
#[derive(Clone, Debug)]
pub struct NativeCommand {
    pub program: String,
    pub prefix_args: Vec<String>,
}
impl NativeCommand {
    pub fn new(program: impl Into<String>, prefix_args: Vec<String>) -> Result<Self> {
        let program = program.into();
        if program.is_empty()
            || program.contains('\0')
            || prefix_args.iter().any(|a| a.contains('\0'))
        {
            return Err(invalid(
                "a native executable and NUL-free arguments are required",
            ));
        }
        Ok(Self {
            program,
            prefix_args,
        })
    }
    pub fn mcp_args(&self, root: Option<&Path>) -> Vec<String> {
        let mut args = self.prefix_args.clone();
        args.push("mcp".into());
        if let Some(root) = root {
            args.push(root.to_string_lossy().into_owned());
        }
        args
    }
    pub fn hook(&self, args: &[&str]) -> String {
        std::iter::once(self.program.clone())
            .chain(self.prefix_args.iter().cloned())
            .chain(std::iter::once("hook".into()))
            .chain(args.iter().map(|s| s.to_string()))
            .map(|s| shell_quote(&s))
            .collect::<Vec<_>>()
            .join(" ")
    }
}
pub(crate) fn shell_quote(value: &str) -> String {
    if !value.is_empty()
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&c))
    {
        value.into()
    } else {
        format!("'{}'", value.replace('\'', "'\"'\"'"))
    }
}
#[derive(Clone, Copy, Debug)]
pub enum HookHost {
    Claude,
    Codex,
}
#[derive(Clone, Debug, Default)]
pub struct InstallOptions {
    pub hosts: HostSelection,
    pub no_wire: bool,
    pub instructions: Option<bool>,
    pub force_codex: bool,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ResourceChanges {
    pub installed: Vec<String>,
    pub updated: Vec<String>,
    pub unchanged: Vec<String>,
    pub removed: Vec<String>,
    pub preserved: BTreeMap<String, String>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct InstallReport {
    pub changed: Vec<String>,
    pub preserved: BTreeMap<String, String>,
    pub skills: crate::skills::SkillChanges,
    pub instructions: crate::instructions::InstructionChanges,
}
