//! Complete native endpoint histories, with explicit registered source resources.
#[path = "support/best_search.rs"]
mod support;
use ken_models::{
    AcquisitionPolicy, ArtifactCache, ModelCatalog, ModelFactory, NativeOnnxRuntime,
    PreparedModelResources,
};
use ken_retrieval::rank_models::ProductionRankModels;
use ken_search::RegisteredSearchResources;
use ken_syntax::GrammarCatalog;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, io::Read, path::PathBuf, rc::Rc, sync::Arc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    grammar_manifest: PathBuf,
    ranking_directory: PathBuf,
    runtime_registration: Value,
    library: PathBuf,
    sources: BTreeMap<String, PathBuf>,
    cache_parent: PathBuf,
    cases: Vec<Frame>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    id: String,
    input: support::Input,
}
fn run() -> support::ProbeResult<Value> {
    let mut raw = String::new();
    std::io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_string(&mut raw)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err("best search request exceeds8MiB".into());
    }
    let request: Request =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw)?)?;
    if request.cases.is_empty()
        || !request.cache_parent.is_absolute()
        || !request.library.is_absolute()
        || request.sources.values().any(|p| !p.is_absolute())
    {
        return Err("nonempty cases and absolute resources required".into());
    }
    let grammars = Arc::new(GrammarCatalog::prepared(&request.grammar_manifest)?);
    let ranks = Arc::new(ProductionRankModels::open(&request.ranking_directory)?);
    let runtime =
        NativeOnnxRuntime::from_json(&request.runtime_registration.to_string(), &request.library)?;
    let mut cases = Vec::new();
    for frame in request.cases {
        let directory = tempfile::tempdir_in(&request.cache_parent)?;
        let provider = if let Some(legacy) = frame.input.registered_runtime() {
            let mut resources = PreparedModelResources::new(
                &directory.path().join("owned"),
                &directory.path().join("unused.npz"),
            )?;
            resources.source_overrides = request.sources.clone();
            resources.onnx = Some(runtime.clone());
            let factory = Arc::new(ModelFactory::new(
                ModelCatalog::built_in()?,
                ArtifactCache::new(&directory.path().join("cache"))?,
                resources,
                AcquisitionPolicy::Offline,
            ));
            let provider = Rc::new(RegisteredSearchResources::new(
                factory,
                ranks.clone(),
                legacy,
            ));
            Some(Rc::new(move || provider.inputs())
                as Rc<
                    dyn Fn() -> ken_search::Result<ken_search::SearchResourceInputs>,
                >)
        } else {
            None
        };
        cases.push(json!({"id":frame.id,"events":support::observe(frame.input,grammars.clone(),provider)?}));
    }
    Ok(
        json!({"format":"ken-best-search-native/1","runtime":runtime.loaded_identity()?,"cases":cases}),
    )
}
fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1)
        }
    }
}
