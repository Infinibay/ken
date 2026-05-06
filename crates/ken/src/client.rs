//! Synchronous HTTP client for the ken HTTP server. Used by hooks (where
//! sub-100ms latency matters) and the MCP server (where stdio dispatch
//! is single-threaded anyway). Async would only buy us concurrency we
//! don't need here.

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use std::time::Duration;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(15);

pub struct EngineClient {
    base: String,
    agent: ureq::Agent,
}

impl EngineClient {
    pub fn new(base: impl Into<String>) -> Self {
        let agent = ureq::AgentBuilder::new()
            .timeout(DEFAULT_TIMEOUT)
            .build();
        Self { base: base.into(), agent }
    }

    /// Find-or-create a workspace by name (under tenant `"local"` by
    /// default). Returns the workspace id. Used by `ken install` so the
    /// user can pass `--workspace my-project` instead of memorizing
    /// numeric ids.
    pub fn resolve_workspace(&self, name: &str) -> Result<u64> {
        let body = json!({ "name": name });
        let resp: ResolveWorkspaceResponse = self
            .agent
            .post(&format!("{}/workspaces/resolve", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /workspaces/resolve: {e}"))?
            .into_json()
            .context("decode /workspaces/resolve response")?;
        Ok(resp.id)
    }

    /// Create a session and return its id. Idempotent at the caller's
    /// discretion — the engine creates a fresh session every call.
    pub fn create_session(&self, workspace_id: u64, agent_id: &str) -> Result<u64> {
        let body = json!({
            "workspace_id": workspace_id,
            "agent_id": agent_id,
        });
        let resp: SessionResponse = self
            .agent
            .post(&format!("{}/sessions", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /sessions: {e}"))?
            .into_json()
            .context("decode /sessions response")?;
        Ok(resp.id)
    }

    /// Mark a session as ended. The engine fires `infer_coaccessed_edges`
    /// internally on close — best-effort, but worth waiting for the call
    /// to complete so the next session sees the new edges.
    pub fn end_session(&self, session_id: u64) -> Result<()> {
        let body = json!({ "session_id": session_id });
        self.agent
            .post(&format!("{}/sessions/end", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /sessions/end: {e}"))?;
        Ok(())
    }

    /// Tell the engine to emit per-turn anchor edges (`PromptAnchored` /
    /// `ReplyAnchored`). The `Stop` hook calls this after appending the
    /// assistant reply so the turn's tool interactions get linked to both
    /// dialog endpoints. Server-side it's a single batched insert.
    pub fn anchor_turn(&self, session_id: u64, iteration: u32) -> Result<()> {
        let body = json!({
            "session_id": session_id,
            "iteration": iteration,
        });
        self.agent
            .post(&format!("{}/sessions/anchor_turn", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /sessions/anchor_turn: {e}"))?;
        Ok(())
    }

    /// Append a `SessionContext` (UserInput / AssistantReply / …) and
    /// optionally embed it. Used by the `UserPromptSubmit` and `Stop` hooks
    /// to persist the outer dialog so the predictive ranker can compare
    /// future queries against past intent + answers.
    pub fn append_context(
        &self,
        session_id: u64,
        kind: &str,
        content: &str,
        iteration: u32,
        embed: bool,
    ) -> Result<u64> {
        let body = json!({
            "session_id": session_id,
            "kind": kind,
            "content": content,
            "iteration": iteration,
            "embed": embed,
        });
        let resp: ContextResponse = self
            .agent
            .post(&format!("{}/contexts", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /contexts: {e}"))?
            .into_json()
            .context("decode /contexts response")?;
        Ok(resp.id)
    }

    /// Record an interaction event. `target` is `doc:<id>`, `chunk:<id>`,
    /// `ent:<id>`, or `ext:<uri>` (`NodeRef` Display format).
    pub fn record_event(
        &self,
        session_id: u64,
        target: &str,
        event_type: &str,
        weight: f32,
        iteration: u32,
        tool_name: Option<&str>,
    ) -> Result<u64> {
        let body = json!({
            "session_id": session_id,
            "target": target,
            "event_type": event_type,
            "weight": weight,
            "iteration": iteration,
            "tool_name": tool_name,
        });
        let resp: EventResponse = self
            .agent
            .post(&format!("{}/events", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /events: {e}"))?
            .into_json()
            .context("decode /events response")?;
        Ok(resp.id)
    }

    /// Run a rank query with a pre-built body. The MCP path uses this
    /// because it needs `include_text` + `limit` flags that the simpler
    /// helper below doesn't expose.
    pub fn rank_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/rank", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /rank: {e}"))?
            .into_json()
            .context("decode /rank response")?;
        Ok(resp)
    }

    /// Substring-match symbols by qualified_name. Same response shape as
    /// `/rank` (items with citation/qualified_name/kind), but ranked by
    /// name closeness rather than embedding similarity.
    pub fn search_symbols_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/symbols", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /symbols: {e}"))?
            .into_json()
            .context("decode /symbols response")?;
        Ok(resp)
    }

    /// Rank file paths (not chunks) by aggregating chunk-level scores
    /// per path. Cheap stand-in for `Glob`-style file orientation.
    pub fn rank_files_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/files", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /files: {e}"))?
            .into_json()
            .context("decode /files response")?;
        Ok(resp)
    }

    /// Commits (from the git-history ingest) that touched a path or symbol.
    pub fn git_history_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/git_history", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /git_history: {e}"))?
            .into_json()
            .context("decode /git_history response")?;
        Ok(resp)
    }

    /// All symbols declared in a file (cheap structural overview; no
    /// embedder traffic).
    pub fn symbols_in_file_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/symbols_in_file", self.base))
            .send_json(body)
            .map_err(|e| anyhow!("POST /symbols_in_file: {e}"))?
            .into_json()
            .context("decode /symbols_in_file response")?;
        Ok(resp)
    }

    /// Walk a codebase under `root` (path on the server) and ingest every
    /// file an adapter accepts. Server-side does the heavy work — CLI
    /// blocks until done. Long-running on big repos; we lift the per-call
    /// timeout to 30 minutes.
    pub fn ingest_codebase_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/ingest_codebase", self.base))
            .timeout(Duration::from_secs(30 * 60))
            .send_json(body)
            .map_err(|e| anyhow!("POST /ingest_codebase: {e}"))?
            .into_json()
            .context("decode /ingest_codebase response")?;
        Ok(resp)
    }

    /// Walk a repo's git history and ingest commits. Same long-running
    /// shape as `ingest_codebase_raw` — bumped timeout, server does the
    /// work.
    pub fn ingest_git_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/ingest_git", self.base))
            .timeout(Duration::from_secs(30 * 60))
            .send_json(body)
            .map_err(|e| anyhow!("POST /ingest_git: {e}"))?
            .into_json()
            .context("decode /ingest_git response")?;
        Ok(resp)
    }

    /// Index a single file (base64 bytes) into the workspace's KG. Used by
    /// the agent-facing `ingest_file` MCP tool.
    pub fn ingest_file_raw(&self, body: Value) -> Result<Value> {
        // 60s — embedding can be slow on first run when fastembed has to
        // download model weights.
        let resp: Value = self
            .agent
            .post(&format!("{}/ingest_file", self.base))
            .timeout(Duration::from_secs(60))
            .send_json(body)
            .map_err(|e| anyhow!("POST /ingest_file: {e}"))?
            .into_json()
            .context("decode /ingest_file response")?;
        Ok(resp)
    }

    /// Fetch + index a URL (single page or shallow crawl). The server caps
    /// depth ≤ 2, max_pages ≤ 10, wall ≤ 30s; we mirror the wall here as
    /// the request timeout (+5s slack for the response).
    pub fn ingest_url_raw(&self, body: Value) -> Result<Value> {
        let resp: Value = self
            .agent
            .post(&format!("{}/ingest_url", self.base))
            .timeout(Duration::from_secs(35))
            .send_json(body)
            .map_err(|e| anyhow!("POST /ingest_url: {e}"))?
            .into_json()
            .context("decode /ingest_url response")?;
        Ok(resp)
    }
}

#[derive(Deserialize)]
struct SessionResponse {
    id: u64,
}

#[derive(Deserialize)]
struct ResolveWorkspaceResponse {
    id: u64,
}

#[derive(Deserialize)]
struct ContextResponse {
    id: u64,
}

#[derive(Deserialize)]
struct EventResponse {
    id: u64,
}
