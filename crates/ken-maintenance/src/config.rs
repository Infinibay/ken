//! User defaults are prospective; existing project selection stays ModelPolicy-owned.
use crate::Result;
use ken_models::{
    ModelCatalog,
    model_policy::{LEGACY_MODEL, ModelPolicy},
};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::{Path, PathBuf},
};
#[derive(Clone, Debug)]
pub struct ConfigEnvironment {
    pub config_dir: Option<PathBuf>,
    pub xdg_config_home: Option<PathBuf>,
    pub home: PathBuf,
}
#[derive(Clone, Debug)]
pub struct UserConfig {
    path: PathBuf,
}
impl UserConfig {
    pub fn new(environment: &ConfigEnvironment) -> Self {
        let selected = environment
            .config_dir
            .as_ref()
            .filter(|path| !path.as_os_str().is_empty())
            .map(|base| base.join("config.json"))
            .unwrap_or_else(|| {
                environment
                    .xdg_config_home
                    .as_ref()
                    .filter(|path| !path.as_os_str().is_empty())
                    .cloned()
                    .unwrap_or_else(|| environment.home.join(".config"))
                    .join("ken/config.json")
            });
        Self { path: selected }
    }
    pub fn path(&self) -> &Path {
        &self.path
    }
    fn read(&self) -> serde_json::Map<String, Value> {
        std::fs::read(&self.path)
            .ok()
            .and_then(|raw| serde_json::from_slice::<Value>(&raw).ok())
            .and_then(|value| value.as_object().cloned())
            .unwrap_or_default()
    }
    pub fn default_model(&self) -> Result<Option<String>> {
        Ok(self
            .read()
            .get("default_model")
            .and_then(Value::as_str)
            .filter(|value| value.chars().any(|c| !ken_text::unicode::whitespace(c)))
            .map(str::to_owned))
    }
    pub fn recommended_model(&self) -> Result<String> {
        Ok(ModelPolicy::new(self.default_model()?.as_deref())
            .recommended_model()
            .into())
    }
    pub fn set_default_model(&self, model: Option<&str>) -> Result<PathBuf> {
        let parent = self.path.parent().unwrap_or(Path::new("."));
        std::fs::create_dir_all(parent)?;
        let mut value = self.read();
        if let Some(model) = model.filter(|model| !model.is_empty()) {
            value.insert("default_model".into(), json!(model));
        } else {
            value.remove("default_model");
        }
        let mut file = tempfile::NamedTempFile::new_in(parent)?;
        if let Ok(metadata) = std::fs::metadata(&self.path) {
            file.as_file().set_permissions(metadata.permissions())?;
        }
        serde_json::to_writer_pretty(&mut file, &value)?;
        file.write_all(b"\n")?;
        file.as_file().sync_all()?;
        file.persist(&self.path).map_err(|error| error.error)?;
        std::fs::File::open(parent)?.sync_all()?;
        Ok(self.path.clone())
    }
}
#[derive(Clone, Debug)]
pub struct ModelSelection {
    pub model: String,
}
impl ModelSelection {
    pub fn resolve(
        conn: &Connection,
        config: &UserConfig,
        environment_model: Option<&str>,
        forced_model: Option<&str>,
    ) -> Result<Self> {
        let policy = ModelPolicy::new(config.default_model()?.as_deref());
        let selected =
            ken_retrieval::project_embeddings::resolve_project(conn, &policy, environment_model)?;
        Ok(Self {
            model: forced_model
                .filter(|model| !model.is_empty())
                .unwrap_or(&selected.model)
                .into(),
        })
    }
}
mod model_metadata;
pub fn models(config: &UserConfig, catalog: &ModelCatalog) -> Result<Value> {
    model_metadata::compose(config.recommended_model()?, LEGACY_MODEL, catalog.models())
}
