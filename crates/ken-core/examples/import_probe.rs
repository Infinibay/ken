//! Strict input-only external consumer of native import resolution.
use ken_core::imports::{ImportCatalog, ImportError, ImportRequest};
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{self, Read},
    path::PathBuf,
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    files: Vec<String>,
    imports: Vec<ImportRequest>,
    source: Source,
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase", deny_unknown_fields)]
enum Source {
    Inputs {
        configs: Option<BTreeMap<String, String>>,
    },
    Project {
        root: Option<PathBuf>,
    },
}
fn main() -> Result<(), String> {
    let mut bytes = Vec::new();
    io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err("import request exceeds8MiB".into());
    }
    let request: Request = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if request.cases.is_empty() || request.cases.len() > 4096 {
        return Err("1..4096import cases required".into());
    }
    let mut identities = BTreeSet::new();
    let mut rows = Vec::new();
    let mut budget = 0;
    for case in request.cases {
        if case.id.is_empty() || !identities.insert(case.id.clone()) {
            return Err("unique nonempty import case identities required".into());
        }
        let catalog = match case.source {
            Source::Inputs { configs } => {
                let configs = configs
                    .map(|values| {
                        values
                            .into_iter()
                            .map(|(name, hex)| {
                                if !hex.len().is_multiple_of(2)
                                    || !hex.bytes().all(|b| b.is_ascii_hexdigit())
                                {
                                    return Err(
                                        "strict hexadecimal config bytes required".to_owned()
                                    );
                                }
                                let bytes = (0..hex.len())
                                    .step_by(2)
                                    .map(|i| {
                                        u8::from_str_radix(&hex[i..i + 2], 16)
                                            .expect("validated ASCII hex")
                                    })
                                    .collect();
                                Ok((name, bytes))
                            })
                            .collect::<Result<BTreeMap<_, _>, String>>()
                    })
                    .transpose()?;
                ImportCatalog::from_inputs(case.files, configs)
            }
            Source::Project { root } => {
                if root.as_ref().is_some_and(|r| !r.is_absolute()) {
                    return Err("absolute project root required".into());
                }
                ImportCatalog::from_project(root.as_deref(), case.files)
            }
        };
        let row = match catalog {
            Ok(catalog) => {
                let results = case
                    .imports
                    .iter()
                    .map(|request| catalog.resolve(request))
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(|e| e.to_string())?;
                json!({"id":case.id,"results":results})
            }
            Err(ImportError::Config { path, reason }) => {
                json!({"id":case.id,"error":{"kind":"invalid_config","path":path,"reason":reason}})
            }
        };
        budget += serde_json::to_vec(&row).map_err(|e| e.to_string())?.len();
        if budget > 16 * 1024 * 1024 - 1024 {
            return Err("import response exceeds16MiB".into());
        }
        rows.push(row);
    }
    println!(
        "{}",
        json!({"format":"ken-import-observation/1","cases":rows})
    );
    Ok(())
}
