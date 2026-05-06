//! Quality-of-results tests for the ranker on a controlled synthetic corpus.
//!
//! These tests use `MockEmbedder` (deterministic, hash-based) so they're
//! reproducible without ONNX downloads. Because mock embeddings are noisy
//! and don't carry real semantics, we calibrate the ranker config to
//! *exercise the plumbing* — the goal is to catch regressions in the
//! confidence gate, MAD filter, and channel merge under realistic shapes,
//! not to prove embedding quality (that's `end_to_end_quality.rs`).
//!
//! What's covered:
//! * `recall_at_k_*` — ingest N chunks, run K queries with known target,
//!   assert the target appears in top-K. Lower bound, not "win-rate".
//! * `confidence_gate_*` — query that has nothing in the corpus must
//!   return an empty result; the gate should fire before MAD even runs.
//! * `mad_filter_*` — corpus with one clear winner + a long tail of
//!   noise chunks; only the winner (and a small neighborhood) survives.
//!
//! Run with:
//!     DATABASE_URL=postgres://cae:cae_dev@localhost:5432/context_engine \
//!     cargo test -p ken-engine --features postgres --test ranker_quality \
//!         --ignored

#![cfg(feature = "postgres")]

use engine::embed::{Embedder, MockEmbedder};
use engine::postgres::PostgresStorage;
use engine::rank::{RankRequest, Ranker, RankerConfig};
use engine::storage::{NewChunk, NewDocument, NewSource};
use engine::types::*;

async fn setup() -> Option<(PostgresStorage, WorkspaceId, SourceId)> {
    let url = std::env::var("DATABASE_URL").ok()?;
    let s = PostgresStorage::connect(&url).await.expect("connect");
    s.migrate().await.expect("migrate");
    let t = s
        .create_tenant("quality", PlanTier::Free)
        .await
        .expect("tenant");
    let w = s
        .create_workspace(t, "ws", WorkspaceSettings::default())
        .await
        .expect("workspace");
    let src = s
        .create_source(NewSource {
            workspace_id: w,
            kind: SourceKind::Manual,
            name: "manual".into(),
            config_json: serde_json::Value::Null,
            keep_history: false,
            default_acl: Acl::default(),
        })
        .await
        .expect("source");
    Some((s, w, src))
}

fn doc(w: WorkspaceId, src: SourceId, ext: &str, hash_seed: u8) -> NewDocument {
    NewDocument {
        workspace_id: w,
        source_id: src,
        external_id: Some(ext.into()),
        kind: ContentKind::PlainText,
        mime: "text/plain".into(),
        title: Some(ext.into()),
        path_or_url: None,
        content_hash: [hash_seed; 32],
        acl: Acl::default(),
        metadata: MetadataMap::default(),
        source_modified_at: None,
    }
}

/// Insert a doc with a single chunk. Returns `(document_id, chunk_id)`.
async fn ingest_one(
    s: &PostgresStorage,
    embedder: &MockEmbedder,
    w: WorkspaceId,
    src: SourceId,
    ext: &str,
    hash_seed: u8,
    text: &str,
) -> (DocumentId, ChunkId) {
    let did = s.upsert_document(doc(w, src, ext, hash_seed)).await.unwrap().current_id();
    let cids = s
        .replace_chunks(
            did,
            vec![NewChunk {
                kind: ChunkKind::Paragraph,
                position: ChunkPosition::ByteRange { start: 0, end: text.len() as u64 },
                text: text.to_string(),
                metadata: MetadataMap::default(),
                embedding: None,
            }],
        )
        .await
        .unwrap();
    s.put_embedding(EmbedKey::chunk(cids[0]), embedder.embed_passage(text))
        .await
        .unwrap();
    (did, cids[0])
}

/// Loose calibration suitable for `MockEmbedder`'s hashy similarity scores.
/// The defaults expect transformer-grade cosine, which the mock can't
/// produce — so we lower the gate but keep MAD active.
fn loose_config() -> RankerConfig {
    let mut cfg = RankerConfig::default();
    cfg.semantic.min_similarity = 0.05;
    cfg.semantic.scale = 10.0;
    cfg.merge.confidence_gate = 0.05;
    cfg
}

// ============================================================================
// Recall@K
// ============================================================================

#[tokio::test]
#[ignore]
async fn recall_at_k_finds_each_target_in_topk() {
    let Some((s, w, src)) = setup().await else { return };
    let embedder = MockEmbedder::new(768);

    // 6 thematic chunks; each query verbatim-quotes one of them so cosine
    // for the right chunk is ≈1.0 even under MockEmbedder.
    let pairs: Vec<(&str, &str)> = vec![
        ("auth", "auth flow login session token"),
        ("billing", "billing invoice subscription payment receipt"),
        ("kubernetes", "kubernetes deployment pod replica scaling"),
        ("ml", "machine learning gradient descent neural network"),
        ("recipe", "tomato basil pasta recipe italian"),
        ("infra", "terraform module aws vpc subnet"),
    ];
    let mut chunks = Vec::with_capacity(pairs.len());
    for (i, (slug, text)) in pairs.iter().enumerate() {
        let (_doc, cid) = ingest_one(&s, &embedder, w, src, slug, 0xC0 + i as u8, text).await;
        chunks.push((slug, cid, *text));
    }

    let session = s.create_session(w, Some("recall-test")).await.unwrap();
    let ranker = Ranker::new(&s).with_config(loose_config());

    let top_k = 3;
    let mut hits = 0usize;
    for (slug, expected_cid, query) in &chunks {
        let result = ranker
            .rank(RankRequest {
                workspace: w,
                session,
                query_embedding: embedder.embed_query(query),
                iteration: 0,
            })
            .await;
        let in_topk = result
            .items
            .iter()
            .take(top_k)
            .any(|it| it.target == NodeRef::Chunk(*expected_cid));
        if in_topk {
            hits += 1;
        } else {
            eprintln!(
                "miss for query '{slug}': top-{top_k} = {:?}",
                result.items.iter().take(top_k).map(|i| (&i.target, i.score, &i.reason)).collect::<Vec<_>>()
            );
        }
    }
    // Verbatim-quoted queries should hit every target. We allow one miss to
    // account for hash collisions in MockEmbedder's space — but if more than
    // one query whiffs, something is wrong with the merge.
    assert!(
        hits >= chunks.len() - 1,
        "recall@{top_k} = {hits}/{} — expected ≥ {}",
        chunks.len(),
        chunks.len() - 1
    );
}

// ============================================================================
// Confidence gate
// ============================================================================

#[tokio::test]
#[ignore]
async fn confidence_gate_rejects_unrelated_query() {
    let Some((s, w, src)) = setup().await else { return };
    let embedder = MockEmbedder::new(768);

    // Tightly-themed corpus: nothing about meteorology in here.
    for (i, text) in [
        "kubernetes deployment pod replica scaling",
        "terraform module aws vpc subnet",
        "machine learning gradient descent neural network",
    ]
    .iter()
    .enumerate()
    {
        ingest_one(&s, &embedder, w, src, &format!("c{i}"), 0xD0 + i as u8, text).await;
    }

    let session = s.create_session(w, Some("gate-test")).await.unwrap();

    // Use the *default* config here — we want the gate's calibrated cutoff
    // to do its job. Lowering the gate would defeat the purpose of the test.
    let ranker = Ranker::new(&s);
    let result = ranker
        .rank(RankRequest {
            workspace: w,
            session,
            query_embedding: embedder.embed_query("what is the weather forecast for tomorrow"),
            iteration: 0,
        })
        .await;
    assert!(
        result.items.is_empty(),
        "expected gate to reject unrelated query; got {:?}",
        result.items.iter().map(|i| (&i.target, i.score, &i.reason)).collect::<Vec<_>>()
    );
}

// ============================================================================
// MAD outlier filter
// ============================================================================

#[tokio::test]
#[ignore]
async fn mad_filter_trims_long_tail() {
    let Some((s, w, src)) = setup().await else { return };
    let embedder = MockEmbedder::new(768);

    let target_text = "exactly the kind of unique phrase that hashes well";
    let (_did, target_cid) =
        ingest_one(&s, &embedder, w, src, "target", 0xE0, target_text).await;

    // Insert a long tail of unrelated chunks. With MockEmbedder these all
    // produce low-but-not-zero cosines vs. the query — exactly the regime
    // where the MAD filter should engage.
    for i in 0..20 {
        let text = format!("filler chunk number {i} containing assorted words");
        ingest_one(&s, &embedder, w, src, &format!("filler-{i}"), 0xF0 ^ i as u8, &text).await;
    }

    let session = s.create_session(w, Some("mad-test")).await.unwrap();
    let ranker = Ranker::new(&s).with_config(loose_config());
    let result = ranker
        .rank(RankRequest {
            workspace: w,
            session,
            query_embedding: embedder.embed_query(target_text),
            iteration: 0,
        })
        .await;

    assert!(!result.items.is_empty(), "expected at least the target to survive");
    assert_eq!(
        result.items[0].target,
        NodeRef::Chunk(target_cid),
        "target should rank #1; full result: {:?}",
        result.items.iter().map(|i| (&i.target, i.score)).collect::<Vec<_>>()
    );
    // After MAD trimming, we should have far fewer than the 21 chunks
    // ingested. Exact count varies with MockEmbedder noise; "≤ 7" is a
    // generous upper bound that still flags regressions where MAD silently
    // disengages.
    assert!(
        result.items.len() <= 7,
        "MAD filter let too many through: {} items — {:?}",
        result.items.len(),
        result.items.iter().map(|i| (&i.target, i.score)).collect::<Vec<_>>()
    );
}
