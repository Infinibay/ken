//! Small real-model integration of the indexing encoder adapter; no Python runtime.
use ken_index::{DocumentEncoder, encoder::ManagedDocumentEncoder};
use ken_models::{
    AcquisitionPolicy, ArtifactCache, LegacyRuntimeIdentity, ModelCatalog, ModelFactory,
    PreparedModelResources,
};
use serde_json::{Value, json};
use std::path::PathBuf;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let work = PathBuf::from(
        std::env::args_os()
            .nth(1)
            .ok_or("absolute private work path required")?,
    );
    if !work.is_absolute() {
        return Err("absolute private work path required".into());
    }
    let runtime = if cfg!(target_os = "macos") {
        include_str!("../../ken-models/tests/fixtures/profile-identity/macos.json")
    } else {
        include_str!("../../ken-models/tests/fixtures/profile-identity/linux.json")
    };
    let runtime: Value = serde_json::from_str(runtime)?;
    let legacy = LegacyRuntimeIdentity::from_json(&runtime["legacy_runtime"].to_string())?;
    let catalog = ModelCatalog::built_in()?;
    let spec = catalog.potion_spec();
    let mut resources =
        PreparedModelResources::new(&work.join("private"), &work.join("absent.npz"))?;
    resources.source_overrides.insert(
        spec.model_id.clone(),
        PathBuf::from(
            std::env::var_os("KEN_POTION_SNAPSHOT").ok_or("prepared Potion source required")?,
        ),
    );
    let factory = ModelFactory::new(
        catalog,
        ArtifactCache::new(&work.join("cache"))?,
        resources,
        AcquisitionPolicy::Offline,
    );
    let owner = factory.encoder(&spec, &legacy)?;
    assert!(!owner.is_prepared()?);
    let adapter = ManagedDocumentEncoder(owner);
    let texts = [
        "function refresh_index — Publish a complete changed-file generation.",
        "python snapshot_reader — Preserve prior source evidence while an index transaction commits.",
        "module_docstring — Native incremental indexing retains original source files.",
    ];
    let counts = texts
        .iter()
        .map(|s| adapter.token_count(s))
        .collect::<ken_retrieval::Result<Vec<_>>>()?;
    assert!(counts.iter().all(|n| *n > 0));
    let vectors = adapter.embed_passages(&texts)?;
    let dimension = adapter.dim()?;
    assert_eq!(vectors.len(), texts.len());
    assert_eq!(dimension, 256);
    for vector in &vectors {
        assert_eq!(vector.len(), dimension);
        assert!(vector.iter().all(|n| n.is_finite()));
        let norm = vector.iter().map(|n| n * n).sum::<f32>().sqrt();
        assert!(norm.is_finite() && norm > 0.);
    }
    assert_ne!(vectors[0], vectors[1]);
    assert!(adapter.0.is_prepared()?);
    let mut db = ken_store::ProjectDatabase::open(&work.join("smoke.db"))?;
    db.initialize()?;
    db.connection().execute(
        "INSERT INTO ci_files(path,content_hash,mtime,indexed_at)VALUES('fixture.input',x'00',0,0)",
        [],
    )?;
    let policy = ken_retrieval::PassagePolicy::new(1, "code-lexical-v1")?;
    let source = texts.join("\n");
    let passages = ken_retrieval::extract_passages(
        source.as_bytes(),
        &ken_syntax::ParsedFile::default(),
        "fixture.input",
        "text",
        &policy,
        &ken_retrieval::LexicalCounter,
    )?;
    assert_eq!(passages.len(), texts.len());
    let tx = db.immediate()?;
    let ids = ken_retrieval::storage::replace_file_passages(&tx, 1, &passages, None, &policy)?;
    let entries = ids
        .iter()
        .zip(texts)
        .zip(&vectors)
        .map(
            |((&passage_id, text), vector)| ken_retrieval::embedding_store::EmbeddingInput {
                passage_id,
                text: text.into(),
                vector: vector.clone(),
            },
        )
        .collect::<Vec<_>>();
    let revision = spec.key(&legacy)?;
    ken_retrieval::embedding_store::put_embeddings(&tx, "behavior", &revision, &entries)?;
    tx.commit()?;
    let stored =
        ken_retrieval::embedding_store::load_vectors(db.connection(), "behavior", &revision)?;
    assert_eq!(stored.ids, ids);
    for vector in &stored.matrix {
        let norm = vector.iter().map(|n| n * n).sum::<f32>().sqrt();
        assert!((norm - 1.).abs() < 1e-5);
    }

    println!(
        "{}",
        json!({"format":"ken-index-model-smoke/1","model":spec,"texts":texts,"token_counts":counts,"dimension":dimension,"vectors":vectors,"stored_vectors":stored.matrix,"preparation":adapter.0.preparation()?})
    );
    Ok(())
}
