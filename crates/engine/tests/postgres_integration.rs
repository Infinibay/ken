//! Integration tests for `PostgresStorage`.
//!
//! These tests require a running Postgres instance with `pgvector` enabled.
//! They are `#[ignore]`d by default; run with:
//!
//!     DATABASE_URL=postgres://cae:cae@localhost:5432/cae \
//!     cargo test --workspace --all-features --ignored
//!
//! The repository ships a `docker-compose.yml` that starts a compatible
//! Postgres + pgvector image.

#![cfg(feature = "postgres")]

use engine::embed::MockEmbedder;
use engine::postgres::PostgresStorage;
use engine::rank::reactive::{reactive_scores, ReactiveConfig};
use engine::rank::{RankRequest, Ranker};
use engine::storage::{
    ChunkFilter, NewChunk, NewContext, NewDocument, NewEdge, NewEntity, NewInteraction,
    NewSessionScore, NewSource, UpsertOutcome,
};
use engine::types::*;

async fn setup() -> Option<(PostgresStorage, TenantId, WorkspaceId, SourceId)> {
    let url = std::env::var("DATABASE_URL").ok()?;
    let s = PostgresStorage::connect(&url).await.expect("connect");
    s.migrate().await.expect("migrate");

    let t = s
        .create_tenant("integration", PlanTier::Free)
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
    Some((s, t, w, src))
}

async fn versioned_source(s: &PostgresStorage, w: WorkspaceId) -> SourceId {
    s.create_source(NewSource {
        workspace_id: w,
        kind: SourceKind::Manual,
        name: "versioned".into(),
        config_json: serde_json::Value::Null,
        keep_history: true,
        default_acl: Acl::default(),
    })
    .await
    .expect("versioned source")
}

fn doc_draft(w: WorkspaceId, src: SourceId, ext: &str, hash_seed: u8) -> NewDocument {
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

#[tokio::test]
#[ignore]
async fn tenant_workspace_source_roundtrip() {
    let Some((s, t, w, src)) = setup().await else { return };
    assert_eq!(s.get_tenant(t).await.unwrap().plan, PlanTier::Free);
    assert_eq!(s.get_workspace(w).await.unwrap().tenant_id, t);
    assert_eq!(s.get_source(src).await.unwrap().workspace_id, w);
}

#[tokio::test]
#[ignore]
async fn upsert_document_unchanged_then_updated() {
    let Some((s, _, w, src)) = setup().await else { return };
    let first = s.upsert_document(doc_draft(w, src, "doc-A", 0xAA)).await.unwrap();
    let id = first.current_id();
    assert!(matches!(first, UpsertOutcome::Created(_)));

    let second = s.upsert_document(doc_draft(w, src, "doc-A", 0xAA)).await.unwrap();
    assert!(matches!(second, UpsertOutcome::Unchanged(d) if d == id));

    let third = s.upsert_document(doc_draft(w, src, "doc-A", 0xBB)).await.unwrap();
    assert!(matches!(third, UpsertOutcome::Updated(d) if d == id));

    let doc = s.get_document(id).await.unwrap();
    assert_eq!(doc.version, 2);
    assert_eq!(doc.content_hash, [0xBB; 32]);
}

#[tokio::test]
#[ignore]
async fn replace_chunks_and_embeddings() {
    let Some((s, _, w, src)) = setup().await else { return };
    let did = s
        .upsert_document(doc_draft(w, src, "doc-chunks", 0x01))
        .await
        .unwrap()
        .current_id();
    let cids = s
        .replace_chunks(
            did,
            (0..3)
                .map(|i| NewChunk {
                    kind: ChunkKind::Paragraph,
                    position: ChunkPosition::ByteRange { start: i * 5, end: i * 5 + 5 },
                    text: format!("chunk {i}"),
                    metadata: MetadataMap::default(),
                    embedding: None,
                })
                .collect(),
        )
        .await
        .unwrap();
    assert_eq!(cids.len(), 3);

    s.put_embedding(EmbedKey::chunk(cids[0]), vec![1.0; 768])
        .await
        .unwrap();
    let v = s.get_embedding_by_owner(EmbedKey::chunk(cids[0])).await.unwrap();
    assert_eq!(v.len(), 768);
    assert_eq!(v[0], 1.0);

    let listed = s.list_chunk_embeddings(w, true).await;
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].0, cids[0]);
}

#[tokio::test]
#[ignore]
async fn add_edge_dedup_keeps_max_weight() {
    let Some((s, _, w, src)) = setup().await else { return };
    let a = s
        .upsert_document(doc_draft(w, src, "edge-A", 0x10))
        .await
        .unwrap()
        .current_id();
    let b = s
        .upsert_document(doc_draft(w, src, "edge-B", 0x20))
        .await
        .unwrap()
        .current_id();
    let e1 = s
        .add_edge(NewEdge {
            workspace_id: w,
            from: NodeRef::Document(a),
            to: NodeRef::Document(b),
            kind: EdgeKind::Cites,
            weight: 0.5,
            metadata: MetadataMap::default(),
            created_by: EdgeOrigin::Adapter,
        })
        .await
        .unwrap();
    let e2 = s
        .add_edge(NewEdge {
            workspace_id: w,
            from: NodeRef::Document(a),
            to: NodeRef::Document(b),
            kind: EdgeKind::Cites,
            weight: 0.9,
            metadata: MetadataMap::default(),
            created_by: EdgeOrigin::Adapter,
        })
        .await
        .unwrap();
    assert_eq!(e1, e2, "dedup should return the same edge id");
    let edge = s.get_edge(e1).await.unwrap();
    assert!((edge.weight - 0.9).abs() < 1e-6);
}

#[tokio::test]
#[ignore]
async fn upsert_entity_merges_aliases() {
    let Some((s, _, w, _)) = setup().await else { return };
    let first = s
        .upsert_entity(NewEntity {
            workspace_id: w,
            kind: EntityKind::Person,
            canonical_name: "Ada Lovelace".into(),
            aliases: vec!["Ada".into()],
            metadata: MetadataMap::default(),
        })
        .await
        .unwrap();
    let again = s
        .upsert_entity(NewEntity {
            workspace_id: w,
            kind: EntityKind::Person,
            canonical_name: "Ada Lovelace".into(),
            aliases: vec!["A. Lovelace".into()],
            metadata: MetadataMap::default(),
        })
        .await
        .unwrap();
    assert_eq!(first, again);
    let ent = s.get_entity(first).await.unwrap();
    assert!(ent.aliases.contains(&"Ada".into()));
    assert!(ent.aliases.contains(&"A. Lovelace".into()));
}

#[tokio::test]
#[ignore]
async fn snapshot_session_scores_roundtrip() {
    let Some((s, _, w, src)) = setup().await else { return };
    let sid = s.create_session(w, Some("agent-int")).await.unwrap();
    // D5: live sessions default to kind=Real.
    assert_eq!(s.get_session(sid).await.unwrap().kind, SessionKind::Real);
    let did = s
        .upsert_document(doc_draft(w, src, "score-target", 0x42))
        .await
        .unwrap()
        .current_id();

    let cid = s
        .append_context(NewContext {
            session_id: sid,
            kind: ContextKind::UserInput,
            content: "find me".into(),
            iteration: 0,
        })
        .await
        .unwrap();
    s.put_embedding(EmbedKey::context(cid), vec![0.5; 768])
        .await
        .unwrap();
    assert!(s.get_context(cid).await.unwrap().embedding_id.is_some());

    s.snapshot_session_scores(
        sid,
        vec![NewSessionScore {
            target: NodeRef::Document(did),
            score: 1.5,
            access_count: 3,
            productivity: 0.8,
            pattern: Pattern::ReadEdit,
            was_edited: true,
        }],
    )
    .await
    .unwrap();

    let got = s
        .session_score(sid, &NodeRef::Document(did))
        .await
        .unwrap();
    assert!((got.score - 1.5).abs() < 1e-6);
    assert_eq!(got.access_count, 3);
    assert_eq!(got.pattern, Pattern::ReadEdit);
    assert!(got.was_edited);

    let recent = s.list_recent_context_embeddings(w, 0, None).await;
    assert!(recent.iter().any(|(c, v)| c.id == cid && v.len() == 768));
}

#[tokio::test]
#[ignore]
async fn upsert_document_versioned_when_keep_history() {
    let Some((s, _, w, _)) = setup().await else { return };
    let src = versioned_source(&s, w).await;
    let r1 = s.upsert_document(doc_draft(w, src, "history", 0xC0)).await.unwrap();
    let r2 = s.upsert_document(doc_draft(w, src, "history", 0xC1)).await.unwrap();
    let UpsertOutcome::Versioned { new, replaced } = r2 else {
        panic!("expected Versioned, got {r2:?}");
    };
    assert_eq!(replaced, r1.current_id());
    let old = s.get_document(replaced).await.unwrap();
    assert!(!old.current);
    assert_eq!(old.replaced_by, Some(new));
    assert_eq!(old.external_id.as_deref(), Some("history"));
    let new_doc = s.get_document(new).await.unwrap();
    assert!(new_doc.current);
    assert_eq!(new_doc.version, 2);
}

#[tokio::test]
#[ignore]
async fn delete_document_cascades_chunks_embeddings_edges() {
    let Some((s, _, w, src)) = setup().await else { return };
    let did = s
        .upsert_document(doc_draft(w, src, "cascade", 0xD0))
        .await
        .unwrap()
        .current_id();
    let cid = s
        .replace_chunks(
            did,
            vec![NewChunk {
                kind: ChunkKind::Paragraph,
                position: ChunkPosition::ByteRange { start: 0, end: 5 },
                text: "hi".into(),
                metadata: MetadataMap::default(),
                embedding: None,
            }],
        )
        .await
        .unwrap()[0];
    s.put_embedding(EmbedKey::chunk(cid), vec![1.0; 768])
        .await
        .unwrap();
    s.add_edge(NewEdge {
        workspace_id: w,
        from: NodeRef::Document(did),
        to: NodeRef::External("https://example.com".into()),
        kind: EdgeKind::Cites,
        weight: 1.0,
        metadata: MetadataMap::default(),
        created_by: EdgeOrigin::Adapter,
    })
    .await
    .unwrap();

    s.delete_document(did).await.unwrap();
    assert!(s.get_document(did).await.is_none());
    assert!(s.get_chunk(cid).await.is_none());
    assert!(s.get_embedding_by_owner(EmbedKey::chunk(cid)).await.is_none());
    assert!(s.edges_from(&NodeRef::Document(did), None).await.is_empty());
}

#[tokio::test]
#[ignore]
async fn chunks_in_workspace_filter_kinds_and_tags() {
    let Some((s, _, w, src)) = setup().await else { return };
    let did = s
        .upsert_document(doc_draft(w, src, "filter-doc", 0xF1))
        .await
        .unwrap()
        .current_id();
    s.replace_chunks(
        did,
        vec![
            NewChunk {
                kind: ChunkKind::Paragraph,
                position: ChunkPosition::ByteRange { start: 0, end: 5 },
                text: "p".into(),
                metadata: MetadataMap {
                    tags: vec!["urgent".into()],
                    ..Default::default()
                },
                embedding: None,
            },
            NewChunk {
                kind: ChunkKind::Heading,
                position: ChunkPosition::ByteRange { start: 5, end: 10 },
                text: "h".into(),
                metadata: MetadataMap::default(),
                embedding: None,
            },
        ],
    )
    .await
    .unwrap();

    let only_para = s
        .chunks_in_workspace(
            w,
            &ChunkFilter {
                kinds: Some(vec![ChunkKind::Paragraph]),
                ..Default::default()
            },
        )
        .await;
    assert_eq!(only_para.len(), 1);

    let by_tag = s
        .chunks_in_workspace(
            w,
            &ChunkFilter {
                tags: Some(vec!["urgent".into()]),
                ..Default::default()
            },
        )
        .await;
    assert_eq!(by_tag.len(), 1);
}

#[tokio::test]
#[ignore]
async fn predictive_context_sweep_excludes_session() {
    let Some((s, _, w, _)) = setup().await else { return };
    let s1 = s.create_session(w, None).await.unwrap();
    let s2 = s.create_session(w, None).await.unwrap();
    let c1 = s
        .append_context(NewContext {
            session_id: s1,
            kind: ContextKind::UserInput,
            content: "first".into(),
            iteration: 0,
        })
        .await
        .unwrap();
    let c2 = s
        .append_context(NewContext {
            session_id: s2,
            kind: ContextKind::UserInput,
            content: "second".into(),
            iteration: 0,
        })
        .await
        .unwrap();
    s.put_embedding(EmbedKey::context(c1), vec![1.0; 768]).await.unwrap();
    s.put_embedding(EmbedKey::context(c2), vec![2.0; 768]).await.unwrap();

    let hits: Vec<ContextId> = s
        .list_recent_context_embeddings(w, 0, Some(s1))
        .await
        .into_iter()
        .map(|(ctx, _)| ctx.id)
        .collect();
    assert_eq!(hits, vec![c2]);
}

#[tokio::test]
#[ignore]
async fn reactive_channel_ranks_cited_above_dismissed() {
    let Some((s, _, w, src)) = setup().await else { return };
    let sid = s.create_session(w, Some("agent-int")).await.unwrap();
    let cited = s
        .upsert_document(doc_draft(w, src, "cited-doc", 0xA1))
        .await
        .unwrap()
        .current_id();
    let read = s
        .upsert_document(doc_draft(w, src, "read-doc", 0xA2))
        .await
        .unwrap()
        .current_id();
    let dismissed = s
        .upsert_document(doc_draft(w, src, "dismissed-doc", 0xA3))
        .await
        .unwrap()
        .current_id();

    for (target, kind) in [
        (cited, EventType::Read),
        (cited, EventType::Cited),
        (read, EventType::Read),
        (dismissed, EventType::Read),
        (dismissed, EventType::Dismissed),
    ] {
        s.append_interaction(NewInteraction {
            session_id: sid,
            context_id: None,
            iteration: 0,
            event_type: kind,
            target: NodeRef::Document(target),
            weight: 1.0,
            tool_name: Some("test.tool".into()),
        })
        .await
        .unwrap();
    }

    let hits = reactive_scores(&s, sid, 0, &ReactiveConfig::default()).await;
    let by = |id: DocumentId| {
        hits.iter()
            .find(|h| h.target == NodeRef::Document(id))
            .map(|h| h.score)
    };

    let cited_score = by(cited).expect("cited should appear");
    let read_score = by(read).expect("read-only should appear");
    assert!(by(dismissed).is_none(), "dismissed should be filtered out");
    assert!(
        cited_score > read_score,
        "cited ({cited_score}) should outrank read-only ({read_score})"
    );
}

#[tokio::test]
#[ignore]
async fn ranker_end_to_end_finds_semantic_match() {
    use engine::embed::Embedder;
    let Some((s, _, w, src)) = setup().await else { return };
    let embedder = MockEmbedder::new(768);

    // Seed: ingest two documents with chunks. Embed query-similar text into
    // one of them; query-unrelated text into the other.
    let target_doc = s
        .upsert_document(doc_draft(w, src, "ranker-target", 0xE1))
        .await
        .unwrap()
        .current_id();
    let target_chunks = s
        .replace_chunks(
            target_doc,
            vec![NewChunk {
                kind: ChunkKind::Paragraph,
                position: ChunkPosition::ByteRange { start: 0, end: 32 },
                text: "auth flow login session token".into(),
                metadata: MetadataMap::default(),
                embedding: None,
            }],
        )
        .await
        .unwrap();
    let unrelated_doc = s
        .upsert_document(doc_draft(w, src, "ranker-unrelated", 0xE2))
        .await
        .unwrap()
        .current_id();
    let unrelated_chunks = s
        .replace_chunks(
            unrelated_doc,
            vec![NewChunk {
                kind: ChunkKind::Paragraph,
                position: ChunkPosition::ByteRange { start: 0, end: 32 },
                text: "cooking recipe pasta tomato".into(),
                metadata: MetadataMap::default(),
                embedding: None,
            }],
        )
        .await
        .unwrap();

    s.put_embedding(
        EmbedKey::chunk(target_chunks[0]),
        embedder.embed_passage("auth flow login session token"),
    )
    .await
    .unwrap();
    s.put_embedding(
        EmbedKey::chunk(unrelated_chunks[0]),
        embedder.embed_passage("cooking recipe pasta tomato"),
    )
    .await
    .unwrap();

    let session = s.create_session(w, Some("ranker-test")).await.unwrap();

    let mut config = engine::rank::RankerConfig::default();
    // The mock embedder is hashy and noisy; loosen thresholds so the test
    // verifies the *plumbing* (channels reach the merge) rather than fighting
    // calibration of a fake embedder.
    config.semantic.min_similarity = 0.05;
    config.semantic.scale = 10.0;
    config.merge.confidence_gate = 0.05;

    let ranker = Ranker::new(&s).with_config(config);
    let result = ranker
        .rank(RankRequest {
            workspace: w,
            session,
            query_embedding: embedder.embed_query("auth flow login session token"),
            iteration: 0,
        })
        .await;

    assert!(!result.items.is_empty(), "ranker returned empty list");
    let top = &result.items[0];
    assert_eq!(
        top.target,
        NodeRef::Chunk(target_chunks[0]),
        "expected the auth chunk to win, got {:?} reasons={:?}",
        top.target,
        result.items.iter().map(|i| (&i.target, i.score, &i.reason)).collect::<Vec<_>>()
    );
}

#[tokio::test]
#[ignore]
async fn reactive_channel_decays_old_iterations() {
    let Some((s, _, w, src)) = setup().await else { return };
    let sid = s.create_session(w, Some("agent-decay")).await.unwrap();
    let target = s
        .upsert_document(doc_draft(w, src, "decay-doc", 0xB0))
        .await
        .unwrap()
        .current_id();

    // Same event at iter 0 vs iter 10 should produce a smaller score when
    // the current iteration is well past the event.
    s.append_interaction(NewInteraction {
        session_id: sid,
        context_id: None,
        iteration: 0,
        event_type: EventType::Read,
        target: NodeRef::Document(target),
        weight: 1.0,
        tool_name: None,
    })
    .await
    .unwrap();

    let early = reactive_scores(&s, sid, 0, &ReactiveConfig::default()).await;
    let later = reactive_scores(&s, sid, 10, &ReactiveConfig::default()).await;

    let early_score = early.iter().find(|h| h.target == NodeRef::Document(target)).unwrap().score;
    let later_score = later.iter().find(|h| h.target == NodeRef::Document(target)).unwrap().score;
    assert!(later_score < early_score, "decay should reduce score over iterations");
    assert!(later_score > 0.0);
}
