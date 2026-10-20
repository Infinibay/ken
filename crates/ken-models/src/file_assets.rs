//! Source locations and independent, privately owned verified model files.
use crate::{
    ModelAssets, ModelError,
    assets::Artifact,
    verified_file::{self, VerificationError},
};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
};

#[derive(Clone, Debug)]
pub struct ModelFileSource {
    snapshot: PathBuf,
    private_parent: PathBuf,
}

impl ModelFileSource {
    pub fn new(snapshot: &Path, private_parent: &Path) -> Result<Self, ModelError> {
        if !snapshot.is_absolute() || !private_parent.is_absolute() {
            return Err(ModelError::Registration(
                "absolute model source and private parent required".into(),
            ));
        }
        Ok(Self {
            snapshot: snapshot.into(),
            private_parent: private_parent.into(),
        })
    }
}

/// Kept alive through every native session using these registered paths.
#[derive(Debug)]
pub struct VerifiedModelFiles {
    directory: tempfile::TempDir,
    artifacts: BTreeMap<String, Artifact>,
    fingerprint: String,
}

impl VerifiedModelFiles {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }

    pub fn read(&self, name: &str) -> Result<Vec<u8>, ModelError> {
        let record = self
            .artifacts
            .get(name)
            .ok_or_else(|| ModelError::Artifact(name.into()))?;
        verified_file::read(
            &self.directory.path().join(name),
            record.bytes,
            &record.sha256,
        )
        .map_err(|error| artifact_error(name, error))
    }

    pub(crate) fn artifact_path(&self, name: &str) -> Result<PathBuf, ModelError> {
        if !self.artifacts.contains_key(name) {
            return Err(ModelError::Artifact(name.into()));
        }
        Ok(self.directory.path().join(name))
    }

    pub(crate) fn root(&self) -> &Path {
        self.directory.path()
    }

    pub(crate) fn artifact_size(&self, name: &str) -> Option<u64> {
        self.artifacts.get(name).map(|record| record.bytes)
    }
}

fn artifact_error(name: &str, error: VerificationError) -> ModelError {
    match error {
        VerificationError::Io(source) => ModelError::Io {
            artifact: name.into(),
            source,
        },
        VerificationError::Invalid(_) => ModelError::Artifact(name.into()),
    }
}

fn io_error(name: &str, source: std::io::Error) -> ModelError {
    ModelError::Io {
        artifact: name.into(),
        source,
    }
}

fn private_directories(root: &Path, relative: &Path) -> std::io::Result<()> {
    let mut current = root.to_path_buf();
    for component in relative.components() {
        current.push(component);
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        if let Err(error) = builder.create(&current) {
            if error.kind() != std::io::ErrorKind::AlreadyExists {
                return Err(error);
            }
            let metadata = fs::symlink_metadata(&current)?;
            if !metadata.is_dir() || metadata.is_symlink() {
                return Err(std::io::Error::other("private model directory changed"));
            }
        }
    }
    Ok(())
}

pub(crate) fn verify(
    assets: &ModelAssets,
    source: &ModelFileSource,
) -> Result<VerifiedModelFiles, ModelError> {
    verify_with(assets, source, |path, record, destination| {
        verified_file::copy(path, record.bytes, &record.sha256, destination)
    })
}

// The copier is an ordinary I/O operation, allowing a real Write decorator in
// tests to interrupt an actual file copy without a product failure switch.
fn verify_with(
    assets: &ModelAssets,
    source: &ModelFileSource,
    mut copy: impl FnMut(&Path, &Artifact, &mut File) -> Result<(), VerificationError>,
) -> Result<VerifiedModelFiles, ModelError> {
    if source.snapshot.file_name().and_then(|name| name.to_str()) != Some(assets.revision())
        || !source.snapshot.is_dir()
    {
        return Err(ModelError::Registration(
            "registered revision directory required".into(),
        ));
    }
    let mut builder = tempfile::Builder::new();
    builder.prefix("ken-model-files-");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(fs::Permissions::from_mode(0o700));
    }
    let directory = builder
        .tempdir_in(&source.private_parent)
        .map_err(|error| io_error("private model staging", error))?;
    for (name, record) in assets.artifact_records() {
        let relative = Path::new(name);
        private_directories(
            directory.path(),
            relative.parent().unwrap_or_else(|| Path::new("")),
        )
        .map_err(|error| io_error(name, error))?;
        let path = directory.path().join(relative);
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut destination = options.open(&path).map_err(|error| io_error(name, error))?;
        copy(&source.snapshot.join(name), record, &mut destination)
            .map_err(|error| artifact_error(name, error))?;
        destination
            .sync_all()
            .map_err(|error| io_error(name, error))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            destination
                .set_permissions(fs::Permissions::from_mode(0o444))
                .map_err(|error| io_error(name, error))?;
        }
        #[cfg(not(unix))]
        {
            let mut permissions = destination
                .metadata()
                .map_err(|error| io_error(name, error))?
                .permissions();
            permissions.set_readonly(true);
            destination
                .set_permissions(permissions)
                .map_err(|error| io_error(name, error))?;
        }
    }
    Ok(VerifiedModelFiles {
        directory,
        artifacts: assets.artifact_records().clone(),
        fingerprint: assets.fingerprint(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::io::{self, Write};

    struct InterruptedWrite<'a> {
        destination: &'a mut File,
        source: &'a Path,
        truncate: bool,
        written: bool,
    }

    impl Write for InterruptedWrite<'_> {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            let count = self.destination.write(bytes)?;
            if !self.written {
                self.written = true;
                if self.truncate {
                    OpenOptions::new()
                        .write(true)
                        .open(self.source)?
                        .set_len(0)?;
                } else {
                    return Err(io::Error::other("interrupted actual destination write"));
                }
            }
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            self.destination.flush()
        }
    }

    #[test]
    fn interrupted_real_copy_cleans_staging_before_publishing() {
        for truncate in [true, false] {
            let temp = tempfile::tempdir().unwrap();
            let snapshot = temp.path().join("1111111111111111111111111111111111111111");
            let private = temp.path().join("private");
            fs::create_dir(&snapshot).unwrap();
            fs::create_dir(&private).unwrap();
            let bytes = vec![77_u8; 256 * 1024];
            fs::write(snapshot.join("weights"), &bytes).unwrap();
            let assets = ModelAssets::from_json(
                &serde_json::json!({"model_id":"test/interruption",
                "revision":"1111111111111111111111111111111111111111", "artifacts":{"weights":{
                    "bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))}}})
                .to_string(),
            )
            .unwrap();
            let source = ModelFileSource::new(&snapshot, &private).unwrap();
            let result = verify_with(&assets, &source, |path, record, destination| {
                let mut writer = InterruptedWrite {
                    destination,
                    source: path,
                    truncate,
                    written: false,
                };
                verified_file::copy(path, record.bytes, &record.sha256, &mut writer)
            });
            assert!(result.is_err(), "truncate={truncate}");
            assert_eq!(fs::read_dir(&private).unwrap().count(), 0);
            if truncate {
                assert_eq!(fs::metadata(snapshot.join("weights")).unwrap().len(), 0);
            }
        }
    }
}
