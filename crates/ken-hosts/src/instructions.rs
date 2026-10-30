//! Optional marked guidance has ownership separate from all user instructions.
use crate::{
    ResourceChanges, Result, catalog::embedded, digest, invalid, json_bytes, local::Root,
    plan::Builder,
};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::Path};
pub type InstructionChanges = ResourceChanges;
const STATE: &str = ".ken/instructions.json";
const AGENTS_START: &str = "<!-- ken:instructions:start -->";
const AGENTS_END: &str = "<!-- ken:instructions:end -->";
const CLAUDE_START: &str = "<!-- ken:agents-import:start -->";
const CLAUDE_END: &str = "<!-- ken:agents-import:end -->";
pub fn guidance() -> &'static str {
    embedded::GUIDANCE
}
fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\x1c'..='\x1f')
}
fn section(name: &str) -> (&'static str, &'static str, &'static str) {
    if name == "AGENTS.md" {
        (AGENTS_START, AGENTS_END, guidance())
    } else {
        (CLAUDE_START, CLAUDE_END, "@AGENTS.md\n")
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Record {
    sha256: String,
    created: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct State {
    version: u32,
    files: BTreeMap<String, Record>,
}
impl State {
    fn load(builder: &mut Builder) -> Result<Self> {
        let Some(bytes) = builder.read(STATE)? else {
            return Ok(Self {
                version: 1,
                files: BTreeMap::new(),
            });
        };
        let state: Self =
            serde_json::from_slice(&bytes).map_err(|e| invalid(format!("invalid {STATE}: {e}")))?;
        if state.version != 1
            || state.files.iter().any(|(name, record)| {
                !["AGENTS.md", "CLAUDE.md"].contains(&name.as_str())
                    || record.sha256.len() != 64
                    || !record
                        .sha256
                        .bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            })
        {
            return Err(invalid(format!("invalid ownership in {STATE}")));
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
}
fn region(text: &str, name: &str) -> Result<Option<(usize, usize)>> {
    let (start, end, _) = section(name);
    let a = text.find(start);
    let b = text.find(end);
    if a.is_none() && b.is_none() {
        return Ok(None);
    }
    if text.matches(start).count() != 1 || text.matches(end).count() != 1 || b < a {
        return Err(invalid(format!(
            "{name} has incomplete Ken markers; preserving it"
        )));
    }
    Ok(Some((
        a.expect("one start"),
        b.expect("one end") + end.len(),
    )))
}
fn user_guidance(text: &str) -> bool {
    for line in std::iter::once(0).chain(text.match_indices('\n').map(|(i, _)| i + 1)) {
        let rest = &text[line..];
        let Some(rest) = rest.strip_prefix("##") else {
            continue;
        };
        if !rest.chars().next().is_some_and(whitespace) {
            continue;
        }
        let rest = rest.trim_start_matches(whitespace);
        let prefix = "code intelligence:";
        if !rest
            .get(..prefix.len())
            .is_some_and(|s| s.eq_ignore_ascii_case(prefix))
        {
            continue;
        }
        let rest = rest[prefix.len()..].trim_start_matches(whitespace);
        if !rest.get(..3).is_some_and(|s| s.eq_ignore_ascii_case("ken")) {
            continue;
        }
        let rest = &rest[3..];
        if rest.is_empty()
            || rest
                .chars()
                .take_while(|c| whitespace(*c))
                .any(|c| c == '\n')
            || rest.chars().all(whitespace)
        {
            return true;
        }
    }
    false
}
enum Put {
    Installed,
    Updated,
    Unchanged,
    Skipped,
}
fn put(builder: &mut Builder, state: &mut State, name: &str) -> Result<Put> {
    let previous = builder.read(name)?;
    let text = std::str::from_utf8(previous.as_deref().unwrap_or(&[]))
        .map_err(|_| invalid(format!("{name} is not UTF8; preserving it")))?;
    let span = region(text, name)?;
    let old = state.files.get(name).cloned();
    if span.is_none() && name == "AGENTS.md" && user_guidance(text) {
        return Err(invalid(
            "AGENTS.md already has user-managed Ken guidance; preserving it",
        ));
    }
    if span.is_none()
        && name == "CLAUDE.md"
        && text
            .lines()
            .any(|s| matches!(s.trim_matches(whitespace), "@AGENTS.md" | "@./AGENTS.md"))
    {
        return Ok(Put::Skipped);
    }
    let newline = if text.contains("\r\n") { "\r\n" } else { "\n" };
    let (start, end, content) = section(name);
    let block =
        format!("{start}\n{}\n{end}", content.trim_end_matches(whitespace)).replace('\n', newline);
    let updated = if let Some((a, b)) = span {
        let current = &text[a..b];
        if current == block {
            return Ok(Put::Unchanged);
        }
        if old
            .as_ref()
            .is_none_or(|r| r.sha256 != digest(current.as_bytes()))
        {
            return Err(invalid(format!(
                "{name} has locally edited or unowned Ken guidance; preserving it"
            )));
        }
        format!("{}{block}{}", &text[..a], &text[b..])
    } else {
        let separator = if text.is_empty() {
            String::new()
        } else if text.ends_with('\n') {
            newline.into()
        } else {
            newline.repeat(2)
        };
        format!("{text}{separator}{block}{newline}")
    };
    let created = old.as_ref().map_or(previous.is_none(), |r| r.created);
    state.files.insert(
        name.into(),
        Record {
            sha256: digest(block.as_bytes()),
            created,
        },
    );
    builder.write(name, Some(updated.into_bytes()))?;
    Ok(if old.is_some() {
        Put::Updated
    } else {
        Put::Installed
    })
}
pub(crate) fn plan_install(
    builder: &mut Builder,
    choice: Option<bool>,
    claude: bool,
) -> Result<InstructionChanges> {
    let mut changes = InstructionChanges::default();
    if choice != Some(true) {
        return Ok(changes);
    }
    let mut state = match State::load(builder) {
        Ok(state) => state,
        Err(e) => {
            changes.preserved.insert(STATE.into(), e.to_string());
            return Ok(changes);
        }
    };
    for name in if claude {
        vec!["AGENTS.md", "CLAUDE.md"]
    } else {
        vec!["AGENTS.md"]
    } {
        match put(builder, &mut state, name) {
            Ok(Put::Installed) => changes.installed.push(name.into()),
            Ok(Put::Updated) => changes.updated.push(name.into()),
            Ok(Put::Unchanged) => changes.unchanged.push(name.into()),
            Ok(Put::Skipped) => {}
            Err(e) => {
                changes.preserved.insert(name.into(), e.to_string());
                break;
            }
        }
    }
    state.save(builder)?;
    Ok(changes)
}
pub(crate) fn plan_uninstall(builder: &mut Builder) -> Result<InstructionChanges> {
    let mut changes = InstructionChanges::default();
    let state = match State::load(builder) {
        Ok(state) => state,
        Err(e) => {
            changes.preserved.insert(STATE.into(), e.to_string());
            return Ok(changes);
        }
    };
    for (name, record) in state.files {
        let result = (|| -> Result<()> {
            let Some(bytes) = builder.read(&name)? else {
                return Ok(());
            };
            let text =
                std::str::from_utf8(&bytes).map_err(|_| invalid("instruction file is not UTF8"))?;
            let Some((a, b)) = region(text, &name)? else {
                return Ok(());
            };
            if digest(&text.as_bytes()[a..b]) != record.sha256 {
                return Err(invalid(format!("preserving locally edited {name}")));
            }
            let remaining = format!("{}{}", &text[..a], &text[b..]);
            builder.write(
                &name,
                if record.created && remaining.trim_matches(whitespace).is_empty() {
                    None
                } else {
                    Some(remaining.into_bytes())
                },
            )?;
            changes.removed.push(name.clone());
            Ok(())
        })();
        if let Err(e) = result {
            changes.preserved.insert(name, e.to_string());
        }
    }
    builder.write(STATE, None)?;
    Ok(changes)
}
pub fn install(root: &Path, choice: Option<bool>, claude: bool) -> Result<InstructionChanges> {
    let mut builder = Builder::new(Root::new(root)?);
    let changes = plan_install(&mut builder, choice, claude)?;
    builder.report.instructions = changes.clone();
    builder.report.preserved.extend(changes.preserved.clone());
    builder.finish().apply()?;
    Ok(changes)
}
pub fn uninstall(root: &Path) -> Result<InstructionChanges> {
    let mut builder = Builder::new(Root::new(root)?);
    let changes = plan_uninstall(&mut builder)?;
    builder.report.instructions = changes.clone();
    builder.report.preserved.extend(changes.preserved.clone());
    builder.finish().apply()?;
    Ok(changes)
}
