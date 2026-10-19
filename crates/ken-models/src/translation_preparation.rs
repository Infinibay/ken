//! Normalize authenticated model data and publish only a complete verified cache.
use crate::{
    ModelError, PreparedTranslation, TranslationModel, translation_json,
    translation_model::TRANSLATION_FILES,
};
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

impl TranslationModel {
    pub fn prepare(
        &self,
        source: Option<&Path>,
        destination: &Path,
    ) -> Result<PreparedTranslation, ModelError> {
        self.check_destination(destination)?;
        if destination.exists() {
            return self.verify_prepared(destination);
        }
        let source = source.ok_or_else(|| {
            ModelError::Artifact("explicit translation source required for preparation".into())
        })?;
        let verified = self.source_assets().verify(source)?;
        let parent = destination
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        io(parent, fs::create_dir_all(parent))?;
        let stage = io(
            parent,
            tempfile::Builder::new()
                .prefix(".prepare-translation-")
                .tempdir_in(parent),
        )?;
        let ready = stage.path().join(
            destination
                .file_name()
                .expect("validated revision basename"),
        );
        io(&ready, fs::create_dir(&ready))?;
        for name in TRANSLATION_FILES {
            let bytes = verified.artifact(name)?;
            let output;
            let bytes = if matches!(name, "config.json" | "shared_vocabulary.json") {
                let mut normalized = translation_json::normalize(bytes)?;
                if name == "config.json" {
                    normalized.push(b'\n');
                }
                output = normalized;
                output.as_slice()
            } else {
                bytes
            };
            let path = ready.join(name);
            let mut file = io(&path, File::create(&path))?;
            io(&path, file.write_all(bytes))?;
            io(&path, file.sync_all())?;
        }
        drop(verified);
        let prepared = self.verify_prepared(&ready)?;
        io(&ready, io(&ready, File::open(&ready))?.sync_all())?;
        match fs::rename(&ready, destination) {
            Ok(()) => {
                io(parent, io(parent, File::open(parent))?.sync_all())?;
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
