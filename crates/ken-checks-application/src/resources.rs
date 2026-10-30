use crate::{Error, Result};
use ken_query::execution::Cancellation;
use ken_structural::application::catalog::Catalog;
use ken_syntax::GrammarCatalog;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    ffi::OsString,
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
};
include!(concat!(env!("OUT_DIR"), "/identity.rs"));
#[derive(Clone, Debug)]
pub struct WorkerProgram {
    pub executable: PathBuf,
    pub arguments: Vec<OsString>,
}
impl WorkerProgram {
    pub fn new(executable: PathBuf) -> Self {
        Self {
            executable,
            arguments: Vec::new(),
        }
    }
}
#[derive(Clone, Debug)]
pub struct WorkerLimits {
    pub max_request_bytes: usize,
    pub max_response_bytes: usize,
    pub max_stderr_bytes: usize,
}
impl Default for WorkerLimits {
    fn default() -> Self {
        Self {
            max_request_bytes: 16_000_000,
            max_response_bytes: 16_000_000,
            max_stderr_bytes: 4096,
        }
    }
}
#[derive(Clone, Default)]
pub struct WorkerControl {
    pub cancellation: Cancellation,
    pub deadline: Option<Instant>,
}
impl WorkerControl {
    pub fn checkpoint(&self) -> Result<()> {
        if self.cancellation.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self
            .deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            return Err(Error::Timeout);
        }
        Ok(())
    }
    pub fn within(&self, duration: std::time::Duration) -> Result<Self> {
        self.checkpoint()?;
        let own = Instant::now().checked_add(duration).ok_or(Error::Timeout)?;
        let mut control = self.clone();
        control.deadline = Some(control.deadline.map_or(own, |old| old.min(own)));
        Ok(control)
    }
}
#[derive(Clone)]
pub struct Resources {
    pub grammar_manifest: PathBuf,
    pub packaged_libraries: BTreeMap<String, String>,
    pub worker: WorkerProgram,
    pub worker_limits: WorkerLimits,
    pub cache_mb: f64,
    pub max_file_bytes: u64,
    pub(crate) catalog: Arc<GrammarCatalog>,
}
#[derive(Clone, Serialize, Deserialize)]
pub(crate) struct WorkerResources {
    pub grammar_manifest: PathBuf,
    pub packaged_libraries: BTreeMap<String, String>,
    pub cache_mb: f64,
    pub max_file_bytes: u64,
}
impl Resources {
    pub fn prepared(manifest: &Path, worker: WorkerProgram) -> Result<Self> {
        let manifest = manifest.canonicalize()?;
        let catalog = Arc::new(GrammarCatalog::prepared(&manifest)?);
        Ok(Self {
            grammar_manifest: manifest,
            packaged_libraries: Catalog::packaged()?.libraries().clone(),
            worker,
            worker_limits: WorkerLimits::default(),
            cache_mb: 100.,
            max_file_bytes: 2_000_000,
            catalog,
        })
    }
    pub(crate) fn seal(mut self) -> Result<Self> {
        self.grammar_manifest = self.grammar_manifest.canonicalize()?;
        if !self.worker.executable.is_absolute() {
            return Err(Error::Invalid(
                "check worker requires an explicit absolute executable path".into(),
            ));
        }
        if self.worker_limits.max_request_bytes == 0 || self.worker_limits.max_response_bytes == 0 {
            return Err(Error::Invalid("worker pipe limits must be positive".into()));
        }
        self.catalog = Arc::new(GrammarCatalog::prepared(&self.grammar_manifest)?);
        self.identity()?;
        Ok(self)
    }
    pub(crate) fn packet(&self) -> WorkerResources {
        WorkerResources {
            grammar_manifest: self.grammar_manifest.clone(),
            packaged_libraries: self.packaged_libraries.clone(),
            cache_mb: self.cache_mb,
            max_file_bytes: self.max_file_bytes,
        }
    }
    pub fn identity(&self) -> Result<String> {
        self.packet().identity()
    }
    pub(crate) fn identity_checked(
        &self,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<String> {
        self.packet().identity_checked(check)
    }
}
impl WorkerResources {
    pub(crate) fn identity(&self) -> Result<String> {
        self.identity_checked(&mut || Ok(()))
    }
    pub(crate) fn identity_checked(
        &self,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<String> {
        check()?;
        let mut hash = Sha256::new();
        for value in [
            b"checks-native/1".as_slice(),
            IMPLEMENTATION_FINGERPRINT.as_bytes(),
            ken_structural::IMPLEMENTATION_FINGERPRINT.as_bytes(),
        ] {
            part(&mut hash, value);
        }
        let mut file = std::fs::File::open(&self.grammar_manifest)?;
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 8192];
        while bytes.len() <= 128 * 1024 {
            check()?;
            let n = file.read(&mut chunk)?;
            check()?;
            if n == 0 {
                break;
            }
            bytes.extend_from_slice(&chunk[..n]);
        }
        if bytes.len() > 128 * 1024 {
            return Err(Error::Invalid("grammar manifest exceeds128KiB".into()));
        }
        let manifest: serde_json::Value = serde_json::from_slice(&bytes)?;
        part_checked(&mut hash, &bytes, check)?;
        let parent = self
            .grammar_manifest
            .parent()
            .ok_or_else(|| Error::Invalid("grammar manifest has no directory".into()))?;
        let libraries = manifest["libraries"]
            .as_array()
            .ok_or_else(|| Error::Invalid("grammar inventory unavailable".into()))?;
        for library in libraries {
            let name = library["file"]
                .as_str()
                .ok_or_else(|| Error::Invalid("grammar filename unavailable".into()))?;
            if Path::new(name).file_name().and_then(|s| s.to_str()) != Some(name) {
                return Err(Error::Invalid("unsafe grammar resource filename".into()));
            }
            let expected = library["bytes"]
                .as_u64()
                .ok_or_else(|| Error::Invalid("grammar byte identity unavailable".into()))?;
            let mut file = std::fs::File::open(parent.join(name))?;
            let mut content_hash = Sha256::new();
            let mut count = 0u64;
            loop {
                check()?;
                let n = file.read(&mut chunk)?;
                check()?;
                if n == 0 {
                    break;
                }
                count = count
                    .checked_add(n as u64)
                    .ok_or_else(|| Error::Invalid("grammar byte count overflow".into()))?;
                if count > expected {
                    return Err(Error::Invalid(format!(
                        "grammar resource identity changed: {name}"
                    )));
                }
                content_hash.update(&chunk[..n]);
            }
            let digest = format!("{:x}", content_hash.finalize());
            if count != expected || library["sha256"].as_str() != Some(digest.as_str()) {
                return Err(Error::Invalid(format!(
                    "grammar resource identity changed: {name}"
                )));
            }
            part(&mut hash, name.as_bytes());
            part(&mut hash, digest.as_bytes());
        }
        let mut encoded = crate::worker::CheckedWriter::new(check, usize::MAX);
        serde_json::to_writer(&mut encoded, &self.packaged_libraries)?;
        part_checked(&mut hash, &encoded.finish(), check)?;
        check()?;
        part(&mut hash, &self.max_file_bytes.to_be_bytes());
        Ok(format!("{:x}", hash.finalize()))
    }
}
fn part(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_be_bytes());
    hash.update(bytes);
}

fn part_checked(
    hash: &mut Sha256,
    bytes: &[u8],
    check: &mut impl FnMut() -> Result<()>,
) -> Result<()> {
    hash.update((bytes.len() as u64).to_be_bytes());
    for chunk in bytes.chunks(8192) {
        check()?;
        hash.update(chunk);
    }
    Ok(())
}
