//! Actual native preparation and query attempts; requests supply no expectations.
use ken_models::{
    FrozenTranslationRuntime, LocalQueryExpansion, ModelError, PreparedTranslation,
    TranslationModel,
};
use serde::Deserialize;
use serde_json::{Map, Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{collections::HashSet, fs, io::Read, path::PathBuf, time::Instant};
#[path = "support/observed_peak.rs"]
mod observed_peak;
mod support;

const FILES: [&str; 5] = [
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    registration: Box<RawValue>,
    source: Option<PathBuf>,
    cache: PathBuf,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    queries: Vec<String>,
    #[serde(default)]
    missing_assets: bool,
    corrupt_artifact: Option<String>,
    source_pieces_with_eos: Option<usize>,
}

fn artifact(bytes: &[u8]) -> Value {
    json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))})
}
fn artifacts(prepared: &PreparedTranslation) -> Result<Value, ModelError> {
    let mut out = Map::new();
    for name in FILES {
        out.insert(name.into(), artifact(prepared.artifact(name)?));
    }
    Ok(Value::Object(out))
}
fn sample(
    peaks: &mut observed_peak::ObservedPeak,
    samples: &mut Vec<Value>,
    phase: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let peak = peaks.record(support::peak_rss()?)?;
    samples.push(json!({"phase":phase,"reported_hwm_bytes":peak.reported_hwm_bytes,"observed_peak_bytes":peak.observed_peak_bytes}));
    Ok(())
}
fn failure(error: ModelError) -> Value {
    let kind = match &error {
        ModelError::Registration(_) => "registration",
        ModelError::Json(_) => "json",
        ModelError::Io { .. } => "io",
        ModelError::Artifact(_) => "artifact",
        ModelError::Tokenizer(_) => "tokenizer",
        ModelError::Weights(_) => "weights",
        ModelError::Inference(_)
        | ModelError::RelevanceBudget
        | ModelError::RelevanceEmptyDocuments
        | ModelError::RelevanceNonfinite => "inference",
        ModelError::Runtime(_) => "runtime",
    };
    let message = match &error {
        ModelError::Inference(message) => message.clone(),
        _ => error.to_string(),
    };
    json!({"type":"ModelError","kind":kind,"message":message})
}

fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    let unique: HashSet<_> = request.cases.iter().map(|case| case.id.as_str()).collect();
    if request.cases.is_empty()
        || unique.len() != request.cases.len()
        || request.cases.iter().any(|c| {
            c.id.is_empty()
                || c.queries.is_empty()
                || c.corrupt_artifact
                    .as_ref()
                    .is_some_and(|s| !FILES.contains(&s.as_str()))
        })
        || !request.cache.is_absolute()
        || request.source.as_ref().is_some_and(|p| !p.is_absolute())
    {
        return Err("distinct nonempty histories and absolute cache/source paths required".into());
    }
    let profile = if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        FrozenTranslationRuntime::MacOS483
    } else if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        FrozenTranslationRuntime::Linux482
    } else {
        return Err("registered native translation platform required".into());
    };
    let model = TranslationModel::from_json(request.registration.get())?;
    let mut peaks = observed_peak::ObservedPeak::default();
    let mut memory = Vec::new();
    sample(&mut peaks, &mut memory, "before-prepare".into())?;
    let started = Instant::now();
    let mut source_artifacts = Map::new();
    if let Some(source) = &request.source {
        let verified = model.source_assets().verify(source)?;
        for name in FILES {
            source_artifacts.insert(name.into(), artifact(verified.artifact(name)?));
        }
    }
    let fresh_cache = match fs::symlink_metadata(&request.cache) {
        Ok(_) => false,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => true,
        Err(error) => return Err(error.into()),
    };
    let first = model.prepare(request.source.as_deref(), &request.cache)?;
    let prepared_artifacts = artifacts(&first)?;
    drop(first);
    let reused = model.prepare(None, &request.cache)?;
    if artifacts(&reused)? != prepared_artifacts {
        return Err("reused native cache differs".into());
    }
    drop(reused);
    let prepare_ns = started.elapsed().as_nanos();
    sample(&mut peaks, &mut memory, "after-prepare".into())?;
    let mut results = Vec::new();
    for (case_index, case) in request.cases.into_iter().enumerate() {
        let mut changed = None;
        let cache = if case.missing_assets {
            request
                .cache
                .parent()
                .ok_or("cache parent required")?
                .join(format!("missing-{case_index}"))
                .join(
                    request
                        .cache
                        .file_name()
                        .ok_or("revision basename required")?,
                )
        } else if let Some(name) = &case.corrupt_artifact {
            let parent = tempfile::tempdir()?;
            let cache = parent.path().join(
                request
                    .cache
                    .file_name()
                    .ok_or("revision basename required")?,
            );
            fs::create_dir(&cache)?;
            for name in FILES {
                fs::copy(request.cache.join(name), cache.join(name))?;
            }
            let path = cache.join(name);
            let mut bytes = fs::read(&path)?;
            if bytes.is_empty() {
                return Err("nonempty corrupt artifact required".into());
            }
            bytes[0] ^= 1;
            fs::write(path, bytes)?;
            changed = Some(parent);
            cache
        } else {
            request.cache.clone()
        };
        let started = Instant::now();
        let engine = LocalQueryExpansion::new(model.clone(), None, cache)?;
        let constructor_ns = started.elapsed().as_nanos();
        let mut calls = Vec::new();
        sample(&mut peaks, &mut memory, format!("{}.before-calls", case.id))?;
        for (index, query) in case.queries.iter().enumerate() {
            let started = Instant::now();
            let attempt = engine.expand_attempt(query);
            let wall_ns = started.elapsed().as_nanos();
            let policy = engine.runtime_identity()?;
            let options = policy.as_ref().map(
                |p| json!({"beam_size":p.beam_size,"max_decoding_length":p.max_decoding_length}),
            );
            let mut trace = Map::new();
            if let Some(input) = attempt.input {
                if index == 0
                    && case
                        .source_pieces_with_eos
                        .is_some_and(|n| n != input.tokens.pieces_with_eos.len())
                {
                    return Err(
                        "observed source boundary differs from requested characterization".into(),
                    );
                }
                trace.insert("prepared".into(), json!(input.prepared));
                trace.insert("source_ids".into(), json!(input.tokens.ids));
                trace.insert(
                    "source_pieces_with_eos".into(),
                    json!(input.tokens.pieces_with_eos),
                );
                trace.insert(
                    "options".into(),
                    options.ok_or("encoded input requires native runtime")?,
                );
            }
            let mut call = Map::new();
            match attempt.result {
                Ok(value) => {
                    call.insert("output".into(), json!(value.text));
                    if let Some(value) = value.trace {
                        trace.insert("hypotheses".into(), json!(value.hypotheses));
                        trace.insert("decoded".into(), json!(value.decoded));
                    }
                }
                Err(error) => {
                    call.insert("error".into(), failure(error));
                }
            }
            call.insert("wall_ns".into(), json!(wall_ns));
            call.insert("trace".into(), json!(trace));
            call.insert("runtime_loaded".into(), json!(engine.is_loaded()));
            calls.push(Value::Object(call));
            sample(
                &mut peaks,
                &mut memory,
                format!("{}.after-call{index}", case.id),
            )?;
        }
        results.push(json!({"id":case.id,"calls":calls,"constructor_ns":constructor_ns,
            "identity":model.compatible_identity(profile),"revision":model.compatible_revision(profile),
            "actual_runtime":engine.runtime_identity()?}));
        drop(engine);
        drop(changed);
    }
    Ok(
        json!({"format":"ken-translation-native/1","preparation":{"fresh_cache":fresh_cache,
        "reused_without_source":true,"source_artifacts":source_artifacts,"artifacts":prepared_artifacts,
        "recipe_key":model.recipe_key()},"prepare_ns":prepare_ns,"runtime":{"engine":"rust","ken_models":env!("CARGO_PKG_VERSION")},
        "memory_samples":memory,"results":results}),
    )
}
fn main() {
    match run().and_then(|value| Ok(serde_json::to_string(&value)?)) {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("translation_probe: {error}");
            std::process::exit(1)
        }
    }
}
