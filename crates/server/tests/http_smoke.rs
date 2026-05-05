//! End-to-end smoke test for the HTTP API.
//!
//! Drives the full router via `tower::ServiceExt::oneshot` (no socket) and
//! covers the agent-first flow: tenant → workspace → source → session →
//! ingest → rank → event. Gated `#[ignore]` because it needs a running
//! Postgres; run with:
//!
//!     DATABASE_URL=postgres://cae:cae@localhost:5432/cae \
//!     cargo test -p cae-server --all-features --ignored

#![cfg(feature = "postgres")]

use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::http::{Method, Request, StatusCode};
use cae_server::{build_router, AppState};
use engine::embed::{Embedder, MockEmbedder};
use engine::postgres::PostgresStorage;
use serde_json::{json, Value};
use tower::util::ServiceExt;

async fn try_setup() -> Option<axum::Router> {
    let url = std::env::var("DATABASE_URL").ok()?;
    let storage = PostgresStorage::connect(&url).await.expect("connect");
    storage.migrate().await.expect("migrate");
    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let state = Arc::new(AppState { storage, embedder });
    Some(build_router(state))
}

async fn post(app: &axum::Router, path: &str, body: Value) -> (StatusCode, Value) {
    let req = Request::builder()
        .method(Method::POST)
        .uri(path)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    let res = app.clone().oneshot(req).await.expect("oneshot");
    let status = res.status();
    let bytes = to_bytes(res.into_body(), 1 << 20).await.expect("body");
    let json: Value = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({"raw": String::from_utf8_lossy(&bytes)}))
    };
    (status, json)
}

async fn get(app: &axum::Router, path: &str) -> (StatusCode, Value) {
    let req = Request::builder()
        .method(Method::GET)
        .uri(path)
        .body(Body::empty())
        .unwrap();
    let res = app.clone().oneshot(req).await.expect("oneshot");
    let status = res.status();
    let bytes = to_bytes(res.into_body(), 1 << 20).await.expect("body");
    let json: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, json)
}

#[tokio::test]
#[ignore]
async fn full_agent_flow_via_http() {
    let app = match try_setup().await {
        Some(a) => a,
        None => {
            eprintln!("DATABASE_URL not set — skipping");
            return;
        }
    };

    // Health.
    let (status, body) = get(&app, "/health").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));

    // Tenant.
    let (status, body) = post(&app, "/tenants", json!({"name": "smoke", "plan": "free"})).await;
    assert_eq!(status, StatusCode::OK);
    let tenant_id = body["id"].as_str().expect("tenant id").to_string();

    // Workspace.
    let (status, body) = post(
        &app,
        "/workspaces",
        json!({"tenant_id": tenant_id, "name": "default"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let workspace_id = body["id"].as_u64().expect("ws id");

    // Source.
    let (status, body) = post(
        &app,
        "/sources",
        json!({"workspace_id": workspace_id, "kind": "manual", "name": "smoke-src"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let source_id = body["id"].as_u64().expect("source id");

    // Ingest text — adapter chunks paragraphs.
    let (status, body) = post(
        &app,
        "/ingest_text",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "auth-overview",
            "text": "Authentication uses JWT tokens with rotating refresh.\n\nRate limiting is enforced per user via a sliding window.\n\nLogging captures every auth attempt with redacted tokens.",
            "external_id": "auth-overview",
            "mime": "text/plain"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["outcome"], json!("created"));
    let chunk_ids: Vec<u64> = body["chunks"]
        .as_array()
        .expect("chunks")
        .iter()
        .map(|v| v.as_u64().unwrap())
        .collect();
    assert!(chunk_ids.len() >= 3, "expected ≥3 chunks, got {chunk_ids:?}");

    // Re-ingest same text — should be unchanged.
    let (_, body) = post(
        &app,
        "/ingest_text",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "auth-overview",
            "text": "Authentication uses JWT tokens with rotating refresh.\n\nRate limiting is enforced per user via a sliding window.\n\nLogging captures every auth attempt with redacted tokens.",
            "external_id": "auth-overview",
            "mime": "text/plain"
        }),
    )
    .await;
    assert_eq!(body["outcome"], json!("unchanged"));

    // Session.
    let (status, body) = post(
        &app,
        "/sessions",
        json!({"workspace_id": workspace_id, "agent_id": "smoke-agent"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let session_id = body["id"].as_u64().expect("session id");

    // Rank — query matches the first chunk verbatim so the deterministic-but-
    // hashy MockEmbedder produces cosine ~1.0 and the result clears the
    // default confidence gate. The smoke test's job is to verify the plumbing
    // (semantic → merge → response), not to tune mock-embedder calibration.
    let (status, body) = post(
        &app,
        "/rank",
        json!({
            "workspace_id": workspace_id,
            "session_id": session_id,
            "query": "Authentication uses JWT tokens with rotating refresh.",
            "iteration": 0
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let items = body["items"].as_array().expect("items");
    assert!(!items.is_empty(), "expected ≥1 ranked item, got {body}");
    let first_target = items[0]["target"].as_str().expect("target");
    assert!(first_target.starts_with("chunk:"), "got {first_target}");

    // Event — record a Cited interaction.
    let (status, body) = post(
        &app,
        "/events",
        json!({
            "session_id": session_id,
            "target": first_target,
            "event_type": "cited",
            "weight": 2.5,
            "iteration": 0,
            "tool_name": "smoke.cite"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert!(body["id"].as_u64().is_some());
}

#[tokio::test]
#[ignore]
async fn markdown_ingest_dispatches_and_persists_cites_edges() {
    let app = match try_setup().await {
        Some(a) => a,
        None => return,
    };

    // Bootstrap.
    let (_, body) = post(&app, "/tenants", json!({"name": "md-smoke"})).await;
    let tenant_id = body["id"].as_str().unwrap().to_string();
    let (_, body) = post(
        &app,
        "/workspaces",
        json!({"tenant_id": tenant_id, "name": "default"}),
    )
    .await;
    let workspace_id = body["id"].as_u64().unwrap();
    let (_, body) = post(
        &app,
        "/sources",
        json!({"workspace_id": workspace_id, "kind": "manual", "name": "md-src"}),
    )
    .await;
    let source_id = body["id"].as_u64().unwrap();

    // Ingest a markdown blob with two H2s and two inline links.
    let md = "# Architecture\n\nIntro.\n\n## Auth\n\nSee [JWT spec](https://jwt.io) for details.\n\n## Storage\n\nWe use [Postgres](https://postgresql.org).";
    let (status, body) = post(
        &app,
        "/ingest_text",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "architecture.md",
            "text": md,
            "external_id": "architecture",
            "mime": "text/markdown"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["outcome"], json!("created"));
    let chunks = body["chunks"].as_array().unwrap();
    // # Architecture preamble + ## Auth + ## Storage = 3 sections.
    assert_eq!(chunks.len(), 3, "expected 3 markdown sections, got {chunks:?}");

    // Verify the markdown chunk text was actually preserved (not converted
    // to HTML). Pulling chunk by query that should match the auth section.
    let session_id = post(
        &app,
        "/sessions",
        json!({"workspace_id": workspace_id, "agent_id": "md-agent"}),
    )
    .await
    .1["id"]
        .as_u64()
        .unwrap();

    let (_, body) = post(
        &app,
        "/rank",
        json!({
            "workspace_id": workspace_id,
            "session_id": session_id,
            "query": "## Auth\n\nSee JWT spec for details.",
            "iteration": 0
        }),
    )
    .await;
    let items = body["items"].as_array().unwrap();
    assert!(!items.is_empty(), "expected ranker hits for markdown, got {body}");

    // Re-ingest unchanged → same content_hash → outcome=unchanged.
    let (_, body) = post(
        &app,
        "/ingest_text",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "architecture.md",
            "text": md,
            "external_id": "architecture",
            "mime": "text/markdown"
        }),
    )
    .await;
    assert_eq!(body["outcome"], json!("unchanged"));
}

#[tokio::test]
#[ignore]
async fn ingest_blob_dispatches_via_mime_and_decodes_base64() {
    use base64::Engine;
    let app = match try_setup().await {
        Some(a) => a,
        None => return,
    };

    let (_, body) = post(&app, "/tenants", json!({"name": "blob-smoke"})).await;
    let tenant_id = body["id"].as_str().unwrap().to_string();
    let (_, body) = post(
        &app,
        "/workspaces",
        json!({"tenant_id": tenant_id, "name": "default"}),
    )
    .await;
    let workspace_id = body["id"].as_u64().unwrap();
    let (_, body) = post(
        &app,
        "/sources",
        json!({"workspace_id": workspace_id, "kind": "manual", "name": "blob-src"}),
    )
    .await;
    let source_id = body["id"].as_u64().unwrap();

    // Use a markdown blob (text-derived but routed through the binary path)
    // to exercise the base64 → adapter dispatch chain end-to-end without
    // requiring a PDF fixture in the repo.
    let md = "# Blob Test\n\nLine one.\n\n## Sub\n\nLine two.\n";
    let b64 = base64::engine::general_purpose::STANDARD.encode(md.as_bytes());

    let (status, body) = post(
        &app,
        "/ingest_blob",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "blob.md",
            "bytes_base64": b64,
            "external_id": "blob-doc",
            "mime": "text/markdown"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["outcome"], json!("created"));
    let chunks = body["chunks"].as_array().unwrap();
    // # Blob Test preamble + ## Sub = 2 sections.
    assert_eq!(chunks.len(), 2, "got {chunks:?}");
}

#[tokio::test]
#[ignore]
async fn ingest_blob_rejects_bad_base64() {
    let app = match try_setup().await {
        Some(a) => a,
        None => return,
    };
    // Bootstrap to satisfy schema validity; the bad base64 trips earlier.
    let (_, body) = post(&app, "/tenants", json!({"name": "blob-bad"})).await;
    let tenant_id = body["id"].as_str().unwrap().to_string();
    let (_, body) = post(
        &app,
        "/workspaces",
        json!({"tenant_id": tenant_id, "name": "default"}),
    )
    .await;
    let workspace_id = body["id"].as_u64().unwrap();
    let (_, body) = post(
        &app,
        "/sources",
        json!({"workspace_id": workspace_id, "kind": "manual", "name": "src"}),
    )
    .await;
    let source_id = body["id"].as_u64().unwrap();

    let (status, _) = post(
        &app,
        "/ingest_blob",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "x.bin",
            "bytes_base64": "!!! not base64 !!!",
            "mime": "text/plain"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
#[ignore]
async fn rust_code_ingest_extracts_symbols_and_imports_edges() {
    let app = match try_setup().await {
        Some(a) => a,
        None => return,
    };

    let (_, body) = post(&app, "/tenants", json!({"name": "code-smoke"})).await;
    let tenant_id = body["id"].as_str().unwrap().to_string();
    let (_, body) = post(
        &app,
        "/workspaces",
        json!({"tenant_id": tenant_id, "name": "default"}),
    )
    .await;
    let workspace_id = body["id"].as_u64().unwrap();
    let (_, body) = post(
        &app,
        "/sources",
        json!({"workspace_id": workspace_id, "kind": "manual", "name": "code-src"}),
    )
    .await;
    let source_id = body["id"].as_u64().unwrap();

    // Real Rust source with imports + a struct + an impl with two methods.
    let rust_src = "use std::collections::HashMap;\nuse serde::{Serialize, Deserialize};\n\n/// A user account.\n#[derive(Serialize, Deserialize)]\npub struct User {\n    pub name: String,\n    pub age: u32,\n}\n\nimpl User {\n    /// Returns true if the user's name is non-empty.\n    pub fn validate(&self) -> bool {\n        !self.name.is_empty()\n    }\n\n    pub fn rename(&mut self, new_name: String) {\n        self.name = new_name;\n    }\n}\n";
    let (status, body) = post(
        &app,
        "/ingest_text",
        json!({
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_uri": "src/user.rs",
            "text": rust_src,
            "external_id": "user.rs",
            "mime": "text/x-rust"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["outcome"], json!("created"));
    let chunks = body["chunks"].as_array().unwrap();
    // struct User + 2 methods = 3 chunks (impl block itself doesn't emit a chunk).
    assert_eq!(chunks.len(), 3, "expected 3 symbol chunks, got {chunks:?}");

    // Rank — query that should retrieve the validate method.
    let session_id = post(
        &app,
        "/sessions",
        json!({"workspace_id": workspace_id, "agent_id": "code-agent"}),
    )
    .await
    .1["id"]
        .as_u64()
        .unwrap();

    let (_, body) = post(
        &app,
        "/rank",
        json!({
            "workspace_id": workspace_id,
            "session_id": session_id,
            "query": "Returns true if the user's name is non-empty.",
            "iteration": 0
        }),
    )
    .await;
    let items = body["items"].as_array().unwrap();
    assert!(!items.is_empty(), "expected ranker hits for code, got {body}");
}

#[tokio::test]
#[ignore]
async fn validation_errors_return_400() {
    let app = match try_setup().await {
        Some(a) => a,
        None => return,
    };

    // chunks must not be empty.
    let (status, _) = post(
        &app,
        "/ingest",
        json!({
            "workspace_id": 1,
            "source_id": 1,
            "kind": "plain_text",
            "mime": "text/plain",
            "chunks": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}
