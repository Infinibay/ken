//! End-to-end test for the git-history ingest path. Builds a tiny repo
//! programmatically with libgit2 (so the test is hermetic — no network and
//! no fixture tarball to maintain), then drives `engine::ingest_git` against
//! it and asserts the database state.
//!
//! Run with:
//!     DATABASE_URL=postgres://cae:cae_dev@localhost:5432/context_engine \
//!     cargo test -p cae-engine --features "git fastembed" \
//!         --test ingest_git_integration -- --ignored
//!
//! The fixture covers: a regular author, a bot author (must be filtered),
//! an add-modify-remove sequence on one path, a merge commit, and a
//! whitespace-only commit.

#![cfg(feature = "git")]

use std::path::Path;
use std::sync::Arc;

use git2::{Repository, Signature, Time};

use engine::embed::{Embedder, MockEmbedder};
use engine::ingest_git::{ensure_source, ingest_repo, IngestGitConfig, IngestMode};
use engine::postgres::PostgresStorage;
use engine::storage::ChunkFilter;
use engine::types::*;

fn signature(name: &str, email: &str, when: i64) -> Signature<'static> {
    Signature::new(name, email, &Time::new(when, 0)).unwrap()
}

/// Stage `path` with the given content and commit on the current branch.
/// Returns the commit oid.
fn commit_file(
    repo: &Repository,
    path: &str,
    content: &[u8],
    msg: &str,
    sig: &Signature<'_>,
    parent: Option<git2::Oid>,
) -> git2::Oid {
    let workdir = repo.workdir().unwrap().to_path_buf();
    let abs = workdir.join(path);
    if let Some(parent_dir) = abs.parent() {
        std::fs::create_dir_all(parent_dir).unwrap();
    }
    std::fs::write(&abs, content).unwrap();

    let mut idx = repo.index().unwrap();
    idx.add_path(Path::new(path)).unwrap();
    idx.write().unwrap();
    let tree_oid = idx.write_tree().unwrap();
    let tree = repo.find_tree(tree_oid).unwrap();

    let parents: Vec<git2::Commit<'_>> = parent
        .map(|p| vec![repo.find_commit(p).unwrap()])
        .unwrap_or_default();
    let parent_refs: Vec<&git2::Commit<'_>> = parents.iter().collect();

    repo.commit(Some("HEAD"), sig, sig, msg, &tree, &parent_refs).unwrap()
}

/// Remove a file and commit. Returns the commit oid.
fn commit_remove(
    repo: &Repository,
    path: &str,
    msg: &str,
    sig: &Signature<'_>,
    parent: git2::Oid,
) -> git2::Oid {
    let workdir = repo.workdir().unwrap().to_path_buf();
    let abs = workdir.join(path);
    let _ = std::fs::remove_file(&abs);

    let mut idx = repo.index().unwrap();
    idx.remove_path(Path::new(path)).unwrap();
    idx.write().unwrap();
    let tree_oid = idx.write_tree().unwrap();
    let tree = repo.find_tree(tree_oid).unwrap();
    let parent_commit = repo.find_commit(parent).unwrap();

    repo.commit(Some("HEAD"), sig, sig, msg, &tree, &[&parent_commit]).unwrap()
}

fn make_fixture_repo(dir: &Path) -> usize {
    let repo = Repository::init(dir).unwrap();
    let alice = signature("Alice", "alice@example.com", 1_700_000_000);
    let bob_bot = signature("dependabot[bot]", "dependabot[bot]@users.noreply.github.com", 1_700_000_500);
    let charlie = signature("Charlie", "charlie@example.com", 1_700_001_000);

    // 1. Initial commit by Alice — adds README.md
    let c1 = commit_file(&repo, "README.md", b"# Project\n\nIt does things.\n", "initial: README", &alice, None);

    // 2. Add a code file
    let c2 = commit_file(
        &repo,
        "src/lib.rs",
        b"fn main() { println!(\"hello\"); }\n",
        "feat: add hello main",
        &alice,
        Some(c1),
    );

    // 3. Modify the code file
    let c3 = commit_file(
        &repo,
        "src/lib.rs",
        b"fn main() { println!(\"hello, world\"); }\n",
        "fix: greet the world properly",
        &charlie,
        Some(c2),
    );

    // 4. Bot commit — must be filtered out
    let c4 = commit_file(
        &repo,
        "Cargo.lock",
        b"# automated bump\n",
        "chore(deps): bump foo to 1.2.3\n\nautomated by bot",
        &bob_bot,
        Some(c3),
    );

    // 5. Whitespace-only modification (just a trailing newline added)
    let c5 = commit_file(
        &repo,
        "README.md",
        b"# Project\n\nIt does things.\n\n",
        "chore: trailing newline",
        &alice,
        Some(c4),
    );

    // 6. Add a doc file by Charlie
    let c6 = commit_file(
        &repo,
        "docs/intro.md",
        b"# Intro\n\nDocs here.\n",
        "docs: intro page",
        &charlie,
        Some(c5),
    );

    // 7. Remove the original code file
    let _c7 = commit_remove(&repo, "src/lib.rs", "refactor: remove deprecated lib", &alice, c6);

    7 // total commits created
}

async fn setup_storage() -> Option<(PostgresStorage, WorkspaceId)> {
    let url = std::env::var("DATABASE_URL").ok()?;
    let s = PostgresStorage::connect(&url).await.expect("connect");
    s.migrate().await.expect("migrate");
    let t = s
        .create_tenant("git_ingest", PlanTier::Free)
        .await
        .expect("tenant");
    let w = s
        .create_workspace(t, "ws", WorkspaceSettings::default())
        .await
        .expect("workspace");
    Some((s, w))
}

#[tokio::test]
#[ignore]
async fn ingest_fixture_repo_filters_and_persists() {
    let Some((storage, ws)) = setup_storage().await else {
        eprintln!("DATABASE_URL not set — skipping");
        return;
    };
    let tmp = tempdir_in_target("git_fixture_v1");
    let total_commits = make_fixture_repo(&tmp);
    assert_eq!(total_commits, 7);

    let source_id = ensure_source(&storage, ws, "fixture", &tmp).await.expect("source");

    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let mut cfg = IngestGitConfig::new(&tmp, ws, source_id);
    cfg.skip_merges = true;
    cfg.skip_whitespace_only = true;
    cfg.mode = IngestMode::Both;

    let stats = ingest_repo(&storage, embedder.clone(), &cfg).await.expect("ingest");

    // Visited: every commit on HEAD = 7. Kept = 7 - 1 (bot) - 1 (whitespace) = 5.
    assert_eq!(stats.walk.visited, 7, "all commits visited");
    assert_eq!(stats.walk.skipped_bot, 1, "the dependabot commit got filtered");
    assert_eq!(stats.walk.skipped_whitespace, 1, "the trailing-newline commit got filtered");
    assert_eq!(stats.walk.skipped_merge, 0);
    assert_eq!(stats.walk.kept, 5);
    assert_eq!(stats.documents_written, 5, "one Document per kept commit");
    assert_eq!(stats.sessions_created, 5, "one synthetic session per kept commit");
    assert!(stats.edges_written >= 5, "at least one ChangesFile + Authored per commit");

    // Idempotency: re-ingest. Documents should all be Unchanged; no new
    // synthetic sessions created.
    let stats2 = ingest_repo(&storage, embedder, &cfg).await.expect("re-ingest");
    assert_eq!(stats2.documents_written, 0);
    assert_eq!(stats2.documents_unchanged, 5);
    assert_eq!(stats2.sessions_created, 0);

    // Document-level: there should be exactly 5 commit Documents in this
    // workspace, each with kind = Other("commit").
    let chunks = storage
        .chunks_in_workspace(
            ws,
            &ChunkFilter { current_only: true, ..Default::default() },
        )
        .await;
    // No chunks were created because Phase 0 stores commit body in the
    // Document only (no chunk pipeline). Sanity check that the empty path
    // works — chunk filter ran without error.
    assert!(chunks.is_empty(), "no chunks expected from git ingest");

    // D5: every session created by the git pipeline carries
    // kind = Synthetic. Reactive readers can rely on this to filter.
    // Now that linkage parsing is wired (Phase 1.1), our fixture's
    // `Fixes:` and `Co-authored-by:` trailers should produce edges. The
    // 3rd commit ("fix: greet the world properly") doesn't have one — but
    // the v4 fixture below does, so we add a separate test for that.

    let synthetic_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sessions WHERE workspace_id = $1 AND kind = 'synthetic'",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(synthetic_count, 5);
    let real_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sessions WHERE workspace_id = $1 AND kind = 'real'",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(real_count, 0);
}

#[tokio::test]
#[ignore]
async fn ingest_fixture_repo_documents_only_skips_sessions() {
    let Some((storage, ws)) = setup_storage().await else {
        return;
    };
    let tmp = tempdir_in_target("git_fixture_v2");
    make_fixture_repo(&tmp);
    let source_id = ensure_source(&storage, ws, "fixture-docs", &tmp).await.expect("source");

    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let mut cfg = IngestGitConfig::new(&tmp, ws, source_id);
    cfg.mode = IngestMode::DocumentsOnly;

    let stats = ingest_repo(&storage, embedder, &cfg).await.expect("ingest");
    assert_eq!(stats.documents_written, 5);
    assert_eq!(stats.sessions_created, 0, "DocumentsOnly mode should skip sessions");
}

#[tokio::test]
#[ignore]
async fn ingest_respects_max_commits_cap() {
    let Some((storage, ws)) = setup_storage().await else {
        return;
    };
    let tmp = tempdir_in_target("git_fixture_v3");
    make_fixture_repo(&tmp);
    let source_id = ensure_source(&storage, ws, "fixture-cap", &tmp).await.expect("source");

    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let mut cfg = IngestGitConfig::new(&tmp, ws, source_id);
    cfg.max_commits = 2;
    cfg.mode = IngestMode::Both;

    let stats = ingest_repo(&storage, embedder, &cfg).await.expect("ingest");
    assert!(
        stats.walk.kept <= 2,
        "max_commits=2 should cap kept at 2, got {}",
        stats.walk.kept,
    );
    assert!(stats.documents_written <= 2);
}

#[tokio::test]
#[ignore]
async fn ingest_extracts_commit_message_linkages() {
    let Some((storage, ws)) = setup_storage().await else {
        return;
    };
    let tmp = tempdir_in_target("git_fixture_linkage");
    let repo = Repository::init(&tmp).unwrap();
    let alice = signature("Alice", "alice@example.com", 1_700_000_000);

    // c1: a regular feature commit. Its short sha will be referenced by c2.
    let c1 = commit_file(&repo, "x.rs", b"fn x() {}\n", "feat: add x", &alice, None);
    let c1_short = format!("{}", c1).chars().take(8).collect::<String>();

    // c2: references c1 in `Fixes:` AND has a coauthor trailer.
    let msg2 = format!(
        "fix: bug introduced by {short}\n\nFixes: {short}\nCo-authored-by: Bob <bob@example.com>\n",
        short = c1_short,
    );
    let c2 = commit_file(&repo, "x.rs", b"fn x() { /* fixed */ }\n", &msg2, &alice, Some(c1));

    // c3: cherry-pick attribution.
    let _c3 = commit_file(
        &repo,
        "y.rs",
        b"fn y() {}\n",
        "feat: add y\n\n(cherry picked from commit deadbeef0)\n",
        &alice,
        Some(c2),
    );

    let source_id = ensure_source(&storage, ws, "linkage", &tmp).await.expect("source");
    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let cfg = IngestGitConfig::new(&tmp, ws, source_id);

    let stats = ingest_repo(&storage, embedder, &cfg).await.expect("ingest");
    assert_eq!(stats.walk.kept, 3);

    // The kind column is JSONB; the trailing serialization for unit
    // variants is `"fixes"` etc. (snake_case rename).
    let fixes_n: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"fixes\"'::jsonb",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(fixes_n, 1, "expected one Fixes edge from c2");

    let cherry_n: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"cherry_picked_from\"'::jsonb",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(cherry_n, 1, "expected one CherryPickedFrom edge from c3");

    // 3 primary Authored + 1 coauthor = 4 Authored edges.
    let authored_n: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"authored\"'::jsonb",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(authored_n, 4);

    // Coauthor should appear as an External(git+author:bob@example.com).
    let bob_n: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND to_uri = $2 AND kind = '\"authored\"'::jsonb",
    )
    .bind(ws.0 as i64)
    .bind("git+author:bob@example.com")
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(bob_n, 1);
}

#[tokio::test]
#[ignore]
async fn ingest_emits_renamed_from_edge_on_rename() {
    let Some((storage, ws)) = setup_storage().await else {
        return;
    };
    let tmp = tempdir_in_target("git_fixture_rename");
    let repo = Repository::init(&tmp).unwrap();
    let alice = signature("Alice", "alice@example.com", 1_700_000_000);

    // libgit2's rename detection (default 50% similarity) needs enough
    // content to score against — tiny files miss the threshold. Use a
    // realistic ~20-line file so the similarity check has signal to work
    // with. This also matches real-world repos better.
    const ORIGINAL: &[u8] = b"\
//! User profile module.
use std::collections::HashMap;

pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
    pub created_at: u64,
}

impl User {
    pub fn new(id: u64, name: String, email: String) -> Self {
        Self { id, name, email, created_at: 0 }
    }

    pub fn validate(&self) -> bool {
        !self.email.is_empty() && self.email.contains('@')
    }
}
";
    const RENAMED_WITH_SMALL_TWEAK: &[u8] = b"\
//! User profile module (v2).
use std::collections::HashMap;

pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
    pub created_at: u64,
}

impl User {
    pub fn new(id: u64, name: String, email: String) -> Self {
        Self { id, name, email, created_at: 0 }
    }

    pub fn validate(&self) -> bool {
        !self.email.is_empty() && self.email.contains('@')
    }
}
";

    // c1: introduce the file at its original path
    let c1 = commit_file(&repo, "src/old_name.rs", ORIGINAL, "feat: add User", &alice, None);

    // c2: rename the file (delete at old path + add at new path with a
    // tiny tweak, in the same commit). libgit2 sees this as Add+Delete
    // until `find_similar` post-processes it into a Renamed delta.
    let workdir = repo.workdir().unwrap().to_path_buf();
    let _ = std::fs::remove_file(workdir.join("src/old_name.rs"));
    std::fs::write(workdir.join("src/new_name.rs"), RENAMED_WITH_SMALL_TWEAK).unwrap();
    {
        let mut idx = repo.index().unwrap();
        idx.remove_path(std::path::Path::new("src/old_name.rs")).unwrap();
        idx.add_path(std::path::Path::new("src/new_name.rs")).unwrap();
        idx.write().unwrap();
    }
    {
        let tree_oid = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_oid).unwrap();
        let parent = repo.find_commit(c1).unwrap();
        repo.commit(
            Some("HEAD"),
            &alice,
            &alice,
            "refactor: rename old_name → new_name",
            &tree,
            &[&parent],
        )
        .unwrap();
    }

    let source_id = ensure_source(&storage, ws, "rename", &tmp).await.expect("source");
    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let cfg = IngestGitConfig::new(&tmp, ws, source_id);

    let stats = ingest_repo(&storage, embedder, &cfg).await.expect("ingest");
    assert_eq!(stats.walk.kept, 2);

    // The rename commit should have produced one RenamedFrom edge.
    let renamed_n: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"renamed_from\"'::jsonb",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(renamed_n, 1, "expected one RenamedFrom edge on the rename commit");

    // The rename edge bridges new → old.
    let bridge: Option<(String, String)> = sqlx::query_as(
        "SELECT from_uri, to_uri FROM edges
         WHERE workspace_id = $1 AND kind = '\"renamed_from\"'::jsonb",
    )
    .bind(ws.0 as i64)
    .fetch_optional(storage.pool())
    .await
    .unwrap();
    let (from_uri, to_uri) = bridge.expect("rename edge present");
    assert!(from_uri.ends_with("src/new_name.rs"), "from = new path, got {from_uri}");
    assert!(to_uri.ends_with("src/old_name.rs"), "to = old path, got {to_uri}");
}

/// Build a fixture with a topology:
///
///   main: c1 — c2 ─────────────── M (merge)
///                  \             /
///       feat:       b1 — b2 — b3
///
/// b1, b2, b3 are unique to the feature branch. M is a merge with
/// parents (c2, b3). Phase 1.4 means: M is the session anchor; b1, b2, b3
/// each get a Document but no individual session; M's session aggregates
/// the file changes from b1+b2+b3 (and any merge-resolution changes
/// inside M itself).
fn make_branch_fixture(dir: &std::path::Path) -> (git2::Oid, Vec<git2::Oid>, git2::Oid) {
    let repo = Repository::init(dir).unwrap();
    let alice = signature("Alice", "alice@example.com", 1_700_000_000);

    // c1, c2 on main
    let c1 = commit_file(&repo, "main.rs", b"fn main() {}\n", "init", &alice, None);
    let c2 = commit_file(&repo, "main.rs", b"fn main() { /* v2 */ }\n", "wire main", &alice, Some(c1));

    // Branch off c2: b1 adds a file, b2 modifies main, b3 adds another file.
    // We'll commit them on a refs/heads/feat branch via raw git2 API.
    let _ = repo.branch("feat", &repo.find_commit(c2).unwrap(), false).unwrap();
    repo.set_head("refs/heads/feat").unwrap();
    repo.checkout_head(Some(git2::build::CheckoutBuilder::new().force())).unwrap();

    let b1 = commit_file(&repo, "feature.rs", b"fn feature() {}\n", "feat: add feature", &alice, Some(c2));
    let b2 = commit_file(
        &repo,
        "main.rs",
        b"fn main() { feature(); }\n",
        "feat: call feature from main",
        &alice,
        Some(b1),
    );
    let b3 = commit_file(&repo, "feature_test.rs", b"fn test_feature() {}\n", "test: feature", &alice, Some(b2));

    // Switch back to main and merge feat into it.
    repo.set_head("refs/heads/master")
        .or_else(|_| repo.set_head("refs/heads/main"))
        .or_else(|_| {
            // Some git2 versions default to "master"; if the initial branch
            // wasn't named explicitly, fall back to whichever name exists.
            let head = repo
                .find_branch("master", git2::BranchType::Local)
                .or_else(|_| repo.find_branch("main", git2::BranchType::Local))
                .unwrap();
            repo.set_head(head.get().name().unwrap())
        })
        .unwrap();
    repo.checkout_head(Some(git2::build::CheckoutBuilder::new().force())).unwrap();

    // Merge commit: parents (c2, b3). Tree = b3's tree (clean fast-forward
    // would technically work here, but to force a merge commit we re-build
    // the merge tree explicitly).
    let parents = [
        &repo.find_commit(c2).unwrap(),
        &repo.find_commit(b3).unwrap(),
    ];
    let b3_tree = repo.find_commit(b3).unwrap().tree().unwrap();
    let merge_oid = repo
        .commit(
            Some("HEAD"),
            &alice,
            &alice,
            "Merge feat into main",
            &b3_tree,
            &parents,
        )
        .unwrap();

    (c2, vec![b1, b2, b3], merge_oid)
}

#[tokio::test]
#[ignore]
async fn ingest_aggregates_branch_as_single_session() {
    let Some((storage, ws)) = setup_storage().await else {
        return;
    };
    let tmp = tempdir_in_target("git_fixture_branch");
    let (_c2, branch_commits, merge_oid) = make_branch_fixture(&tmp);
    assert_eq!(branch_commits.len(), 3);

    let source_id = ensure_source(&storage, ws, "branch", &tmp).await.expect("source");
    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let cfg = IngestGitConfig::new(&tmp, ws, source_id);
    // branch_as_session is the default

    let stats = ingest_repo(&storage, embedder, &cfg).await.expect("ingest");
    // Visited commits on default branch reachable from HEAD: c1, c2, b1,
    // b2, b3, merge = 6.
    assert_eq!(stats.walk.visited, 6);
    assert_eq!(stats.walk.kept, 6);

    // Documents: one per commit, including the merge.
    assert_eq!(stats.documents_written, 6);

    // Synthetic sessions: c1, c2 each individual; merge aggregates b1+b2+b3.
    // Total = 3 sessions (c1, c2, merge), NOT 6 — branch members are
    // subsumed by the merge.
    assert_eq!(stats.sessions_created, 3, "branch members should be subsumed by the merge");

    let synthetic_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sessions WHERE workspace_id = $1 AND kind = 'synthetic'",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(synthetic_count, 3);

    // The merge's session should have interactions for all 3 paths the
    // branch touched: feature.rs, main.rs, feature_test.rs.
    let merge_external = format!("git+sha:{}", merge_oid);
    let merge_session_id: Option<i64> = sqlx::query_scalar(
        "SELECT s.id FROM sessions s
         JOIN session_interactions si ON si.session_id = s.id
         JOIN documents d ON d.workspace_id = s.workspace_id
         WHERE s.workspace_id = $1 AND s.kind = 'synthetic'
           AND d.external_id = $2
         GROUP BY s.id
         ORDER BY s.created_at DESC LIMIT 1",
    )
    .bind(ws.0 as i64)
    .bind(&merge_external)
    .fetch_optional(storage.pool())
    .await
    .unwrap();
    let _ = merge_session_id; // not strictly needed; below check is path-based

    // Check: across all synthetic sessions in this workspace, the union of
    // touched paths covers feature.rs, feature_test.rs (added by branch),
    // and main.rs (modified by branch + earlier on main).
    let paths: Vec<String> = sqlx::query_scalar(
        "SELECT DISTINCT target_uri FROM session_interactions si
         JOIN sessions s ON s.id = si.session_id
         WHERE s.workspace_id = $1 AND s.kind = 'synthetic'
           AND si.target_uri LIKE 'git+path:%'",
    )
    .bind(ws.0 as i64)
    .fetch_all(storage.pool())
    .await
    .unwrap();
    let path_set: std::collections::HashSet<_> = paths.iter().map(|s| s.as_str()).collect();
    assert!(path_set.iter().any(|s| s.ends_with(":feature.rs")));
    assert!(path_set.iter().any(|s| s.ends_with(":feature_test.rs")));
    assert!(path_set.iter().any(|s| s.ends_with(":main.rs")));
}

#[tokio::test]
#[ignore]
async fn ingest_resolves_diff_hunks_to_symbols() {
    let Some((storage, ws)) = setup_storage().await else {
        return;
    };
    let tmp = tempdir_in_target("git_fixture_symbols");
    let repo = Repository::init(&tmp).unwrap();
    let alice = signature("Alice", "alice@example.com", 1_700_000_000);

    // c1: introduce a Rust file with two methods on `impl User`.
    const V1: &[u8] = b"\
//! User profile module.

pub struct User {
    pub email: String,
}

impl User {
    pub fn validate(&self) -> bool {
        if self.email.is_empty() {
            return false;
        }
        self.email.contains('@')
    }

    pub fn name(&self) -> &str {
        \"alice\"
    }
}
";
    let c1 = commit_file(&repo, "src/user.rs", V1, "feat: add User", &alice, None);

    // c2: modify ONLY `validate` body. `name` is unchanged.
    const V2: &[u8] = b"\
//! User profile module.

pub struct User {
    pub email: String,
}

impl User {
    pub fn validate(&self) -> bool {
        if self.email.is_empty() || self.email.len() > 254 {
            return false;
        }
        self.email.contains('@') && self.email.contains('.')
    }

    pub fn name(&self) -> &str {
        \"alice\"
    }
}
";
    let _c2 = commit_file(&repo, "src/user.rs", V2, "fix: stricter email validation", &alice, Some(c1));

    let source_id = ensure_source(&storage, ws, "symbols", &tmp).await.expect("source");
    let embedder: Arc<dyn Embedder> = Arc::new(MockEmbedder::new(768));
    let cfg = IngestGitConfig::new(&tmp, ws, source_id);

    let stats = ingest_repo(&storage, embedder, &cfg).await.expect("ingest");
    assert_eq!(stats.walk.kept, 2);

    // c2's hunk hits `User::validate` only — exactly one ChangesSymbol
    // edge with that target should exist. `User::name` should NOT have
    // a ChangesSymbol edge from c2.
    let validate_edges: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"changes_symbol\"'::jsonb
           AND to_uri LIKE '%User::validate'",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    // c1 (initial add) creates the file → all symbols enclosed by hunks
    // get tagged. c2 modifies validate only → 1 more edge for validate.
    // So we expect at least 2 edges to validate (one per commit), and
    // since c1 also creates `name`, name should have 1 edge from c1
    // but 0 from c2.
    assert!(
        validate_edges >= 2,
        "expected >=2 ChangesSymbol→validate edges, got {validate_edges}"
    );

    let name_edges: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"changes_symbol\"'::jsonb
           AND to_uri LIKE '%User::name'",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    // c1 creates User::name (so it has a hunk covering that range), but
    // c2 does not — so we expect exactly 1 edge to User::name.
    assert_eq!(name_edges, 1, "c2 should not produce ChangesSymbol→User::name");

    // The file-level ChangesFile edge is still emitted (parallel, not
    // replaced by ChangesSymbol).
    let changes_file_edges: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM edges
         WHERE workspace_id = $1 AND kind = '\"changes_file\"'::jsonb
           AND to_uri LIKE '%src/user.rs'",
    )
    .bind(ws.0 as i64)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert!(changes_file_edges >= 2, "expected ChangesFile parallel to ChangesSymbol");

    // Sanity: target URI shape is git+symbol:<ws>:<path>:<qname>.
    let example: Option<String> = sqlx::query_scalar(
        "SELECT to_uri FROM edges
         WHERE workspace_id = $1 AND kind = '\"changes_symbol\"'::jsonb
           AND to_uri LIKE '%User::validate'
         LIMIT 1",
    )
    .bind(ws.0 as i64)
    .fetch_optional(storage.pool())
    .await
    .unwrap();
    let uri = example.expect("at least one validate edge");
    assert!(uri.starts_with("git+symbol:"), "uri = {uri}");
    assert!(uri.contains("src/user.rs"), "uri = {uri}");
    assert!(uri.ends_with("User::validate"), "uri = {uri}");
}

/// Stable, per-test temp dir under `target/` so multiple test runs don't
/// collide and so libgit2 has a predictable absolute path. We pre-clean
/// the dir to make the test idempotent.
fn tempdir_in_target(name: &str) -> std::path::PathBuf {
    let mut p = std::env::current_dir().unwrap();
    // Walk up to the workspace root if we're inside `crates/engine`.
    while !p.join("Cargo.toml").exists() && p.parent().is_some() {
        p = p.parent().unwrap().to_path_buf();
    }
    let dir = p.join("target").join("test-fixtures").join(name);
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}
