//! libgit2 walker for the git-history ingest path. Read-only: opens a local
//! repo via `git2`, traverses commits newest-first within a `since` window,
//! and yields a `CommitData` per kept commit. No network.
//!
//! Filters here are **shape filters** (merge, bot, whitespace-only) — they
//! cull commits that have no analytical value before we pay the cost of
//! embedding their messages. Semantic filters (revert detection, branch
//! aggregation) live in later phases (see `docs/11-git-history-plan.md`).

use std::path::{Path, PathBuf};

use ahash::{AHashMap, AHashSet};
use git2::{Diff, DiffFindOptions, DiffOptions, Patch, Repository, Sort};

use super::{FileChange, FileStatus, HunkRange, IngestGitConfig};

/// Per-commit data the walker emits to the ingest pipeline. Decoupled from
/// `git2::Commit<'_>` so the pipeline can run async tasks against this
/// data without being tied to libgit2's borrow lifetimes.
#[derive(Debug, Clone)]
pub struct CommitData {
    pub sha: String,
    /// First line of the commit message (or full message if it's one line).
    pub summary: String,
    /// Full commit message body.
    pub message: String,
    pub author_name: String,
    pub author_email: String,
    pub committer_time_seconds: i64,
    /// True if this commit has more than one parent (i.e., is a merge).
    /// Phase-0 still emits these so callers can choose to keep merges as
    /// branch-summary records once branch aggregation lands (Phase 1).
    pub is_merge: bool,
    /// True if the only changes are whitespace / empty lines per
    /// `is_whitespace_only`.
    pub is_whitespace_only: bool,
    pub files: Vec<FileChange>,
    /// Phase 1.4: for merge commits in `branch_as_session` mode, the union
    /// of file changes across every branch commit (commits unique to the
    /// merge's second parent). Per-path status is the *latest* status the
    /// branch produced — i.e., what happened to the file by the time the
    /// branch landed. The persistence layer uses this for the merge's
    /// synthetic session so the session represents the whole feature.
    /// `None` for non-merge commits or when `branch_as_session` is off.
    pub aggregated_files: Option<Vec<FileChange>>,
    /// SHA of the merge whose synthetic session subsumes this commit. When
    /// `Some`, the persistence layer emits a Document but skips synthetic-
    /// session creation — the merge's session covers it.
    pub subsumed_by_merge: Option<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum WalkError {
    #[error("git error: {0}")]
    Git(#[from] git2::Error),
    #[error("repo path is not a directory: {0}")]
    NotARepo(PathBuf),
}

pub type WalkResult<T> = Result<T, WalkError>;

/// Phase 1.5: blob → symbol-table cache. The *symbol table* (all symbols
/// in the file with their line ranges) only depends on the blob content,
/// so we can memoize it. The hunk-to-symbol overlap is recomputed fresh
/// per commit (O(symbols × hunks), cheap).
///
/// Same blob content (= same OID, by git's hashing) ⇒ same symbol table,
/// by definition. Avoids re-parsing files that didn't change across
/// commits, the dominant cost in a large-history walk.
///
/// FIFO eviction with a cap. LRU is overkill — we mostly walk
/// time-ordered, and recently-touched files dominate hits regardless.
struct SymbolCache {
    parsed: AHashMap<git2::Oid, Vec<super::symbols::CachedSymbol>>,
    order: std::collections::VecDeque<git2::Oid>,
    cap: usize,
}

impl SymbolCache {
    fn new(cap: usize) -> Self {
        Self {
            parsed: AHashMap::new(),
            order: std::collections::VecDeque::new(),
            cap,
        }
    }

    /// Resolve `hunks` against the symbol table of the file at `blob_oid`,
    /// parsing it on cache miss. Returns the dedup'd qualified names that
    /// any hunk fell inside (or overlapped, if no full containment exists).
    fn resolve(
        &mut self,
        repo: &Repository,
        blob_oid: git2::Oid,
        path: &str,
        hunks: &[HunkRange],
    ) -> Vec<String> {
        if !self.parsed.contains_key(&blob_oid) {
            let blob = match repo.find_blob(blob_oid) {
                Ok(b) => b,
                Err(_) => {
                    // Memoize "this blob has no symbols" so we don't retry.
                    self.parsed.insert(blob_oid, Vec::new());
                    self.order.push_back(blob_oid);
                    return Vec::new();
                }
            };
            let table = super::symbols::parse_symbol_table(path, blob.content());
            self.parsed.insert(blob_oid, table);
            self.order.push_back(blob_oid);
            if self.parsed.len() > self.cap
                && let Some(oldest) = self.order.pop_front()
            {
                self.parsed.remove(&oldest);
            }
        }
        let table = self.parsed.get(&blob_oid).expect("just inserted");
        super::symbols::overlap_qnames(table, hunks)
    }
}

/// Walk a repo's default branch (or whatever ref the config points to)
/// newest-first. Yields a `CommitData` for every commit kept by the
/// `IngestGitConfig` filters. Caller iterates and persists.
pub struct CommitWalker<'a> {
    cfg: &'a IngestGitConfig,
}

impl<'a> CommitWalker<'a> {
    pub fn new(cfg: &'a IngestGitConfig) -> Self {
        Self { cfg }
    }

    /// Open the repo and emit `CommitData`s for kept commits, newest-first.
    /// The closure approach (vs an iterator) avoids leaking `Repository`
    /// borrow lifetimes across async boundaries — a `Repository` doesn't
    /// like crossing `await` points.
    pub fn for_each<F>(&self, mut f: F) -> WalkResult<WalkStats>
    where
        F: FnMut(CommitData) -> std::ops::ControlFlow<()>,
    {
        let path: &Path = self.cfg.repo_path.as_ref();
        if !path.is_dir() {
            return Err(WalkError::NotARepo(path.to_path_buf()));
        }
        let repo = Repository::open(path)?;
        let head_oid = resolve_head_oid(&repo, self.cfg.branch.as_deref())?;

        let mut walk = repo.revwalk()?;
        walk.set_sorting(Sort::TIME)?;
        walk.push(head_oid)?;

        let mut stats = WalkStats::default();
        let cutoff = self
            .cfg
            .since_seconds_unix
            .map(|s| s as i64);

        // Phase 1.4: track which OIDs are subsumed by a merge we've
        // already emitted (we walk newest-first, so a merge always comes
        // before its branch members). Membership flags `subsumed_by_merge`
        // on the branch commits' CommitData.
        let mut subsumed: AHashMap<git2::Oid, String> = AHashMap::new();

        // Phase 1.5: blob → symbol-table cache. Bounded at 4096 entries,
        // FIFO eviction. Empirically, a 200k-commit repo touches ~100k
        // unique code-file blobs; the cache provides the bulk of the
        // speedup well before saturation. Larger caps are fine memory-
        // wise (CachedSymbol is small) but diminishing returns.
        let mut symbol_cache = SymbolCache::new(4096);

        for oid_res in walk {
            let oid = match oid_res {
                Ok(o) => o,
                Err(_) => {
                    stats.skipped_walk_errors += 1;
                    continue;
                }
            };
            let commit = match repo.find_commit(oid) {
                Ok(c) => c,
                Err(_) => {
                    stats.skipped_walk_errors += 1;
                    continue;
                }
            };

            let when = commit.time().seconds();
            if let Some(c) = cutoff
                && when < c
            {
                break; // commits are time-sorted, nothing older matters
            }
            stats.visited += 1;

            let is_merge = commit.parent_count() > 1;
            // Phase-0 path: when branch_as_session is OFF, merges are
            // skipped (their own diff is mechanical). With branch
            // aggregation ON, the merge is the session anchor — we keep it.
            if self.cfg.skip_merges && is_merge && !self.cfg.branch_as_session {
                stats.skipped_merge += 1;
                continue;
            }

            let author = commit.author();
            let email = author.email().unwrap_or("").to_string();
            let name = author.name().unwrap_or("").to_string();

            if is_bot_email(&email) {
                stats.skipped_bot += 1;
                continue;
            }

            let mut files = match diff_files_for_commit(&repo, &commit) {
                Ok(f) => f,
                Err(_) => {
                    stats.skipped_diff_errors += 1;
                    continue;
                }
            };
            // Phase 1.5: resolve hunks → enclosing code symbols per file.
            // Blob OID is the cache key; the symbol table is parsed once
            // per blob and reused across every commit that touches it.
            for f in files.iter_mut() {
                if f.hunks.is_empty() {
                    continue;
                }
                let Some(blob_oid_str) = f.new_blob_oid.as_deref() else { continue };
                let Ok(blob_oid) = git2::Oid::from_str(blob_oid_str) else { continue };
                f.symbols = symbol_cache.resolve(&repo, blob_oid, &f.path, &f.hunks);
            }
            let is_whitespace_only = match whitespace_only_for_commit(&repo, &commit) {
                Ok(b) => b,
                Err(_) => false,
            };

            if self.cfg.skip_whitespace_only && is_whitespace_only {
                stats.skipped_whitespace += 1;
                continue;
            }

            let message = commit.message().unwrap_or("").to_string();
            let summary = commit.summary().unwrap_or("").to_string();

            // Phase 1.4 branch aggregation. Two cases:
            //   * `is_merge` && `branch_as_session`: enumerate P1..P2,
            //     mark members as subsumed, and aggregate file changes
            //     across the branch into `aggregated_files`.
            //   * otherwise: leave both fields default.
            let mut aggregated_files: Option<Vec<FileChange>> = None;
            if is_merge && self.cfg.branch_as_session {
                if let Ok(branch_files) = aggregate_branch_changes(&repo, &commit, &mut subsumed)
                {
                    aggregated_files = Some(branch_files);
                }
            }
            let subsumed_by_merge = subsumed.get(&oid).cloned();

            let data = CommitData {
                sha: oid.to_string(),
                summary,
                message,
                author_name: name,
                author_email: email,
                committer_time_seconds: when,
                is_merge,
                is_whitespace_only,
                files,
                aggregated_files,
                subsumed_by_merge,
            };

            stats.kept += 1;
            if matches!(f(data), std::ops::ControlFlow::Break(_)) {
                break;
            }
        }
        Ok(stats)
    }
}

fn resolve_head_oid(repo: &Repository, branch_override: Option<&str>) -> Result<git2::Oid, git2::Error> {
    if let Some(b) = branch_override {
        // Try local branch first; fall back to remote-tracking branch (origin/<b>).
        if let Ok(reference) = repo.find_branch(b, git2::BranchType::Local) {
            return reference.get().peel_to_commit().map(|c| c.id());
        }
        if let Ok(reference) = repo.find_branch(&format!("origin/{b}"), git2::BranchType::Remote) {
            return reference.get().peel_to_commit().map(|c| c.id());
        }
        // Direct ref name lookup as last resort.
        return repo.revparse_single(b).map(|o| o.id());
    }
    let head = repo.head()?;
    head.peel_to_commit().map(|c| c.id())
}

/// Compute the file-change list for a commit (extracted helper so the
/// branch-aggregation path can reuse it). Diffs against the first parent
/// (mainline). Root commits diff against an empty tree.
///
/// Phase 1.5: also populates `hunks` and `new_blob_oid` on each
/// `FileChange` via `Patch::from_diff`. Hunks are skipped for `Removed`
/// files (no post-state).
fn diff_files_for_commit(
    repo: &Repository,
    commit: &git2::Commit<'_>,
) -> Result<Vec<FileChange>, git2::Error> {
    let parent_tree = if commit.parent_count() > 0 {
        commit.parent(0).ok().and_then(|p| p.tree().ok())
    } else {
        None
    };
    let this_tree = commit.tree()?;
    let mut opts = DiffOptions::new();
    // `context_lines(0)` is critical for Phase 1.5: with default context
    // (3 lines) a hunk that touches `validate`'s body can spill into
    // `name`'s opening brace and the symbol-overlap logic flags both.
    // Zero context produces hunks that match exactly the changed lines.
    opts.ignore_filemode(true).context_lines(0);
    let mut diff = repo.diff_tree_to_tree(parent_tree.as_ref(), Some(&this_tree), Some(&mut opts))?;
    let mut find_opts = DiffFindOptions::new();
    find_opts.renames(true).renames_from_rewrites(true);
    let _ = diff.find_similar(Some(&mut find_opts));
    let mut files = collect_file_changes(&diff);
    // Phase 1.5 enrichment: walk patches in delta order to populate
    // hunks per file. The delta order from `diff.deltas()` matches the
    // index passed to `Patch::from_diff`. We only iterate up to the
    // file count we kept (deltas we skipped — Untracked/Unmodified — are
    // excluded from `files` but counted by libgit2's index, so we re-walk
    // by name match instead of index to stay robust).
    let by_path: AHashMap<String, usize> = files
        .iter()
        .enumerate()
        .map(|(i, f)| (f.path.clone(), i))
        .collect();
    for delta_idx in 0..diff.deltas().count() {
        let Ok(Some(patch)) = Patch::from_diff(&diff, delta_idx) else { continue };
        let delta = patch.delta();
        // Match the patch back to our `files` entry by path. `Removed`
        // deltas use old-file path; everything else uses new-file path.
        let lookup_path = match delta.status() {
            git2::Delta::Deleted => delta.old_file().path().map(|p| p.to_string_lossy().into_owned()),
            _ => delta.new_file().path().map(|p| p.to_string_lossy().into_owned()),
        };
        let Some(path) = lookup_path else { continue };
        let Some(&i) = by_path.get(&path) else { continue };
        // new_blob_oid: skip for deletions (no post-state blob).
        if !matches!(files[i].status, FileStatus::Removed) {
            let nb = delta.new_file().id();
            if !nb.is_zero() {
                files[i].new_blob_oid = Some(nb.to_string());
            }
            // Hunks: walk the patch.
            let n = patch.num_hunks();
            for h_idx in 0..n {
                if let Ok((hunk, _lines)) = patch.hunk(h_idx) {
                    files[i].hunks.push(HunkRange {
                        new_start: hunk.new_start(),
                        new_lines: hunk.new_lines(),
                    });
                }
            }
        }
    }
    Ok(files)
}

fn whitespace_only_for_commit(
    repo: &Repository,
    commit: &git2::Commit<'_>,
) -> Result<bool, git2::Error> {
    let parent_tree = if commit.parent_count() > 0 {
        commit.parent(0).ok().and_then(|p| p.tree().ok())
    } else {
        None
    };
    let this_tree = commit.tree()?;
    let mut opts = DiffOptions::new();
    opts.ignore_filemode(true);
    let diff = repo.diff_tree_to_tree(parent_tree.as_ref(), Some(&this_tree), Some(&mut opts))?;
    Ok(is_diff_whitespace_only(&diff))
}

/// For a merge commit M with parents P1 (mainline) and P2 (branch tip),
/// enumerate commits in `P1..P2` (newest-first), mark each as subsumed by
/// M's sha, and return the *aggregated* file changes — one entry per path
/// touched in any branch commit, with status = the latest commit's status
/// for that path (i.e., what happened to the file by the time the branch
/// landed).
fn aggregate_branch_changes(
    repo: &Repository,
    merge: &git2::Commit<'_>,
    subsumed: &mut AHashMap<git2::Oid, String>,
) -> Result<Vec<FileChange>, git2::Error> {
    if merge.parent_count() < 2 {
        return Ok(Vec::new());
    }
    let p1 = merge.parent(0)?.id();
    let p2 = merge.parent(1)?.id();
    let merge_sha = merge.id().to_string();

    let mut walk = repo.revwalk()?;
    walk.set_sorting(Sort::TIME)?;
    walk.push(p2)?;
    walk.hide(p1)?;

    // Collect the branch commits in time order (oldest first).
    let mut branch_commits: Vec<git2::Commit<'_>> = Vec::new();
    let mut seen: AHashSet<git2::Oid> = AHashSet::new();
    for oid_res in walk {
        let Ok(oid) = oid_res else { continue };
        if !seen.insert(oid) {
            continue;
        }
        if let Ok(c) = repo.find_commit(oid) {
            branch_commits.push(c);
        }
    }
    // Mark each branch commit as subsumed by the merge — the main walker
    // loop will see this when it encounters them and skip session creation.
    for c in &branch_commits {
        subsumed.entry(c.id()).or_insert_with(|| merge_sha.clone());
    }
    branch_commits.sort_by_key(|c| c.time().seconds());

    // Aggregate file changes per path. Latest status wins.
    let mut agg: AHashMap<String, (FileStatus, Option<String>)> = AHashMap::new();
    for c in &branch_commits {
        let files = match diff_files_for_commit(repo, c) {
            Ok(f) => f,
            Err(_) => continue,
        };
        for f in files {
            agg.insert(f.path, (f.status, f.old_path));
        }
    }
    Ok(agg
        .into_iter()
        .map(|(path, (status, old_path))| FileChange {
            path,
            status,
            old_path,
            // Aggregated branch summaries don't carry per-hunk info — we
            // intentionally lose that resolution at the merge level. The
            // branch members' own Documents still emit per-hunk
            // `ChangesSymbol` edges.
            hunks: Vec::new(),
            new_blob_oid: None,
            symbols: Vec::new(),
        })
        .collect())
}

fn collect_file_changes(diff: &Diff<'_>) -> Vec<FileChange> {
    let mut out: Vec<FileChange> = Vec::new();
    diff.foreach(
        &mut |delta, _| {
            let status = match delta.status() {
                git2::Delta::Added => FileStatus::Added,
                git2::Delta::Deleted => FileStatus::Removed,
                git2::Delta::Modified => FileStatus::Modified,
                git2::Delta::Renamed => FileStatus::Renamed,
                git2::Delta::Copied => FileStatus::Modified,
                _ => return true, // skip Untracked/Unmodified/etc.
            };
            let new_path = delta
                .new_file()
                .path()
                .map(|p| p.to_string_lossy().into_owned());
            let old_path = delta
                .old_file()
                .path()
                .map(|p| p.to_string_lossy().into_owned());
            // For renames, "path" is the new path; old_path captured separately.
            // For deletions, prefer the old path (new path is empty for git2).
            let path = match status {
                FileStatus::Removed => old_path.clone().unwrap_or_default(),
                _ => new_path.clone().unwrap_or_default(),
            };
            if path.is_empty() {
                return true;
            }
            out.push(FileChange {
                path,
                status,
                old_path: if matches!(status, FileStatus::Renamed) { old_path } else { None },
                hunks: Vec::new(),
                new_blob_oid: None,
                symbols: Vec::new(),
            });
            true
        },
        None,
        None,
        None,
    )
    .ok();
    out
}

/// Returns true if every line in the diff is empty or whitespace-only — i.e.
/// the commit only adjusts indentation / trailing whitespace / blank lines.
/// Bins file deletions and binary diffs as "not whitespace-only" so we don't
/// suppress meaningful changes. Walks the diff line-by-line; bounded by total
/// patch size which is already memory-resident in libgit2.
fn is_diff_whitespace_only(diff: &Diff<'_>) -> bool {
    let mut all_ws = true;
    let mut any = false;
    let _ = diff.foreach(
        &mut |_, _| true,
        None,
        None,
        Some(&mut |_, _, line| {
            if !all_ws {
                return true;
            }
            match line.origin() {
                '+' | '-' => {
                    any = true;
                    if let Ok(s) = std::str::from_utf8(line.content()) {
                        if !s.chars().all(|c| c.is_whitespace()) {
                            all_ws = false;
                        }
                    } else {
                        // binary diff — not whitespace-only
                        all_ws = false;
                    }
                }
                _ => {}
            }
            true
        }),
    );
    any && all_ws
}

/// Heuristic: treat as a bot if the email matches one of the well-known
/// bot patterns. Conservative — if we get false negatives, the caller can
/// pass an explicit allowlist via `IngestGitConfig::bot_email_overrides`.
pub(super) fn is_bot_email(email: &str) -> bool {
    let lower = email.to_ascii_lowercase();
    if lower.is_empty() {
        return false;
    }
    if lower.ends_with("[bot]@users.noreply.github.com") {
        return true;
    }
    if lower.ends_with("@users.noreply.github.com") && lower.contains("[bot]") {
        return true;
    }
    let names = [
        "dependabot",
        "renovate-bot",
        "renovate[bot]",
        "github-actions",
        "github-actions[bot]",
        "noreply@github.com",
        "noreply@anthropic.com",
        "snyk-bot",
        "imgbot",
    ];
    names.iter().any(|n| lower.contains(n))
}

/// Aggregate counters returned by `for_each`. Useful for CLI output and
/// test assertions.
#[derive(Debug, Default, Clone, Copy)]
pub struct WalkStats {
    pub visited: u64,
    pub kept: u64,
    pub skipped_merge: u64,
    pub skipped_bot: u64,
    pub skipped_whitespace: u64,
    pub skipped_walk_errors: u64,
    pub skipped_diff_errors: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bot_email_detection() {
        assert!(is_bot_email("dependabot[bot]@users.noreply.github.com"));
        assert!(is_bot_email("renovate-bot@example.com"));
        assert!(is_bot_email("49699333+dependabot[bot]@users.noreply.github.com"));
        assert!(is_bot_email("github-actions@github.com"));
        assert!(!is_bot_email("alice@example.com"));
        assert!(!is_bot_email(""));
    }
}
