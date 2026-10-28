//! Generation-bound contextual source preparation and immutable artifact publication.
use crate::{
    Result,
    context_vector_cache::{CONTEXT_DIMENSION, ContextVectorCache, invalid, valid_vector},
    contextual::{ContextualRetriever, OwnerVectorSnapshot},
    dense_math::DenseMath,
    description::{OwnerDescription, describe_owner},
    npy_matrix::{MappedNpy, NpyWriter, file_sha},
    query_encoder::QueryEncoder,
    source_catalog::SourceCatalog,
    source_views::{SOURCE_VIEW_NAMES, SourceViewSnapshot, owner_view_texts},
};
use ken_models::EncoderSpec;
use ken_text::PythonText;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    fs,
    path::Path,
    rc::Rc,
};
pub trait ContextSourceEncoder: QueryEncoder {
    fn spec(&self) -> &EncoderSpec;
    fn view_spec(&self) -> &EncoderSpec;
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>>;
}
/// Python-compatible sorted JSON is a persistence identity, separate from display JSON.
pub(crate) fn identity_json(value: &Value, compact: bool) -> String {
    fn encode(value: &Value, compact: bool) -> String {
        let comma = if compact { "," } else { ", " };
        let colon = if compact { ":" } else { ": " };
        match value {
            Value::Object(m) => format!(
                "{{{}}}",
                m.iter()
                    .map(|(k, v)| format!(
                        "{}{colon}{}",
                        serde_json::to_string(k).expect("JSON key"),
                        encode(v, compact)
                    ))
                    .collect::<Vec<_>>()
                    .join(comma)
            ),
            Value::Array(a) => format!(
                "[{}]",
                a.iter()
                    .map(|v| encode(v, compact))
                    .collect::<Vec<_>>()
                    .join(comma)
            ),
            _ => serde_json::to_string(value).expect("JSON scalar"),
        }
    }
    let mut out = String::new();
    for c in encode(value, compact).chars() {
        let p = u32::from(c);
        if p <= 127 {
            out.push(c);
        } else if p <= 0xffff {
            out.push_str(&format!("\\u{p:04x}"));
        } else {
            let p = p - 0x10000;
            out.push_str(&format!(
                "\\u{:04x}\\u{:04x}",
                0xd800 + (p >> 10),
                0xdc00 + (p & 1023)
            ));
        }
    }
    out
}
fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn full_owner_text(description: &OwnerDescription) -> PythonText {
    let fields = &description.fields;
    let doc = &fields["documentation"].codepoints()
        [..fields["documentation"].codepoints().len().min(800)];
    let values = [
        PythonText::from(description.entity.path.clone()),
        fields["identity"].clone(),
        fields["signature"].clone(),
        PythonText::from_codepoints(
            [
                "Documentation: ".chars().map(u32::from).collect::<Vec<_>>(),
                doc.to_vec(),
            ]
            .concat(),
        )
        .expect("text points"),
        PythonText::from("Source:"),
        fields["implementation"].clone(),
    ];
    let mut points = Vec::new();
    for (i, v) in values.iter().enumerate() {
        if i > 0 {
            points.push(10);
        }
        points.extend_from_slice(v.codepoints());
    }
    PythonText::from_codepoints(points).expect("source points")
}
pub fn prepare_context(
    catalog: &SourceCatalog,
    generation: i64,
    encoder: Rc<dyn ContextSourceEncoder>,
    directory: &Path,
) -> Result<ContextualRetriever> {
    let mut ordered = catalog.owners().iter().collect::<Vec<_>>();
    ordered.sort_by_cached_key(|(key, _)| {
        identity_json(&serde_json::to_value(key).expect("owner identity"), true)
    });
    if ordered.is_empty() {
        return Err(invalid(
            "cannot prepare contextual search without source owners",
        ));
    }
    let model = encoder.spec().clone();
    let view_model = encoder.view_spec().clone();
    let model_key = model.provided_key()?;
    let view_key = view_model.provided_key()?;
    let owners = ordered
        .iter()
        .map(|(key, _)| key.clone())
        .collect::<Vec<_>>();
    let hashes = owners
        .iter()
        .map(|k| catalog.snapshots()[&k.path].hash().to_owned())
        .collect::<Vec<_>>();
    let mut texts = Vec::<String>::new();
    let mut digests = Vec::<String>::new();
    let mut lookup = HashMap::<String, usize>::new();
    let mut indexes = BTreeMap::<String, Vec<usize>>::from_iter(
        ["full", "contract", "implementation"]
            .into_iter()
            .map(|n| (n.into(), Vec::new())),
    );
    for (_, passages) in ordered {
        let description = describe_owner(passages)?;
        let projections = std::iter::once(("full".to_owned(), full_owner_text(&description)))
            .chain(owner_view_texts(&description));
        for (name, text) in projections {
            let text = text
                .to_utf8()
                .ok_or_else(|| invalid("context source text requires UTF8"))?;
            let hash = sha(text.as_bytes());
            let index = if let Some(&i) = lookup.get(&hash) {
                if texts[i] != text {
                    return Err(invalid("context source hash collision"));
                }
                i
            } else {
                let i = texts.len();
                lookup.insert(hash.clone(), i);
                texts.push(text);
                digests.push(hash);
                i
            };
            indexes
                .get_mut(&name)
                .expect("registered projection")
                .push(index);
        }
    }
    let identity = json!({"schema":1,"model":model_key,"view_model":view_key,"owners":owners,"source_hashes":hashes,"texts":digests,"indexes":indexes});
    let snapshot_key = sha(identity_json(&identity, true).as_bytes());
    let destination = directory.join("snapshots").join(&snapshot_key);
    if !destination.exists() {
        let parent = destination.parent().expect("snapshot parent");
        fs::create_dir_all(parent)
            .map_err(|e| invalid(format!("context snapshots directory: {e}")))?;
        let temporary = tempfile::Builder::new()
            .prefix("prepare-")
            .tempdir_in(parent)
            .map_err(|e| invalid(format!("context snapshot staging: {e}")))?;
        let mut pool = NpyWriter::create(
            &temporary.path().join("views.npy"),
            texts.len(),
            CONTEXT_DIMENSION,
        )?;
        {
            let mut cache = ContextVectorCache::open(directory, &model_key)?;
            for text in &texts {
                let vector = if let Some(v) = cache.get(text)? {
                    v
                } else {
                    let encoded = encoder.embed_passages(&[text.as_str().into()])?;
                    if encoded.len() != 1 {
                        return Err(invalid("context encoder must return one source vector"));
                    }
                    let mut vector = encoded.into_iter().next().expect("one source vector");
                    let norm = DenseMath::platform()?.norm(&vector)?;
                    if !norm.is_finite() || norm <= 1e-9 {
                        return Err(invalid("invalid contextual source norm"));
                    }
                    for v in &mut vector {
                        *v /= norm;
                    }
                    valid_vector(&vector)?;
                    cache.put_many(&[(text.clone(), vector.clone())])?;
                    vector
                };
                pool.row(&vector)?;
            }
        }
        pool.finish()?;
        let views_sha = file_sha(&temporary.path().join("views.npy"))?;
        // SAFETY: staging files are private to this publisher and never modified after finish.
        let pool = unsafe {
            MappedNpy::open(
                &temporary.path().join("views.npy"),
                &views_sha,
                texts.len(),
                CONTEXT_DIMENSION,
            )
        }?;
        let mut full = NpyWriter::create(
            &temporary.path().join("full.npy"),
            owners.len(),
            CONTEXT_DIMENSION,
        )?;
        for &i in &indexes["full"] {
            full.row(pool.row(i)?)?;
        }
        full.finish()?;
        drop(pool);
        let manifest = json!({"identity_sha256":snapshot_key,"artifacts":{"full.npy":file_sha(&temporary.path().join("full.npy"))?,"views.npy":views_sha}});
        fs::write(
            temporary.path().join("manifest.json"),
            identity_json(&manifest, false),
        )
        .map_err(|e| invalid(format!("context snapshot manifest: {e}")))?;
        match fs::rename(temporary.path(), &destination) {
            Ok(()) => (),
            Err(e) if matches!(e.raw_os_error(), Some(libc::EEXIST) | Some(libc::ENOTEMPTY)) => (),
            Err(e) => return Err(invalid(format!("context snapshot publish: {e}"))),
        }
    }
    let manifest: Value = serde_json::from_slice(
        &fs::read(destination.join("manifest.json"))
            .map_err(|e| invalid(format!("context artifact manifest: {e}")))?,
    )
    .map_err(|_| invalid("context artifact manifest mismatch"))?;
    let artifacts = manifest
        .get("artifacts")
        .and_then(Value::as_object)
        .ok_or_else(|| invalid("context artifact manifest mismatch"))?;
    if manifest.get("identity_sha256").and_then(Value::as_str) != Some(&snapshot_key)
        || artifacts.keys().map(String::as_str).collect::<Vec<_>>() != ["full.npy", "views.npy"]
    {
        return Err(invalid("context artifact manifest mismatch"));
    }
    let load = |name: &str, rows| {
        let hash = artifacts[name]
            .as_str()
            .ok_or_else(|| invalid("context artifact manifest mismatch"))?;
        // SAFETY: published cache snapshots are immutable; new generations publish by
        // atomic directory rename. Each mapping retains its checked file/inode.
        unsafe { MappedNpy::open(&destination.join(name), hash, rows, CONTEXT_DIMENSION) }
    };
    let full = load("full.npy", owners.len())?;
    let views = load("views.npy", texts.len())?;
    let full = OwnerVectorSnapshot::from_mapped(
        model.clone(),
        generation,
        owners.clone(),
        hashes.clone(),
        full,
    )?;
    let rows = SOURCE_VIEW_NAMES
        .into_iter()
        .map(|name| {
            Ok((
                name.to_owned(),
                indexes[name]
                    .iter()
                    .map(|&i| {
                        i64::try_from(i)
                            .map_err(|_| invalid("context index exceeds native integer range"))
                    })
                    .collect::<Result<Vec<_>>>()?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    let views = SourceViewSnapshot::from_mapped(
        view_model,
        generation,
        owners,
        hashes,
        views,
        rows,
        model.clone(),
    )?;
    let query: Rc<dyn QueryEncoder> = encoder;
    ContextualRetriever::new(query, model, full, Some(views))
}
