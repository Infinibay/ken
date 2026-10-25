//! Materialize declared physical inputs into an authenticated source catalog.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage, source_catalog::SourceCatalog, source_snapshot::SourceAuthority,
};
use serde::Deserialize;
use std::{collections::BTreeMap, fs, path::Component, sync::Arc};
pub type ProbeResult<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Physical {
    pub files: BTreeMap<String, Vec<u8>>,
    pub owners: Vec<Owner>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Owner {
    pub key: EntityKey,
    pub passages: Vec<Passage>,
}
pub fn catalog(input: Physical) -> ProbeResult<(tempfile::TempDir, SourceCatalog)> {
    let directory = tempfile::tempdir()?;
    for (name, bytes) in input.files {
        let relative = std::path::Path::new(&name);
        if !relative
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
            || relative.as_os_str().is_empty()
        {
            return Err("relative source paths required".into());
        }
        let path = directory.path().join(relative);
        fs::create_dir_all(path.parent().ok_or("source parent required")?)?;
        fs::write(path, bytes)?;
    }
    let context = DiscoveryContext {
        cwd: directory.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(directory.path(), &context)?;
    let source = Arc::new(SourceAuthority::new(&paths)?);
    let catalog = SourceCatalog::new(
        source,
        input
            .owners
            .into_iter()
            .map(|o| (o.key, o.passages))
            .collect(),
    )?;
    Ok((directory, catalog))
}
