//! Git history → engine database pipeline. Phase 0 of the design in
//! `docs/11-git-history-plan.md`. Compiled only when the `git` feature is
//! on; the optional `git2` dep is the only third-party code reached here.
//!
//! ## What Phase 0 does (and does not)
//!
//! Each kept commit becomes:
//!   * **Mode A**: a `Document` (`ContentKind::Other("commit")`) whose body
//!     is the full commit message + a per-file change manifest. Idempotent
//!     via `external_id = "git+sha:<sha>"`.
//!   * **Mode B**: a synthetic `Session` (with backdated timestamps) whose
//!     `SessionContext` is the commit message and whose interactions per
//!     file map status → `EventType` per `docs/10-git-history.md`. The
//!     ranker's predictive channel reads these directly.
//!
//! Both modes can run independently or together via [`IngestMode`].
//!
//! Out of scope for Phase 0 (see `docs/11-git-history-plan.md` for the
//! full taxonomy):
//!   * Symbol-level diff resolution (Phase 1).
//!   * Branch-as-session aggregation (Phase 1).
//!   * Revert-aware replay (Phase 2).
//!   * Co-edit edges (Phase 4).
//!
//! ## Idempotency
//!
//! Mode A piggybacks on `upsert_document`'s content-hash check: a commit
//! whose mode-A `Document` is unchanged short-circuits the rest of the
//! per-commit work, including mode-B session creation. This makes resync
//! cheap: walking 200k commits when 199k are already ingested only does N
//! `upsert_document` calls, no embedder traffic, no session writes.

use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::embed::Embedder;
use crate::postgres::PostgresStorage;
use crate::storage::{
    NewDocument, NewEdge, NewSessionScore, NewSource, StorageError, StorageResult,
    SyntheticInteraction, SyntheticSessionWrite,
};
use crate::types::*;

pub mod linkage;
pub mod symbols;
pub mod walker;
pub use walker::{CommitData, CommitWalker, WalkError, WalkStats};

/// What kind of change git reports for a file in a commit.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FileStatus {
    Added,
    Modified,
    Removed,
    Renamed,
}

impl FileStatus {
    /// Map to the `EventType` we'd use in a synthetic session, per the
    /// table in `docs/09-github-source.md` / `docs/10-git-history.md`.
    pub fn event_type(self) -> EventType {
        match self {
            // Adds are "cited" — the commit decided this file should exist.
            FileStatus::Added => EventType::Cited,
            // Modifications are direct edits.
            FileStatus::Modified | FileStatus::Renamed => EventType::Edited,
            // Removals signal the file's role ended.
            FileStatus::Removed => EventType::Dismissed,
        }
    }

    /// Default interaction weight per status. Adds get a small bump because
    /// creating a file is a stronger signal than modifying one — the file
    /// didn't exist until the author chose to create it.
    pub fn default_weight(self) -> f32 {
        match self {
            FileStatus::Added => 1.5,
            FileStatus::Modified | FileStatus::Renamed => 1.0,
            FileStatus::Removed => 1.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileChange {
    pub path: String,
    pub status: FileStatus,
    /// Set only for renames; the previous path. Phase 0 records it but
    /// does not yet rewrite Document `external_id`s — that's a Phase 1
    /// task (`docs/11-git-history-plan.md` §4 Phase 1).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub old_path: Option<String>,
    /// Phase 1.5: per-hunk line ranges in the *post-state* file. Empty
    /// for `Removed` (no post-state) and for files where the diff didn't
    /// expose hunks (binary blobs, etc).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub hunks: Vec<HunkRange>,
    /// Phase 1.5: blob OID of the post-state file content. The walker
    /// uses it as the symbol-cache key (same blob → same symbols, by
    /// definition) so we don't re-parse files that didn't actually
    /// change content across two commits.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub new_blob_oid: Option<String>,
    /// Phase 1.5: qualified names of code symbols this file's hunks
    /// touched, resolved by the walker via tree-sitter on the post-state
    /// blob. Empty when language detection misses, parsing fails, or no
    /// hunk fell inside any symbol. The persistence layer emits one
    /// `ChangesSymbol` edge per entry to
    /// `External("git+symbol:<ws>:<path>:<qualified_name>")`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub symbols: Vec<String>,
}

/// Phase 1.5: a single hunk's line range in the post-state file.
/// 1-indexed; `new_lines == 0` means a pure deletion at this offset
/// (we still record it because tree-sitter can locate the symbol that
/// surrounded the deleted lines via the surrounding code's structure).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct HunkRange {
    pub new_start: u32,
    pub new_lines: u32,
}

/// Which side(s) of the dual representation to populate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IngestMode {
    /// Documents only — commits are searchable but no synthetic sessions.
    DocumentsOnly,
    /// Synthetic sessions only — predictive channel benefits, but
    /// commits don't appear in keyword/semantic search of mode-A docs.
    SessionsOnly,
    /// Both Documents and synthetic sessions — the default and what the
    /// design doc recommends.
    #[default]
    Both,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestGitConfig {
    pub repo_path: PathBuf,
    pub workspace_id: WorkspaceId,
    pub source_id: SourceId,
    /// Branch to walk. `None` = walk the resolved repo HEAD (typical for
    /// `main`/`master`/`trunk`).
    pub branch: Option<String>,
    /// Cutoff timestamp in unix seconds. Commits older than this are not
    /// walked. `None` = no cutoff (walk full history).
    pub since_seconds_unix: Option<u64>,
    pub skip_merges: bool,
    pub skip_whitespace_only: bool,
    /// Hard cap on commits processed. 0 = unlimited.
    pub max_commits: u64,
    pub mode: IngestMode,
    /// Phase 1.4: when true, merge commits act as session anchors. The
    /// walker enumerates each merge's branch (`P1..P2`), aggregates the
    /// branch's file changes, and the persistence layer creates a *single*
    /// synthetic session whose context is the merge's message and whose
    /// interactions cover every file the branch touched. Branch members
    /// still get their own Documents (so they're searchable) but no
    /// individual synthetic session — the merge's session subsumes them.
    ///
    /// When false (Phase 0 behavior), merges are skipped entirely and
    /// every commit is its own session. The default flips to true here
    /// because branch-as-session is the *correct* unit for the predictive
    /// channel; commits are too granular and over-weight files touched in
    /// many small WIP commits inside one logical change.
    pub branch_as_session: bool,
    /// When set and `mode != DocumentsOnly`, every per-commit synthetic
    /// session gets its `productivity` value scaled by this factor for
    /// targets where `was_edited = true`. Phase 0 default is 1.0 (no
    /// scaling) — branch/revert detection in later phases will adjust this
    /// per-commit. See decision D6 in `docs/11-git-history-plan.md`.
    pub productivity_default: f32,
}

impl IngestGitConfig {
    pub fn new(repo_path: impl Into<PathBuf>, workspace_id: WorkspaceId, source_id: SourceId) -> Self {
        Self {
            repo_path: repo_path.into(),
            workspace_id,
            source_id,
            branch: None,
            since_seconds_unix: None,
            // When `branch_as_session` is on, the walker handles merges
            // itself (it doesn't skip them); `skip_merges` only applies
            // when branch aggregation is off.
            skip_merges: false,
            skip_whitespace_only: true,
            max_commits: 0,
            mode: IngestMode::Both,
            branch_as_session: true,
            productivity_default: 1.0,
        }
    }

    /// Convenience: cutoff to "N years ago" relative to wall-clock now.
    pub fn since_years(mut self, years: u64) -> Self {
        let now_secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let cutoff = now_secs.saturating_sub(years * 365 * 24 * 60 * 60);
        self.since_seconds_unix = Some(cutoff);
        self
    }
}

#[derive(Debug, thiserror::Error)]
pub enum IngestGitError {
    #[error("walk error: {0}")]
    Walk(#[from] WalkError),
    #[error("storage error: {0}")]
    Storage(#[from] StorageError),
}

pub type IngestGitResult<T> = Result<T, IngestGitError>;

#[derive(Debug, Default, Clone, Copy)]
pub struct IngestGitStats {
    pub walk: WalkStats,
    /// Commits whose mode-A document was created or updated this run.
    pub documents_written: u64,
    /// Commits skipped because the mode-A document was already current.
    pub documents_unchanged: u64,
    /// Synthetic sessions created this run.
    pub sessions_created: u64,
    /// `ChangesFile` / `Authored` edges written.
    pub edges_written: u64,
}

/// Drive the pipeline. Synchronous walking (libgit2 doesn't release a
/// `Repository` across `await`), but per-commit persistence is async — we
/// collect commits in memory in batches and flush. For Phase 0 the batch
/// size is 1 (per-commit) for simplicity; the embedding + DB cost is the
/// bottleneck either way.
pub async fn ingest_repo(
    storage: &PostgresStorage,
    embedder: Arc<dyn Embedder>,
    cfg: &IngestGitConfig,
) -> IngestGitResult<IngestGitStats> {
    // 1) Walk synchronously, collect commits into memory. For huge repos
    //    we'd want to stream batches; Phase 0 is fine with a single Vec.
    let mut commits: Vec<CommitData> = Vec::new();
    let max = cfg.max_commits;
    let walker = CommitWalker::new(cfg);
    let walk_stats = walker.for_each(|c| {
        commits.push(c);
        if max > 0 && commits.len() as u64 >= max {
            std::ops::ControlFlow::Break(())
        } else {
            std::ops::ControlFlow::Continue(())
        }
    })?;

    // 2) Persist each commit. Embedding is the hot path; we batch a
    //    single embedder call per commit (small, but model-friendly when
    //    fastembed is wired up — its internal batching kicks in on the
    //    `embed_passages` call).
    let mut stats = IngestGitStats {
        walk: walk_stats,
        ..IngestGitStats::default()
    };

    for commit in commits {
        persist_commit(storage, embedder.as_ref(), cfg, &commit, &mut stats).await?;
    }

    Ok(stats)
}

async fn persist_commit(
    storage: &PostgresStorage,
    embedder: &dyn Embedder,
    cfg: &IngestGitConfig,
    commit: &CommitData,
    stats: &mut IngestGitStats,
) -> IngestGitResult<()> {
    let external_id = format!("git+sha:{}", commit.sha);
    let body = commit_body_text(commit);
    let content_hash = *blake3::hash(body.as_bytes()).as_bytes();
    let committer_millis: u64 = (commit.committer_time_seconds.max(0) as u64) * 1000;
    let is_squash = detect_squash_merge(commit);

    // Mode A: upsert the Document. Always run — even SessionsOnly mode
    // benefits from the side effect that `Unchanged` short-circuits the
    // rest of the per-commit work, making resync cheap.
    let metadata = MetadataMap {
        author: Some(format!("{} <{}>", commit.author_name, commit.author_email)),
        size_bytes: Some(body.len() as u64),
        word_count: Some(body.split_whitespace().count() as u32),
        source_modified_at: Some(committer_millis),
        tags: vec![],
        extra: serde_json::json!({
            "git": {
                "sha": commit.sha,
                "is_merge": commit.is_merge,
                "is_squash": is_squash,
                "files": commit.files.iter().map(|f| serde_json::json!({
                    "path": f.path,
                    "status": match f.status {
                        FileStatus::Added => "added",
                        FileStatus::Modified => "modified",
                        FileStatus::Removed => "removed",
                        FileStatus::Renamed => "renamed",
                    },
                    "old_path": f.old_path,
                })).collect::<Vec<_>>(),
            }
        }),
        ..Default::default()
    };
    let outcome = storage
        .upsert_document(NewDocument {
            workspace_id: cfg.workspace_id,
            source_id: cfg.source_id,
            external_id: Some(external_id.clone()),
            kind: ContentKind::Other("commit".into()),
            mime: "text/x-git-commit".into(),
            title: Some(commit.summary.clone()),
            path_or_url: Some(format!("git+sha:{}", commit.sha)),
            content_hash,
            acl: Acl::default(),
            metadata,
            source_modified_at: Some(committer_millis),
        })
        .await?;

    if outcome.is_unchanged() {
        stats.documents_unchanged += 1;
        return Ok(());
    }
    stats.documents_written += 1;
    let document_id = outcome.current_id();

    // Mode A continued: file-level edges from the commit Document. Each
    // file change becomes an edge to External(`git-path:<workspace>:<path>`)
    // since file paths aren't first-class Documents in Phase 0. Once
    // file-Documents exist (an LSP / repo tree adapter would create them),
    // we'll resolve to those; the External fallback keeps the edge useful
    // in the meantime.
    //
    // Phase 1.1 added: commit-message linkage edges (`Fixes:`, `Reverts:`,
    // `Cherry-picked from`) and per-coauthor `Authored` edges.
    if matches!(cfg.mode, IngestMode::DocumentsOnly | IngestMode::Both) {
        let parsed = linkage::parse(&commit.message);
        let mut edges: Vec<NewEdge> = Vec::with_capacity(
            commit.files.len()
                + 1
                + parsed.fixes.len()
                + parsed.reverts.len()
                + parsed.cherry_picked_from.len()
                + parsed.coauthors.len(),
        );
        // Authored edge: Document(commit) → External(github user)
        edges.push(NewEdge {
            workspace_id: cfg.workspace_id,
            from: NodeRef::Document(document_id),
            to: NodeRef::External(format!("git+author:{}", normalize_email(&commit.author_email))),
            kind: EdgeKind::Authored,
            weight: 1.0,
            metadata: MetadataMap::default(),
            created_by: EdgeOrigin::Adapter,
        });
        // Coauthor edges: same shape as Authored, weight 0.5 because the
        // primary author does the bulk of the work in most paired commits.
        // The schema lets multiple Authored edges coexist on a single
        // commit; the ranker is free to read them all when it learns to.
        for c in &parsed.coauthors {
            edges.push(NewEdge {
                workspace_id: cfg.workspace_id,
                from: NodeRef::Document(document_id),
                to: NodeRef::External(format!("git+author:{}", normalize_email(&c.email))),
                kind: EdgeKind::Authored,
                weight: 0.5,
                metadata: MetadataMap::default(),
                created_by: EdgeOrigin::Adapter,
            });
        }
        // Linkage edges. Targets are `git+sha:<sha>` externals — they may
        // dangle if we haven't ingested the referenced commit yet, which
        // is fine: when (or if) it's ingested, the existing
        // External("git+sha:<sha>") node won't be touched, and queries that
        // already use this edge will resolve through the fresh document.
        for sha in &parsed.fixes {
            edges.push(NewEdge {
                workspace_id: cfg.workspace_id,
                from: NodeRef::Document(document_id),
                to: NodeRef::External(format!("git+sha:{sha}")),
                kind: EdgeKind::Fixes,
                weight: 1.0,
                metadata: MetadataMap::default(),
                created_by: EdgeOrigin::Adapter,
            });
        }
        for sha in &parsed.reverts {
            edges.push(NewEdge {
                workspace_id: cfg.workspace_id,
                from: NodeRef::Document(document_id),
                to: NodeRef::External(format!("git+sha:{sha}")),
                kind: EdgeKind::Reverts,
                weight: 1.0,
                metadata: MetadataMap::default(),
                created_by: EdgeOrigin::Adapter,
            });
        }
        for sha in &parsed.cherry_picked_from {
            edges.push(NewEdge {
                workspace_id: cfg.workspace_id,
                from: NodeRef::Document(document_id),
                to: NodeRef::External(format!("git+sha:{sha}")),
                kind: EdgeKind::CherryPickedFrom,
                weight: 1.0,
                metadata: MetadataMap::default(),
                created_by: EdgeOrigin::Adapter,
            });
        }
        for f in &commit.files {
            let new_path_uri = format!("git+path:{}:{}", cfg.workspace_id, f.path);
            edges.push(NewEdge {
                workspace_id: cfg.workspace_id,
                from: NodeRef::Document(document_id),
                to: NodeRef::External(new_path_uri.clone()),
                kind: EdgeKind::ChangesFile,
                weight: f.status.default_weight(),
                metadata: MetadataMap {
                    extra: serde_json::json!({
                        "status": match f.status {
                            FileStatus::Added => "added",
                            FileStatus::Modified => "modified",
                            FileStatus::Removed => "removed",
                            FileStatus::Renamed => "renamed",
                        },
                        "old_path": f.old_path,
                    }),
                    ..Default::default()
                },
                created_by: EdgeOrigin::Adapter,
            });
            // Phase 1.5: symbol-level edges for code files. The walker
            // already resolved hunks → enclosing symbols via tree-sitter
            // and stuffed the qualified names into `f.symbols`. We emit
            // one `ChangesSymbol` edge per qname — sibling to the
            // `ChangesFile` edge above (not a replacement).
            for q in &f.symbols {
                let target = format!("git+symbol:{}:{}:{}", cfg.workspace_id, f.path, q);
                edges.push(NewEdge {
                    workspace_id: cfg.workspace_id,
                    from: NodeRef::Document(document_id),
                    to: NodeRef::External(target),
                    kind: EdgeKind::ChangesSymbol,
                    weight: 1.0,
                    metadata: MetadataMap::default(),
                    created_by: EdgeOrigin::Adapter,
                });
            }
            // File-identity bridge for renames (Phase 1.2). Lets the ranker
            // 1-hop from the new path to the old path's history. Idempotent:
            // if the same rename appears in multiple commits (e.g.
            // cherry-pick), ON CONFLICT collapses to one row.
            if let (FileStatus::Renamed, Some(old)) = (f.status, f.old_path.as_ref()) {
                let old_uri = format!("git+path:{}:{}", cfg.workspace_id, old);
                edges.push(NewEdge {
                    workspace_id: cfg.workspace_id,
                    from: NodeRef::External(new_path_uri),
                    to: NodeRef::External(old_uri),
                    kind: EdgeKind::RenamedFrom,
                    weight: 1.0,
                    metadata: MetadataMap::default(),
                    created_by: EdgeOrigin::Adapter,
                });
            }
        }
        if !edges.is_empty() {
            let ids = storage.add_edges(edges).await?;
            stats.edges_written += ids.len() as u64;
        }
    }

    // Mode B: synthetic session. The commit message becomes the session
    // context (queryable by the predictive ranker via cosine similarity);
    // each file change becomes one interaction; one score row per file.
    //
    // Phase 1.4: when this commit is subsumed by a merge (i.e. it's a
    // branch member of an already-aggregated merge session), skip session
    // creation entirely. The merge's session covers it.
    let subsumed = commit.subsumed_by_merge.is_some();
    if matches!(cfg.mode, IngestMode::SessionsOnly | IngestMode::Both) && !subsumed {
        let context_text = commit.message.trim().to_string();
        let context_embedding = if context_text.is_empty() {
            None
        } else {
            Some(embedder.embed_passage(&context_text))
        };

        // For merges with branch aggregation, the synthetic session
        // represents the entire feature branch — its interactions come
        // from `aggregated_files`. Falls back to the commit's own diff
        // for the non-merge case.
        let session_files: &[FileChange] = commit
            .aggregated_files
            .as_deref()
            .unwrap_or(commit.files.as_slice());
        let mut interactions: Vec<SyntheticInteraction> = Vec::with_capacity(session_files.len());
        let mut scores: Vec<NewSessionScore> = Vec::with_capacity(session_files.len());
        for f in session_files {
            let target = NodeRef::External(format!("git+path:{}:{}", cfg.workspace_id, f.path));
            let event_type = f.status.event_type();
            let weight = f.status.default_weight();
            interactions.push(SyntheticInteraction {
                iteration: 0,
                event_type,
                target: target.clone(),
                weight,
            });
            // Pattern is a coarse classifier of the per-target interaction
            // history. With one event per file in Phase 0 we just map by
            // event type; Phase 1 (branch-as-session) will see multiple
            // events per file and produce richer patterns.
            let pattern = match event_type {
                EventType::Cited => Pattern::Cited,
                EventType::Edited => Pattern::EditOnly,
                EventType::Dismissed => Pattern::Dismissed,
                EventType::Read | EventType::Retrieved => Pattern::Neutral,
            };
            scores.push(NewSessionScore {
                target,
                score: weight * pattern.multiplier(),
                access_count: 1,
                productivity: cfg.productivity_default,
                pattern,
                was_edited: matches!(
                    f.status,
                    FileStatus::Added | FileStatus::Modified | FileStatus::Renamed
                ),
            });
        }

        let agent_id = format!("git:{}", normalize_email(&commit.author_email));
        let _sid = storage
            .record_synthetic_session(SyntheticSessionWrite {
                workspace_id: cfg.workspace_id,
                agent_id,
                created_at: committer_millis,
                context_kind: ContextKind::StepDescription,
                context_content: if context_text.is_empty() { commit.summary.clone() } else { context_text },
                context_embedding,
                interactions,
                scores,
            })
            .await?;
        stats.sessions_created += 1;
    }
    Ok(())
}

/// Squash-merge detection (Phase 1.3). GitHub's "Squash and merge" produces
/// a single non-merge commit on the target branch whose summary line ends
/// with `(#NNN)` — the PR number — and whose body contains the squashed
/// commits' messages. We can't be 100% sure (a contributor can manually
/// commit with `(#NNN)` in the subject), but the heuristic is good enough
/// to flag the commit as "treat its body as a multi-commit summary, not a
/// WIP slice." Future Phase 1.4 (branch-as-session) uses this to avoid
/// attempting branch aggregation on commits that already represent a
/// branch.
fn detect_squash_merge(c: &CommitData) -> bool {
    if c.is_merge {
        return false;
    }
    // Subject contains `(#NNN)` near the end. We accept multi-digit PR
    // numbers; one digit is too unconstrained.
    let subject = c.summary.as_str();
    let has_pr_marker = subject_has_pr_marker(subject);
    // Body has more than just the subject: multiple paragraphs or at
    // least one extra non-blank line. A squash typically inlines the
    // squashed commits' messages.
    let has_body = c
        .message
        .lines()
        .skip(1)
        .any(|l| !l.trim().is_empty());
    has_pr_marker && has_body
}

fn subject_has_pr_marker(subject: &str) -> bool {
    // Walk from the right looking for `(#NNN)`. Permissive: trailing
    // whitespace allowed.
    let trimmed = subject.trim_end();
    let bytes = trimmed.as_bytes();
    let n = bytes.len();
    if n < 5 || bytes[n - 1] != b')' {
        return false;
    }
    // Find the matching `(`. Scan back at most 16 chars (PRs have at most
    // ~9-digit numbers).
    let limit = n.saturating_sub(16);
    let mut i = n - 2;
    while i >= limit {
        if bytes[i] == b'(' {
            // Inside must be `#` then >=2 digits.
            let inside = &bytes[i + 1..n - 1];
            if inside.first() == Some(&b'#')
                && inside[1..].iter().all(|b| b.is_ascii_digit())
                && inside.len() >= 3
            {
                return true;
            }
            return false;
        }
        if i == 0 {
            break;
        }
        i -= 1;
    }
    false
}

/// Compose the Document body for mode A. The body is what callers retrieve
/// when ranking surfaces this commit, so it must be self-contained: message
/// + a compact per-file manifest with statuses.
fn commit_body_text(c: &CommitData) -> String {
    let mut s = String::with_capacity(c.message.len() + c.files.len() * 64);
    s.push_str(&c.message);
    if !c.message.ends_with('\n') {
        s.push('\n');
    }
    s.push_str("\n--- files ---\n");
    for f in &c.files {
        let label = match f.status {
            FileStatus::Added => "A",
            FileStatus::Modified => "M",
            FileStatus::Removed => "D",
            FileStatus::Renamed => "R",
        };
        if let Some(old) = &f.old_path {
            s.push_str(&format!("{label}\t{old} -> {}\n", f.path));
        } else {
            s.push_str(&format!("{label}\t{}\n", f.path));
        }
    }
    s
}

/// Lowercase + strip a leading `<` / trailing `>` if present. We use the
/// normalized form as the agent_id suffix so the same author isn't split
/// into "Alice <alice@x>" and "alice@x" buckets.
fn normalize_email(email: &str) -> String {
    email.trim_start_matches('<').trim_end_matches('>').to_ascii_lowercase()
}

/// Convenience: ensure a `Source` row exists for this repo, creating one if
/// missing. Idempotent on `(workspace, kind, name)` via lookup-then-create.
/// The CLI uses this to avoid forcing the operator to wire a source by hand.
pub async fn ensure_source(
    storage: &PostgresStorage,
    workspace_id: WorkspaceId,
    name: &str,
    repo_path: &std::path::Path,
) -> StorageResult<SourceId> {
    if let Some(id) = storage.find_source_by_name(workspace_id, name).await {
        return Ok(id);
    }
    storage
        .create_source(NewSource {
            workspace_id,
            kind: SourceKind::Custom("git".into()),
            name: name.to_string(),
            config_json: serde_json::json!({
                "kind": "git",
                "repo_path": repo_path.to_string_lossy(),
            }),
            keep_history: false,
            default_acl: Acl::default(),
        })
        .await
}

/// Convert a `serde_json` value to a `serde_json::Value` representing
/// `EventType` — used in metadata fields for forensic dumps. Kept private
/// because `EventType::serde_json` already handles roundtrip; this only
/// exists if the test wants a human-readable status check.
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_status_to_event_type_mapping() {
        assert_eq!(FileStatus::Added.event_type(), EventType::Cited);
        assert_eq!(FileStatus::Modified.event_type(), EventType::Edited);
        assert_eq!(FileStatus::Renamed.event_type(), EventType::Edited);
        assert_eq!(FileStatus::Removed.event_type(), EventType::Dismissed);
    }

    #[test]
    fn since_years_yields_a_cutoff_in_the_past() {
        let cfg = IngestGitConfig::new("/tmp/repo", WorkspaceId(1), SourceId(1)).since_years(2);
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let cutoff = cfg.since_seconds_unix.unwrap();
        assert!(cutoff < now, "cutoff should be in the past");
        assert!(now - cutoff >= (2 * 365 * 24 * 60 * 60) - 60);
    }

    #[test]
    fn commit_body_text_includes_files_with_statuses() {
        let c = CommitData {
            sha: "abc".into(),
            summary: "fix x".into(),
            message: "fix x\n\ndetailed why".into(),
            author_name: "alice".into(),
            author_email: "alice@example.com".into(),
            committer_time_seconds: 0,
            is_merge: false,
            is_whitespace_only: false,
            files: vec![
                FileChange {
                    path: "a.rs".into(),
                    status: FileStatus::Modified,
                    old_path: None,
                    hunks: vec![],
                    new_blob_oid: None,
                    symbols: vec![],
                },
                FileChange {
                    path: "b.rs".into(),
                    status: FileStatus::Added,
                    old_path: None,
                    hunks: vec![],
                    new_blob_oid: None,
                    symbols: vec![],
                },
                FileChange {
                    path: "c.rs".into(),
                    status: FileStatus::Removed,
                    old_path: None,
                    hunks: vec![],
                    new_blob_oid: None,
                    symbols: vec![],
                },
                FileChange {
                    path: "new.rs".into(),
                    status: FileStatus::Renamed,
                    old_path: Some("old.rs".into()),
                    hunks: vec![],
                    new_blob_oid: None,
                    symbols: vec![],
                },
            ],
            aggregated_files: None,
            subsumed_by_merge: None,
        };
        let body = commit_body_text(&c);
        assert!(body.starts_with("fix x"));
        assert!(body.contains("M\ta.rs"));
        assert!(body.contains("A\tb.rs"));
        assert!(body.contains("D\tc.rs"));
        assert!(body.contains("R\told.rs -> new.rs"));
    }

    #[test]
    fn normalize_email_strips_brackets_and_lowers() {
        assert_eq!(normalize_email("<Alice@Example.com>"), "alice@example.com");
        assert_eq!(normalize_email("alice@x"), "alice@x");
    }

    #[test]
    fn default_weights_match_design_doc() {
        // From doc 10: Added=1.5, Modified=1.0, Removed=1.0
        assert_eq!(FileStatus::Added.default_weight(), 1.5);
        assert_eq!(FileStatus::Modified.default_weight(), 1.0);
        assert_eq!(FileStatus::Removed.default_weight(), 1.0);
    }

    fn commit_for_test(summary: &str, body: &str) -> CommitData {
        let message = if body.is_empty() {
            summary.to_string()
        } else {
            format!("{summary}\n\n{body}")
        };
        CommitData {
            sha: "abc".into(),
            summary: summary.into(),
            message,
            author_name: "a".into(),
            author_email: "a@b".into(),
            committer_time_seconds: 0,
            is_merge: false,
            is_whitespace_only: false,
            files: vec![],
            aggregated_files: None,
            subsumed_by_merge: None,
        }
    }

    #[test]
    fn squash_marker_at_end_of_subject() {
        assert!(subject_has_pr_marker("feat: rate limit (#123)"));
        assert!(subject_has_pr_marker("fix: parser bug (#1)") == false); // 1 digit blocked
        assert!(subject_has_pr_marker("fix: parser bug (#12)"));
        assert!(subject_has_pr_marker("Update deps (#999999)"));
        assert!(!subject_has_pr_marker("feat: rate limit"));
        assert!(!subject_has_pr_marker("feat: rate limit (#abc)"));
        // (123) without # is not a PR marker.
        assert!(!subject_has_pr_marker("feat: rate limit (123)"));
    }

    #[test]
    fn detect_squash_requires_pr_marker_and_body() {
        assert!(detect_squash_merge(&commit_for_test(
            "fix: thing (#42)",
            "* squashed: x\n* squashed: y\n"
        )));
        // No body — could be a manually-typed subject, not a squash.
        assert!(!detect_squash_merge(&commit_for_test("fix: thing (#42)", "")));
        // Body but no PR marker.
        assert!(!detect_squash_merge(&commit_for_test(
            "fix: thing",
            "Long description here.\n"
        )));
    }

    #[test]
    fn merge_commits_are_not_squashes() {
        let mut c = commit_for_test("fix: thing (#42)", "body\n");
        c.is_merge = true;
        assert!(!detect_squash_merge(&c));
    }
}
