//! External validation consumer of the public project-source API.
use ken_core::{
    project::{DiscoveryContext, ProjectError, ProjectPaths},
    source_filter::SourceError,
    source_walk::ProjectSources,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    io::{self, Read},
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    root: PathBuf,
    scope: PathBuf,
}

fn text(path: &Path, root: &Path) -> Result<String, String> {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_str()
        .map(str::to_owned)
        .ok_or_else(|| "source observation cannot represent a non-UTF-8 path".into())
}
fn error(error: SourceError, root: &Path) -> Result<Value, String> {
    let (kind, path) = match error {
        SourceError::OutsideRoot { path }
        | SourceError::Project(ProjectError::EscapesRoot { path }) => {
            ("outside_project".into(), path)
        }
        SourceError::Cycle { path } => ("cycle".into(), path),
        SourceError::Rules { path, .. } => ("invalid_rules".into(), path),
        SourceError::Io { path, source }
        | SourceError::Project(ProjectError::Io { path, source }) => {
            (format!("io:{:?}", source.kind()), path)
        }
        SourceError::Project(ProjectError::Home { path }) => ("home_unavailable".into(), path),
    };
    Ok(json!({"kind":kind,"path":text(&path,root)?}))
}
fn append(values: &mut Vec<Value>, value: Value, budget: &mut usize) -> Result<(), String> {
    *budget += serde_json::to_vec(&value).map_err(|e| e.to_string())?.len() + 1;
    if *budget > 8 * 1024 * 1024 - 1024 {
        return Err("source observation exceeds8MiB".into());
    }
    values.push(value);
    Ok(())
}
fn main() -> Result<(), String> {
    let mut bytes = Vec::new();
    io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 1024 * 1024 {
        return Err("source request exceeds1MiB".into());
    }
    let request: Request = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if !request.root.is_absolute() {
        return Err("absolute project root required".into());
    }
    let context = DiscoveryContext {
        cwd: request.root.clone(),
        forced_root: None,
        home: Some(request.root.clone()),
    };
    let paths = ProjectPaths::at(&request.root, &context).map_err(|e| e.to_string())?;
    let root = paths.root().to_path_buf();
    let owner = ProjectSources::new(paths, context);
    let mut entries = vec![];
    let mut errors = vec![];
    let mut budget = 0;
    match owner.walk(&request.scope) {
        Ok(walk) => {
            for item in walk {
                match item {
                    Ok(entry) => append(
                        &mut entries,
                        serde_json::to_value(entry).map_err(|e| e.to_string())?,
                        &mut budget,
                    )?,
                    Err(e) => append(&mut errors, error(e, &root)?, &mut budget)?,
                }
            }
        }
        Err(e) => append(&mut errors, error(e, &root)?, &mut budget)?,
    }
    println!(
        "{}",
        json!({"format":"ken-source-observation/1","scope":request.scope,"entries":entries,"errors":errors})
    );
    Ok(())
}
