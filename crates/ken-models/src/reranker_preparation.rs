//! Publish only a complete verified derived cache, with no runtime dependency on Python.
use crate::{ModelError, PreparedReranker, RerankerModel, compile_head};
use std::{
    fs::{self, File},
    io::Write,
    path::Path,
};

fn io<T>(path: &Path, result: std::io::Result<T>) -> Result<T, ModelError> {
    result.map_err(|source| ModelError::Io {
        artifact: path.display().to_string(),
        source,
    })
}
fn write(path: &Path, bytes: &[u8]) -> Result<(), ModelError> {
    if let Some(parent) = path.parent() {
        io(parent, fs::create_dir_all(parent))?;
    }
    let mut file = io(path, File::create(path))?;
    io(path, file.write_all(bytes))?;
    io(path, file.sync_all())
}
fn sync_directory(path: &Path) -> Result<(), ModelError> {
    io(path, File::open(path))?
        .sync_all()
        .map_err(|source| ModelError::Io {
            artifact: path.display().to_string(),
            source,
        })
}

impl RerankerModel {
    pub fn prepare(
        &self,
        source: Option<&Path>,
        destination: &Path,
    ) -> Result<PreparedReranker, ModelError> {
        if destination.exists() {
            return self.verify_prepared(destination);
        }
        let source = source.ok_or_else(|| {
            ModelError::Artifact("explicit reranker source required for preparation".into())
        })?;
        let verified = self.source_assets().verify(source)?;
        let graph = compile_head(&verified)?;
        let parent = destination
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        io(parent, fs::create_dir_all(parent))?;
        let temporary = io(
            parent,
            tempfile::Builder::new()
                .prefix(".prepare-reranker-")
                .tempdir_in(parent),
        )?;
        // TempDir is0700; the published inner directory follows the ordinary umask.
        let ready = temporary.path().join("ready");
        io(&ready, fs::create_dir(&ready))?;
        write(&ready.join(self.graph_name()), &graph)?;
        for name in ["tokenizer.json", "config.json", "tokenizer_config.json"] {
            write(&ready.join(name), verified.artifact(name)?)?;
        }
        drop(graph);
        drop(verified);
        let prepared = self.verify_prepared(&ready)?;
        let graph_path = ready.join(self.graph_name());
        for directory in graph_path
            .ancestors()
            .skip(1)
            .take_while(|path| path.starts_with(&ready))
        {
            sync_directory(directory)?;
        }
        match fs::rename(&ready, destination) {
            Ok(()) => {
                sync_directory(parent)?;
                Ok(prepared)
            }
            Err(_) if destination.is_dir() => self.verify_prepared(destination),
            Err(source) => Err(ModelError::Io {
                artifact: destination.display().to_string(),
                source,
            }),
        }
    }
}
