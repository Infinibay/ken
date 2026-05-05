//! End-to-end ingest wall-clock measurement. Drives a 50-chunk document
//! through `replace_chunks` with embeddings inline + adapter-style edges,
//! then asserts the entire write path runs under a budget.
//!
//! Numbers from this test are wall-clock (Postgres on localhost), so they
//! reflect actual round-trip and parse cost — not raw SQL throughput. The
//! point is to surface regressions in the ingest write path (extra round-
//! trips, dropped batching, query plan flips) at PR time.
//!
//! Run with:
//!     DATABASE_URL=postgres://cae:cae_dev@localhost:5432/context_engine \
//!     cargo test -p cae-engine --features postgres --test ingest_perf \
//!         -- --ignored --nocapture

#![cfg(feature = "postgres")]

use std::time::Instant;

use engine::embed::{Embedder, MockEmbedder};
use engine::postgres::PostgresStorage;
use engine::storage::{NewChunk, NewDocument, NewEdge, NewSource};
use engine::types::*;

async fn setup() -> Option<(PostgresStorage, WorkspaceId, SourceId)> {
    let url = std::env::var("DATABASE_URL").ok()?;
    let s = PostgresStorage::connect(&url).await.expect("connect");
    s.migrate().await.expect("migrate");
    let t = s.create_tenant("perf", PlanTier::Free).await.expect("tenant");
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

#[tokio::test]
#[ignore]
async fn ingest_50_chunks_with_inline_embeddings_under_budget() {
    let Some((s, w, src)) = setup().await else { return };
    let embedder = MockEmbedder::new(768);
    const N: usize = 50;

    let doc_t0 = Instant::now();
    let did = s
        .upsert_document(NewDocument {
            workspace_id: w,
            source_id: src,
            external_id: Some("perf-50".into()),
            kind: ContentKind::PlainText,
            mime: "text/plain".into(),
            title: Some("perf-50".into()),
            path_or_url: None,
            content_hash: [0xAA; 32],
            acl: Acl::default(),
            metadata: MetadataMap::default(),
            source_modified_at: None,
        })
        .await
        .unwrap()
        .current_id();
    let doc_dt = doc_t0.elapsed();

    // Build 50 chunks with embeddings already attached → single UNNEST insert.
    let chunks_t0 = Instant::now();
    let chunks: Vec<NewChunk> = (0..N)
        .map(|i| {
            let text = format!("chunk number {i} contains some words for embedding");
            let emb = embedder.embed_passage(&text);
            NewChunk {
                kind: ChunkKind::Paragraph,
                position: ChunkPosition::ByteRange { start: (i * 64) as u64, end: (i * 64 + 60) as u64 },
                text,
                metadata: MetadataMap::default(),
                embedding: Some(emb),
            }
        })
        .collect();
    let cids = s.replace_chunks(did, chunks).await.unwrap();
    assert_eq!(cids.len(), N);
    let chunks_dt = chunks_t0.elapsed();

    // 100 edges: each chunk gets two outbound External (URL) edges.
    let edges_t0 = Instant::now();
    let mut edges: Vec<NewEdge> = Vec::with_capacity(N * 2);
    for (i, cid) in cids.iter().enumerate() {
        edges.push(NewEdge {
            workspace_id: w,
            from: NodeRef::Chunk(*cid),
            to: NodeRef::External(format!("https://example.com/{i}")),
            kind: EdgeKind::References,
            weight: 1.0,
            metadata: MetadataMap::default(),
            created_by: EdgeOrigin::UrlResolver,
        });
        edges.push(NewEdge {
            workspace_id: w,
            from: NodeRef::Chunk(*cid),
            to: NodeRef::External(format!("https://example.com/{i}/extra")),
            kind: EdgeKind::References,
            weight: 1.0,
            metadata: MetadataMap::default(),
            created_by: EdgeOrigin::UrlResolver,
        });
    }
    let _eids = s.add_edges(edges).await.unwrap();
    let edges_dt = edges_t0.elapsed();

    let total = doc_dt + chunks_dt + edges_dt;
    eprintln!(
        "[ingest_perf] doc={doc_dt:?}  chunks(50,inline_emb)={chunks_dt:?}  edges(100)={edges_dt:?}  total={total:?}"
    );

    // Budget: with batching the whole flow should comfortably fit in 250ms
    // against a localhost Postgres. The pre-batching baseline was ~150
    // round-trips + N×UPDATE for embeddings; that ran at 600ms+. Set the
    // budget high enough to avoid CI flakes but low enough to catch a
    // regression (e.g. if someone reverts the UNNEST batching).
    assert!(
        total.as_millis() < 500,
        "ingest of 50 chunks + 100 edges took {total:?}; expected < 500ms"
    );
}

#[tokio::test]
#[ignore]
async fn ingest_idempotent_via_on_conflict() {
    // Runs the same edge batch twice. Second call must complete (no
    // duplicate-key error) and resolve via ON CONFLICT path.
    let Some((s, w, src)) = setup().await else { return };
    let did = s
        .upsert_document(NewDocument {
            workspace_id: w,
            source_id: src,
            external_id: Some("idem".into()),
            kind: ContentKind::PlainText,
            mime: "text/plain".into(),
            title: None,
            path_or_url: None,
            content_hash: [0x77; 32],
            acl: Acl::default(),
            metadata: MetadataMap::default(),
            source_modified_at: None,
        })
        .await
        .unwrap()
        .current_id();
    let edges: Vec<NewEdge> = (0..20)
        .map(|i| NewEdge {
            workspace_id: w,
            from: NodeRef::Document(did),
            to: NodeRef::External(format!("https://example.com/{i}")),
            kind: EdgeKind::References,
            weight: 0.5,
            metadata: MetadataMap::default(),
            created_by: EdgeOrigin::UrlResolver,
        })
        .collect();
    let first = s.add_edges(edges.clone()).await.unwrap();
    assert_eq!(first.len(), 20);
    let second = s.add_edges(edges).await.unwrap();
    assert_eq!(second.len(), 20);
    // Same edge ids both times: ON CONFLICT updated existing rows in place,
    // which RETURNING surfaces as the original ids.
    let mut a = first.clone();
    let mut b = second.clone();
    a.sort();
    b.sort();
    assert_eq!(a, b, "ON CONFLICT path returned different ids");
}
