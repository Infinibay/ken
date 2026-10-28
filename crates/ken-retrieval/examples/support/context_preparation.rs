//! Physical inputs and controlled encoding only; original answers never enter this caller.
#[path = "source_catalog.rs"]
mod source_catalog;
use ken_models::{ContextModel, EncoderSpec};
use ken_retrieval::{
    Result, RetrievalError,
    context_preparation::{ContextSourceEncoder, prepare_context},
    context_vector_cache::ContextVectorCache,
    query_encoder::QueryEncoder,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
pub use source_catalog::{Physical, ProbeResult, catalog};
use std::{cell::RefCell, collections::BTreeMap, fs, path::Path, rc::Rc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub kind: String,
    pub model_registration: Value,
    pub actions: Vec<Action>,
    pub physical: Option<Physical>,
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Action {
    Prepare {
        generation: i64,
    },
    Encoder {
        mode: String,
    },
    ClearSnapshots,
    DiskEdit,
    Corrupt {
        target: String,
    },
    CorruptCache {
        mode: String,
    },
    Get {
        text: String,
    },
    Put {
        text: String,
        mode: String,
        #[serde(default)]
        index: usize,
    },
    PutMany {
        items: Vec<Item>,
    },
    Reopen,
    Model {
        name: String,
    },
    Collision {
        text: String,
    },
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Item {
    text: String,
    mode: String,
}
pub struct Source {
    pub spec: EncoderSpec,
    pub view: EncoderSpec,
    pub mode: RefCell<String>,
    pub calls: RefCell<Vec<Vec<PythonText>>>,
}
impl Source {
    pub fn new(registration: &Value) -> ProbeResult<Self> {
        let full = ContextModel::from_json(&registration.to_string())?.compatible_identity();
        let mut projected = registration.clone();
        projected["document_projection"] =
            ken_retrieval::source_views::SOURCE_VIEW_PROJECTION.into();
        let view = ContextModel::from_json(&projected.to_string())?.compatible_identity();
        Ok(Self {
            spec: serde_json::from_value(full["spec"].clone())?,
            view: serde_json::from_value(view["spec"].clone())?,
            mode: RefCell::new("basis".into()),
            calls: RefCell::default(),
        })
    }
}
fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn vector(mode: &str, index: usize) -> Result<Vec<f32>> {
    let mut value = vec![0.; if mode == "short" { 767 } else { 768 }];
    if index >= value.len() {
        return Err(invalid("vector index outside dimension"));
    }
    value[index] = match mode {
        "nan" => f32::NAN,
        "zero" => 0.,
        "near-unit" => 0.99999,
        "unit" | "short" => 1.,
        _ => return Err(invalid("unknown vector mode")),
    };
    Ok(value)
}
fn bytes(values: &[f32]) -> Vec<u8> {
    values.iter().flat_map(|v| v.to_le_bytes()).collect()
}
impl QueryEncoder for Source {
    fn embed_query(&self, _: &PythonText) -> Result<Vec<f32>> {
        vector("unit", 0)
    }
}
impl ContextSourceEncoder for Source {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn view_spec(&self) -> &EncoderSpec {
        &self.view
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        self.calls.borrow_mut().push(texts.to_vec());
        let mode = self.mode.borrow();
        if *mode == "error" {
            return Err(invalid("encoder unavailable"));
        }
        texts
            .iter()
            .map(|t| {
                let scalar = t
                    .to_utf8()
                    .ok_or_else(|| invalid("source text requires UTF8"))?;
                let mut v = vector(
                    if *mode == "basis" { "unit" } else { &mode },
                    Sha256::digest(scalar.as_bytes())[0] as usize,
                )?;
                if *mode == "basis" {
                    for x in &mut v {
                        *x *= 2.;
                    }
                }
                Ok(v)
            })
            .collect()
    }
}
fn files(path: &Path) -> ProbeResult<Vec<std::path::PathBuf>> {
    if !path.exists() {
        return Ok(vec![]);
    }
    let mut all = fs::read_dir(path)?
        .map(|e| e.map(|e| e.path()))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    all.sort();
    Ok(all)
}
fn identity(path: &Path) -> ProbeResult<Value> {
    let b = fs::read(path)?;
    Ok(json!({"bytes":b.len(),"sha256":sha(&b)}))
}
fn state(directory: &Path) -> ProbeResult<Value> {
    let mut cache = Vec::new();
    if directory.join("vectors.db").exists() {
        let conn = rusqlite::Connection::open(directory.join("vectors.db"))?;
        let mut q =
            conn.prepare("SELECT model,hash,text,vector FROM vectors ORDER BY model,hash")?;
        for row in q.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, Vec<u8>>(3)?,
            ))
        })? {
            let (m, h, t, v) = row?;
            cache.push(
                json!({"model":m,"hash":h,"text":t,"vector_sha256":sha(&v),"vector_bytes":v.len()}),
            );
        }
    }
    let mut snapshots = BTreeMap::new();
    let mut temporary = 0;
    for path in files(&directory.join("snapshots"))? {
        if !path.is_dir() {
            continue;
        }
        let name = path
            .file_name()
            .ok_or("snapshot name required")?
            .to_str()
            .ok_or("scalar snapshot name required")?;
        if name.starts_with("prepare-") {
            temporary += 1;
            continue;
        }
        let mut artifacts = BTreeMap::new();
        for file in files(&path)? {
            if file.is_file() {
                artifacts.insert(
                    file.file_name()
                        .ok_or("artifact name required")?
                        .to_str()
                        .ok_or("scalar artifact name required")?
                        .to_owned(),
                    identity(&file)?,
                );
            }
        }
        snapshots.insert(name.to_owned(), artifacts);
    }
    Ok(json!({"cache":cache,"snapshots":snapshots,"temporary_count":temporary}))
}
fn spaced_json(value: &Value) -> String {
    match value {
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, v)| format!("{}: {}", serde_json::to_string(k).unwrap(), spaced_json(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        _ => serde_json::to_string(value).unwrap(),
    }
}
fn matrix(values: &[f32], shape: [usize; 2]) -> Value {
    json!({"shape":shape,"dtype":"float32","sha256":sha(&bytes(values)),"readonly":true})
}
pub fn observe(mut input: Input) -> ProbeResult<Value> {
    let home = tempfile::tempdir()?;
    let directory = home.path().join("cache");
    let source = Rc::new(Source::new(&input.model_registration)?);
    let physical = if input.kind == "prepare" {
        Some(catalog(
            input.physical.take().ok_or("physical input required")?,
        )?)
    } else if input.kind == "cache" && input.physical.is_none() {
        None
    } else {
        return Err("explicit cache/prepare kind required".into());
    };
    let mut key = source.spec.provided_key()?;
    let mut store = if input.kind == "cache" {
        Some(ContextVectorCache::open(&directory, &key)?)
    } else {
        None
    };
    let mut events = Vec::new();
    for action in input.actions {
        source.calls.borrow_mut().clear();
        let action_result = (|| -> ProbeResult<Value> {
            match action {
                Action::Prepare { generation } => {
                    let (_, catalog) = physical.as_ref().ok_or("catalog required")?;
                    let runtime = prepare_context(catalog, generation, source.clone(), &directory)?;
                    let full = runtime.source_snapshot();
                    let view = runtime.source_views().ok_or("views required")?;
                    let a = full.matrix();
                    let b = view.matrix();
                    Ok(
                        json!({"generation":full.generation(),"owners":full.owners(),"hashes":full.source_hashes(),"model":full.model(),"view_model":view.model(),"full":matrix(a.values,a.shape),"pool":matrix(b.values,b.shape),"rows":view.rows(),"mapped_views":b.is_mapped}),
                    )
                }
                Action::Encoder { mode } => {
                    *source.mode.borrow_mut() = mode;
                    Ok(Value::Null)
                }
                Action::ClearSnapshots => {
                    fs::remove_dir_all(directory.join("snapshots"))?;
                    Ok(Value::Null)
                }
                Action::DiskEdit => {
                    let (dir, c) = physical.as_ref().ok_or("catalog required")?;
                    let path = c.snapshots().keys().next().ok_or("file required")?;
                    fs::write(
                        dir.path().join(path),
                        b"changed after catalog construction\n",
                    )?;
                    Ok(Value::Null)
                }
                Action::Corrupt { target } => {
                    let dest = files(&directory.join("snapshots"))?
                        .into_iter()
                        .next()
                        .ok_or("snapshot required")?;
                    if target == "identity" || target == "manifest-fields" {
                        let path = dest.join("manifest.json");
                        let mut value: Value = serde_json::from_slice(&fs::read(&path)?)?;
                        if target == "identity" {
                            value["identity_sha256"] = "0".repeat(64).into();
                        } else {
                            value["artifacts"]
                                .as_object_mut()
                                .ok_or("artifacts required")?
                                .remove("views.npy");
                        }
                        // Match the original mutation, including observable artifact bytes.
                        fs::write(path, spaced_json(&value))?;
                    } else if matches!(target.as_str(), "full.npy" | "views.npy") {
                        fs::write(dest.join(target), b"corrupt")?;
                    } else {
                        return Err("unknown corruption target".into());
                    }
                    Ok(Value::Null)
                }
                Action::CorruptCache { mode } => {
                    let conn = rusqlite::Connection::open(directory.join("vectors.db"))?;
                    conn.execute("UPDATE vectors SET vector=?1", [bytes(&vector(&mode, 0)?)])?;
                    Ok(Value::Null)
                }
                Action::Get { text } => {
                    Ok(match store.as_ref().ok_or("cache required")?.get(&text)? {
                        None => Value::Null,
                        Some(v) => json!({"bytes":v.len()*4,"sha256":sha(&bytes(&v))}),
                    })
                }
                Action::Put { text, mode, index } => {
                    store
                        .as_mut()
                        .ok_or("cache required")?
                        .put_many(&[(text, vector(&mode, index)?)])?;
                    Ok(Value::Null)
                }
                Action::PutMany { items } => {
                    let items = items
                        .into_iter()
                        .map(|i| Ok((i.text, vector(&i.mode, 0)?)))
                        .collect::<Result<Vec<_>>>()?;
                    store.as_mut().ok_or("cache required")?.put_many(&items)?;
                    Ok(Value::Null)
                }
                Action::Reopen => {
                    drop(store.take());
                    store = Some(ContextVectorCache::open(&directory, &key)?);
                    Ok(Value::Null)
                }
                Action::Model { name } => {
                    drop(store.take());
                    let mut spec = source.spec.clone();
                    match name.as_str() {
                        "base" => (),
                        "other" => spec.model_id.push_str("/other"),
                        _ => return Err("unknown model".into()),
                    };
                    key = spec.provided_key()?;
                    store = Some(ContextVectorCache::open(&directory, &key)?);
                    Ok(Value::Null)
                }
                Action::Collision { text } => {
                    let conn = rusqlite::Connection::open(directory.join("vectors.db"))?;
                    conn.execute(
                        "UPDATE vectors SET text=?1 WHERE model=?2 AND hash=?3",
                        ["foreign", &key, &sha(text.as_bytes())],
                    )?;
                    Ok(Value::Null)
                }
            }
        })();
        let mut row = match action_result {
            Ok(v) => json!({"result":v}),
            Err(e) => json!({"error":{"type":"ValueError","message":e.to_string()}}),
        };
        row["calls"] = json!(source.calls.borrow().as_slice());
        row["state"] = state(&directory)?;
        events.push(row);
    }
    Ok(json!(events))
}
