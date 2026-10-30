//! A plan captures expected bytes before any mutation and applies under the
//! project-directory lock. All components use the same confined atomic writer.
use crate::{
    InstallReport, Result, invalid,
    local::{MAX_BYTES, Root},
};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Debug, serde::Serialize)]
pub struct PlannedFile {
    pub path: String,
    pub expected_sha256: Option<String>,
    pub replacement_sha256: Option<String>,
    pub replacement: Option<Vec<u8>>,
}
pub struct HostPlan {
    root: Root,
    expected: BTreeMap<String, Option<Vec<u8>>>,
    writes: BTreeMap<String, Option<Vec<u8>>>,
    prunes: Vec<(String, String)>,
    owner_write: BTreeSet<String>,
    write_ahead: bool,
    report: InstallReport,
}
impl HostPlan {
    pub fn is_empty(&self) -> bool {
        self.writes.is_empty() && self.owner_write.is_empty()
    }
    pub fn changes(&self) -> Vec<PlannedFile> {
        self.writes
            .iter()
            .map(|(path, replacement)| PlannedFile {
                path: path.clone(),
                expected_sha256: self
                    .expected
                    .get(path)
                    .and_then(Option::as_deref)
                    .map(crate::digest),
                replacement_sha256: replacement.as_deref().map(crate::digest),
                replacement: replacement.clone(),
            })
            .collect()
    }
    pub fn report(&self) -> &InstallReport {
        &self.report
    }
    pub fn apply(mut self) -> Result<InstallReport> {
        if self.is_empty() {
            return Ok(self.report);
        }
        let _lock = self.root.lock()?;
        for (path, expected) in &self.expected {
            if self.root.read(path)? != *expected {
                return Err(invalid(format!(
                    "{path} changed after host configuration was planned"
                )));
            }
        }
        for path in &self.owner_write {
            self.root.add_owner_write(path)?;
        }
        // Host ownership is a write-ahead declaration. Interrupted publication can
        // safely recognize either the original bytes or the exact installed bytes.
        let journal = self.writes.remove(".ken/installed-hosts.json");
        let publish_journal = |value: &Option<Vec<u8>>| -> Result<()> {
            match value {
                Some(bytes) => self.root.write(".ken/installed-hosts.json", bytes),
                None => self.root.remove(".ken/installed-hosts.json"),
            }
        };
        if self.write_ahead
            && let Some(value) = &journal
        {
            publish_journal(value)?;
            self.report.changed.push(".ken/installed-hosts.json".into());
        }
        for (path, bytes) in &self.writes {
            match bytes {
                Some(bytes) => self.root.write(path, bytes)?,
                None => self.root.remove(path)?,
            }
            self.report.changed.push(path.clone());
        }
        if !self.write_ahead
            && let Some(value) = &journal
        {
            publish_journal(value)?;
            self.report.changed.push(".ken/installed-hosts.json".into());
        }
        self.prunes
            .sort_by_key(|(p, _)| std::cmp::Reverse(p.split('/').count()));
        for (path, boundary) in &self.prunes {
            self.root.prune(path, boundary);
        }
        Ok(self.report)
    }
}
pub(crate) struct Builder {
    pub root: Root,
    expected: BTreeMap<String, Option<Vec<u8>>>,
    writes: BTreeMap<String, Option<Vec<u8>>>,
    prunes: Vec<(String, String)>,
    owner_write: BTreeSet<String>,
    write_ahead: bool,
    pub report: InstallReport,
}
impl Builder {
    pub fn new(root: Root) -> Self {
        Self {
            root,
            expected: BTreeMap::new(),
            writes: BTreeMap::new(),
            prunes: vec![],
            owner_write: BTreeSet::new(),
            write_ahead: false,
            report: InstallReport::default(),
        }
    }
    pub fn read(&mut self, path: &str) -> Result<Option<Vec<u8>>> {
        crate::local::parts(path)?;
        if let Some(value) = self.writes.get(path) {
            return Ok(value.clone());
        }
        if let Some(value) = self.expected.get(path) {
            return Ok(value.clone());
        }
        let value = self.root.read(path)?;
        self.expected.insert(path.into(), value.clone());
        Ok(value)
    }
    pub fn write(&mut self, path: &str, bytes: Option<Vec<u8>>) -> Result<()> {
        if bytes.as_ref().is_some_and(|b| b.len() > MAX_BYTES) {
            return Err(invalid("managed file byte budget exhausted"));
        }
        let old = self.read(path)?;
        if old != bytes {
            self.writes.insert(path.into(), bytes);
        }
        Ok(())
    }
    pub fn preserve(&mut self, path: &str, reason: impl Into<String>) {
        self.report.preserved.insert(path.into(), reason.into());
    }
    pub fn prune(&mut self, path: String, boundary: String) {
        self.prunes.push((path, boundary));
    }
    pub fn owner_write(&mut self, path: &str) {
        self.owner_write.insert(path.into());
    }
    pub fn write_ahead(&mut self) {
        self.write_ahead = true;
    }
    pub fn finish(self) -> HostPlan {
        HostPlan {
            root: self.root,
            expected: self.expected,
            writes: self.writes,
            prunes: self.prunes,
            owner_write: self.owner_write,
            write_ahead: self.write_ahead,
            report: self.report,
        }
    }
}
