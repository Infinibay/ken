//! Verified snapshot acquisition; transport, inference and compatibility stay separate.
use crate::{ModelAssets, ModelError, cache_directory::CacheDirectory, verified_file};
use std::{
    io::{self, Read},
    path::{Path, PathBuf},
};

#[derive(Clone, Debug)]
pub struct ArtifactRequest {
    pub model_id: String,
    pub revision: String,
    pub name: String,
}

pub trait ArtifactTransport: Send + Sync {
    fn open(&self, request: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AcquisitionPolicy {
    Offline,
    Public,
}

pub struct ArtifactCache {
    root: CacheDirectory,
}

fn io_error(name: &str, source: io::Error) -> ModelError {
    ModelError::Io {
        artifact: name.into(),
        source,
    }
}

fn verification_error(name: &str, error: verified_file::VerificationError) -> ModelError {
    match error {
        verified_file::VerificationError::Io(source) => io_error(name, source),
        verified_file::VerificationError::Invalid(_) => ModelError::Artifact(name.into()),
    }
}

/// Owns cleanup only while the staging name still identifies its original inode.
struct Stage<'a> {
    parent: &'a CacheDirectory,
    directory: CacheDirectory,
    name: String,
    published: bool,
}

impl<'a> Stage<'a> {
    fn new(parent: &'a CacheDirectory) -> io::Result<Self> {
        use ring::rand::{SecureRandom, SystemRandom};
        for _ in 0..16 {
            let mut random = [0_u8; 16];
            SystemRandom::new()
                .fill(&mut random)
                .map_err(|_| io::Error::other("cache staging randomness unavailable"))?;
            let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
            let name = format!("ken-artifacts-{suffix}");
            match parent.create_child_exclusive(&name) {
                Ok(directory) => {
                    let stage = Self {
                        parent,
                        directory,
                        name,
                        published: false,
                    };
                    parent.sync()?;
                    return Ok(stage);
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error),
            }
        }
        Err(io::Error::other("unable to allocate a unique cache stage"))
    }

    fn published(&mut self) {
        self.published = true;
    }
}

impl Drop for Stage<'_> {
    fn drop(&mut self) {
        if !self.published {
            // The parent checks the original inode; a substituted name is not
            // ours to remove. Cleanup also stays relative to held descriptors.
            let _ = self.parent.remove_owned_child(&self.name, &self.directory);
        }
    }
}

fn artifact_parent<'a>(
    root: &CacheDirectory,
    name: &'a str,
    create: bool,
) -> io::Result<(Option<CacheDirectory>, &'a str)> {
    let (parents, leaf) = name.rsplit_once('/').unwrap_or(("", name));
    let mut directory: Option<CacheDirectory> = None;
    for component in parents.split('/').filter(|s| !s.is_empty()) {
        directory = Some(
            directory
                .as_ref()
                .unwrap_or(root)
                .child(component, create)?,
        );
    }
    Ok((directory, leaf))
}

fn verify_cached(assets: &ModelAssets, directory: &CacheDirectory) -> Result<(), ModelError> {
    for (name, artifact) in assets.artifact_records() {
        let (parent, leaf) =
            artifact_parent(directory, name, false).map_err(|e| io_error(name, e))?;
        let file = parent
            .as_ref()
            .unwrap_or(directory)
            .read_file(leaf)
            .map_err(|e| io_error(name, e))?;
        verified_file::copy_stream(file, artifact.bytes, &artifact.sha256, &mut io::sink())
            .map_err(|e| verification_error(name, e))?;
    }
    directory
        .unchanged()
        .map_err(|e| io_error("cached snapshot", e))
}

impl ArtifactCache {
    pub(crate) fn contains_snapshot(&self, assets: &ModelAssets) -> Result<bool, ModelError> {
        self.root
            .unchanged()
            .map_err(|e| io_error("cache root", e))?;
        let found = self
            .root
            .child("models", false)
            .and_then(|models| models.child(&assets.fingerprint(), false))
            .and_then(|model| model.child(assets.revision(), false));
        match found {
            Ok(_) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(io_error("cached model snapshot", error)),
        }
    }
    pub(crate) fn ensure_capacity(&self, bytes: u64) -> Result<(), ModelError> {
        self.root
            .ensure_capacity(bytes)
            .map_err(|e| io_error("model free space plus3GiB reserve", e))
    }
    pub fn new(root: &Path) -> Result<Self, ModelError> {
        Ok(Self {
            root: CacheDirectory::root(root).map_err(|e| io_error("cache root", e))?,
        })
    }

    pub fn resolve(
        &self,
        assets: &ModelAssets,
        policy: AcquisitionPolicy,
        transport: &dyn ArtifactTransport,
    ) -> Result<PathBuf, ModelError> {
        self.root
            .unchanged()
            .map_err(|e| io_error("cache root", e))?;
        let models = self
            .root
            .child("models", true)
            .map_err(|e| io_error("cache models", e))?;
        let model = models
            .child(&assets.fingerprint(), true)
            .map_err(|e| io_error("cache model identity", e))?;
        let stable = || -> Result<(), ModelError> {
            for directory in [&self.root, &models, &model] {
                directory
                    .unchanged()
                    .map_err(|e| io_error("cache directory", e))?;
            }
            Ok(())
        };
        match model.child(assets.revision(), false) {
            Ok(directory) => {
                verify_cached(assets, &directory)?;
                stable()?;
                return Ok(directory.path);
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(io_error("cache snapshot", error)),
        }
        if policy == AcquisitionPolicy::Offline {
            return Err(ModelError::Artifact(
                "offline model snapshot missing".into(),
            ));
        }
        let mut stage = Stage::new(&model).map_err(|e| io_error("cache staging", e))?;
        for (name, artifact) in assets.artifact_records() {
            let request = ArtifactRequest {
                model_id: assets.model_id().into(),
                revision: assets.revision().into(),
                name: name.clone(),
            };
            let source = transport.open(&request)?;
            stable()?;
            stage
                .directory
                .unchanged()
                .map_err(|e| io_error("cache staging", e))?;
            let (parent, leaf) =
                artifact_parent(&stage.directory, name, true).map_err(|e| io_error(name, e))?;
            let directory = parent.as_ref().unwrap_or(&stage.directory);
            let mut file = directory.create_file(leaf).map_err(|e| io_error(name, e))?;
            verified_file::copy_stream(source, artifact.bytes, &artifact.sha256, &mut file)
                .map_err(|e| verification_error(name, e))?;
            file.sync_all().map_err(|e| io_error(name, e))?;
            directory.sync().map_err(|e| io_error(name, e))?;
        }
        stage
            .directory
            .sync()
            .map_err(|e| io_error("cache staging", e))?;
        stable()?;
        stage
            .directory
            .unchanged()
            .map_err(|e| io_error("cache staging", e))?;
        match model.publish(&stage.name, assets.revision()) {
            Ok(()) => stage.published(),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                let winner = model
                    .child(assets.revision(), false)
                    .map_err(|e| io_error("cache race winner", e))?;
                verify_cached(assets, &winner)?;
            }
            Err(error) => return Err(io_error("cache publication", error)),
        }
        stable()?;
        Ok(model.path.join(assets.revision()))
    }
}
