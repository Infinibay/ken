//! Existing v1 ownership receipts protect the entire locally edited bundle.
use crate::{
    Bundles, HostSelection, ResourceChanges, Result, digest, invalid, json_bytes,
    local::{Root, parts},
    plan::Builder,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};
pub type SkillChanges = ResourceChanges;
const MANIFEST: &str = ".ken/installed-skills.json";
const ROOTS: [&str; 4] = [
    ".claude/skills",
    ".agents/skills",
    ".opencode/skills",
    ".dsh/skills",
];
fn name_valid(name: &str) -> bool {
    name.strip_prefix("ken-").is_some_and(|tail| {
        tail.split('-').all(|part| {
            !part.is_empty()
                && part
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        })
    })
}
fn target_valid(target: &str) -> Result<()> {
    let parts = parts(target)?;
    if parts.len() != 3
        || !ROOTS.contains(&format!("{}/{}", parts[0], parts[1]).as_str())
        || !name_valid(parts[2])
    {
        return Err(invalid(format!("Invalid managed skill location: {target}")));
    }
    Ok(())
}
fn checksum_valid(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Ownership {
    version: u32,
    skills: BTreeMap<String, BTreeMap<String, String>>,
}
impl Ownership {
    fn load(builder: &mut Builder) -> Result<Self> {
        let Some(bytes) = builder.read(MANIFEST)? else {
            return Ok(Self {
                version: 1,
                skills: BTreeMap::new(),
            });
        };
        let value: Self = serde_json::from_slice(&bytes)
            .map_err(|e| invalid(format!("Invalid {MANIFEST}: {e}")))?;
        if value.version != 1 {
            return Err(invalid("Invalid installed-skills manifest version"));
        }
        for (target, resources) in &value.skills {
            target_valid(target)?;
            if !resources.contains_key("SKILL.md") {
                return Err(invalid("Invalid skill resources: missing SKILL.md"));
            }
            for (path, hash) in resources {
                parts(path)?;
                if !checksum_valid(hash) {
                    return Err(invalid("Invalid skill resource checksum"));
                }
            }
        }
        Ok(value)
    }
    fn save(&self, builder: &mut Builder) -> Result<()> {
        builder.write(
            MANIFEST,
            if self.skills.is_empty() {
                None
            } else {
                Some(json_bytes(
                    &serde_json::json!({"version":1,"skills":self.skills}),
                )?)
            },
        )
    }
    fn check(
        &self,
        builder: &mut Builder,
        target: &str,
        desired: &BTreeMap<String, Vec<u8>>,
    ) -> Option<String> {
        let inspect = (|| -> Result<Option<String>> {
            let previous = self.skills.get(target);
            let exists = builder.root.exists(target)?;
            if exists && previous.is_none() {
                return Ok(Some("existing skill is not managed by Ken".into()));
            }
            if exists && !builder.root.is_directory(target)? {
                return Ok(Some("skill location is not a directory".into()));
            }
            let names = previous
                .into_iter()
                .flat_map(|p| p.keys())
                .chain(desired.keys())
                .collect::<BTreeSet<_>>();
            for name in names {
                let path = format!("{target}/{name}");
                if let Some(bytes) = builder.read(&path)? {
                    let Some(expected) = previous.and_then(|p| p.get(name)) else {
                        return Ok(Some(format!(
                            "existing resource is not managed by Ken: {name}"
                        )));
                    };
                    if digest(&bytes) != *expected {
                        return Ok(Some(format!("locally modified resource: {name}")));
                    }
                }
            }
            Ok(None)
        })();
        match inspect {
            Ok(reason) => reason,
            Err(error) => Some(error.to_string()),
        }
    }
}
pub fn destinations(selection: HostSelection) -> Vec<String> {
    let mut out = Vec::new();
    if selection.claude {
        out.push(".claude/skills".into());
    }
    if selection.codex {
        out.push(".agents/skills".into());
    }
    if selection.opencode && out.is_empty() {
        out.push(".opencode/skills".into());
    }
    if selection.deepseek && !selection.codex {
        out.push(".dsh/skills".into());
    }
    out
}
pub(crate) fn plan_install(
    builder: &mut Builder,
    selection: HostSelection,
    bundles: &Bundles,
) -> Result<SkillChanges> {
    let mut changes = SkillChanges::default();
    let destinations = destinations(selection);
    if destinations.is_empty() {
        return Ok(changes);
    }
    let mut ownership = Ownership::load(builder)?;
    if bundles.is_empty() {
        return Err(invalid("The Ken package contains no bundled skills"));
    }
    for (name, resources) in bundles {
        if !name_valid(name) || !resources.contains_key("SKILL.md") {
            return Err(invalid("Invalid bundled skill definition"));
        }
        for path in resources.keys() {
            parts(path)?;
        }
    }
    for destination in destinations {
        for (name, resources) in bundles {
            let target = format!("{destination}/{name}");
            if let Some(reason) = ownership.check(builder, &target, resources) {
                changes.preserved.insert(target, reason);
                continue;
            }
            let previous = ownership.skills.get(&target);
            let mut changed = false;
            for (path, bytes) in resources {
                let path = format!("{target}/{path}");
                if builder.read(&path)?.as_deref() != Some(bytes.as_slice()) {
                    builder.write(&path, Some(bytes.clone()))?;
                    changed = true;
                }
            }
            for path in previous
                .into_iter()
                .flat_map(|p| p.keys())
                .filter(|p| !resources.contains_key(*p))
            {
                let path = format!("{target}/{path}");
                if builder.read(&path)?.is_some() {
                    builder.write(&path, None)?;
                    if let Some((parent, _)) = path.rsplit_once('/') {
                        builder.prune(parent.into(), target.clone());
                    }
                    changed = true;
                }
            }
            if previous.is_none() {
                changes.installed.push(target.clone());
            } else if changed {
                changes.updated.push(target.clone());
            } else {
                changes.unchanged.push(target.clone());
            }
            ownership.skills.insert(
                target,
                resources
                    .iter()
                    .map(|(name, bytes)| (name.clone(), digest(bytes)))
                    .collect(),
            );
        }
    }
    ownership.save(builder)?;
    Ok(changes)
}
pub(crate) fn plan_uninstall(builder: &mut Builder) -> Result<SkillChanges> {
    let mut changes = SkillChanges::default();
    let mut ownership = Ownership::load(builder)?;
    let targets = ownership.skills.keys().cloned().collect::<Vec<_>>();
    for target in targets {
        if let Some(reason) = ownership.check(builder, &target, &BTreeMap::new()) {
            changes.preserved.insert(target, reason);
            continue;
        }
        let resources = ownership
            .skills
            .remove(&target)
            .expect("selected ownership");
        for name in resources.keys() {
            let path = format!("{target}/{name}");
            builder.write(&path, None)?;
            if let Some((parent, _)) = path.rsplit_once('/') {
                builder.prune(parent.into(), target.clone());
            }
        }
        changes.removed.push(target);
    }
    ownership.save(builder)?;
    Ok(changes)
}
pub fn install(root: &Path, selection: HostSelection, bundles: &Bundles) -> Result<SkillChanges> {
    let mut builder = Builder::new(Root::new(root)?);
    let changes = plan_install(&mut builder, selection, bundles)?;
    builder.report.skills = changes.clone();
    builder.report.preserved.extend(changes.preserved.clone());
    builder.finish().apply()?;
    Ok(changes)
}
pub fn uninstall(root: &Path) -> Result<SkillChanges> {
    let mut builder = Builder::new(Root::new(root)?);
    let changes = plan_uninstall(&mut builder)?;
    builder.report.skills = changes.clone();
    builder.report.preserved.extend(changes.preserved.clone());
    builder.finish().apply()?;
    Ok(changes)
}
