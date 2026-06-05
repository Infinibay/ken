"""Git commit-history co-change mining.

Each commit is treated as a market-basket transaction of the files it
changed. We mine pairwise co-change with support / confidence / lift and
an exponential recency decay, then **subtract the resolved import graph**
so the headline result is the *hidden* logical coupling ken cannot derive
structurally (schema <-> migration, code <-> config, parallel impls).

Two entry points:

* ``ingest_commits`` — incremental `git log` parse into ``cr_commits`` /
  ``cr_commit_files`` (idempotent; tracks the last-seen SHA in ``meta``).
* ``cochange`` — query the mined tables for one file's co-change partners.

The math is deliberately honest: we never smooth a thin signal into
existence. A pair must clear ``min_support`` raw commits and ``lift > 1``
or it is dropped, and the tool returns an empty list rather than guessing.
"""

from __future__ import annotations

import subprocess
import time
from collections import defaultdict
from pathlib import Path

from ken.db import get_meta, set_meta

# Commits touching more than this many files are reformat/vendor-bump/merge
# noise that would couple everything to everything — drop them from mining.
_COMMIT_SIZE_CAP = 30
# Half-life (days) for the exponential recency decay applied to each commit's
# contribution. ~90d means a year-old coupling counts ~6% of a fresh one.
_HALF_LIFE_DAYS = 90.0
_SECONDS_PER_DAY = 86_400.0
# Safety cap on a cold full-history ingest.
_MAX_COMMITS = 20_000

_MARK = "\x01"  # commit-header sentinel; \x01 never appears in paths


# Directories never worth descending into when discovering nested git repos.
_REPO_SCAN_SKIP = {
    "node_modules", ".ken", "dist", "build", "out", "target", "vendor",
    ".venv", "venv", "__pycache__", ".next", ".nuxt", ".git", ".cache",
}


def ingest_commits(
    conn,
    project_root: Path,
    *,
    max_commits: int = _MAX_COMMITS,
    only_path: str | None = None,
) -> dict:
    """Parse new commits from `git log` into the co-change tables.

    The indexed root may itself be a git repo **or** a directory that merely
    *contains* repos (a common workspace layout: ``backend/``, ``frontend/x/``,
    each its own repo). We therefore ingest every repo found under the root and
    prefix each repo's changed-file paths with the repo's directory, so they
    match the project-root-relative paths stored in ``ci_files``.

    ``only_path`` restricts ingestion to the single repo that *contains* that
    file — what ``cochange`` passes, so a query touches only the relevant repo
    instead of scanning the whole workspace. Per-repo incremental state is
    tracked in ``meta`` so repeated calls stay cheap.
    """
    root = project_root.resolve()
    if only_path:
        rel = _repo_for_path(root, only_path)
        repos = [rel] if rel is not None else []
    else:
        repos = _discover_repos(root)

    total = 0
    per_repo: dict[str, int] = {}
    last_sha: str | None = None
    for rel in repos:
        repo_dir = root if rel == "" else root / rel
        # Root repo keeps the legacy bare meta key + bare sha for back-compat;
        # sub-repos namespace both so identical SHAs across repos never collide.
        meta_key = "cochange_last_sha" if rel == "" else f"cochange_last_sha:{rel}"
        prefix = "" if rel == "" else rel + "/"
        repo_last = get_meta(conn, meta_key)
        rng = f"{repo_last}..HEAD" if repo_last else "HEAD"
        commits = _git_log(repo_dir, rng, max_commits=max_commits)
        if not commits:
            continue
        inserted = 0
        # `git log` is newest-first; insert oldest-first so the stored last SHA
        # is always the newest ingested even if we hit the cap.
        with conn:
            for commit in reversed(commits):
                files = [prefix + p for p in commit["files"]]
                sha_key = commit["sha"] if rel == "" else f"{rel}{_MARK}{commit['sha']}"
                cur = conn.execute(
                    "INSERT OR IGNORE INTO cr_commits"
                    "(sha, committed_at, author, subject, n_files) VALUES (?, ?, ?, ?, ?)",
                    (sha_key, commit["ts"], commit["author"], commit["subject"], len(files)),
                )
                if cur.rowcount == 0:
                    continue  # already ingested (e.g. overlapping range)
                commit_id = int(cur.lastrowid)
                if files:
                    conn.executemany(
                        "INSERT INTO cr_commit_files(commit_id, path) VALUES (?, ?)",
                        [(commit_id, p) for p in files],
                    )
                inserted += 1
            set_meta(conn, meta_key, commits[0]["sha"])
        if rel == "":
            last_sha = commits[0]["sha"]
        total += inserted
        per_repo[rel or "."] = inserted

    return {"ok": True, "ingested": total, "repos": len(per_repo),
            "per_repo": per_repo, "last_sha": last_sha}


def _discover_repos(root: Path, *, max_depth: int = 3) -> list[str]:
    """Project-root-relative dirs that are git repos ("" = the root itself).

    Walks a few levels down, pruning build/vendor noise, and does not descend
    into a repo once found (a workspace of sibling repos is the target shape).
    """
    repos: list[str] = []

    def walk(d: Path, depth: int) -> None:
        if _has_git(d):
            repos.append("" if d == root else d.relative_to(root).as_posix())
            return  # a repo's own subtree is one unit; don't recurse in
        if depth >= max_depth:
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            if child.name in _REPO_SCAN_SKIP or child.name.startswith("."):
                continue
            walk(child, depth + 1)

    walk(root, 0)
    return repos


def _repo_for_path(root: Path, rel_path: str) -> str | None:
    """The git repo (project-root-relative dir, "" = root) containing *rel_path*.

    Walks up from the file's directory to the root, returning the first
    ancestor holding a ``.git`` entry. None if the path sits in no repo.
    """
    norm = _normalize(rel_path)
    d = (root / norm).resolve().parent
    try:
        d.relative_to(root)
    except ValueError:
        return None
    while True:
        if _has_git(d):
            return "" if d == root else d.relative_to(root).as_posix()
        if d == root:
            return None
        d = d.parent


def _has_git(d: Path) -> bool:
    """Whether *d* holds a ``.git`` entry, tolerant of unreadable dirs."""
    try:
        return (d / ".git").exists()
    except OSError:
        return False


def cochange(
    conn,
    path: str,
    *,
    min_confidence: float = 0.4,
    min_support: int = 3,
    limit: int = 15,
    project_root: Path | None = None,
    auto_ingest: bool = True,
) -> dict:
    """Return files historically changed together with *path*.

    Hidden couplings (no resolved import edge in either direction) are
    flagged and sorted first — that is the signal ken can't get any other
    way. Returns ``{ok, path, total_commits, partners: [...]}``.
    """
    target = _normalize(path)
    if auto_ingest and project_root is not None:
        try:
            # Ingest only the repo that contains the queried file — in a
            # workspace of many repos, scanning all of them per query is waste.
            ingest_commits(conn, project_root, only_path=target)
        except Exception:  # pragma: no cover - ingest is best-effort
            pass

    # Pull every capped commit's file set once. Repos ken targets are small;
    # this stays in memory. (A SQL-only path is a later optimisation.)
    rows = conn.execute(
        """
        SELECT c.id, c.committed_at, f.path
        FROM cr_commits c JOIN cr_commit_files f ON f.commit_id = c.id
        WHERE c.n_files <= ?
        ORDER BY c.id
        """,
        (_COMMIT_SIZE_CAP,),
    ).fetchall()
    if not rows:
        return {"ok": True, "path": target, "total_commits": 0, "partners": [],
                "note": "no commit history ingested"}

    now = time.time()
    commit_files: dict[int, list[str]] = defaultdict(list)
    commit_weight: dict[int, float] = {}
    for r in rows:
        cid = int(r["id"])
        commit_files[cid].append(r["path"])
        if cid not in commit_weight:
            age_days = max(0.0, (now - float(r["committed_at"])) / _SECONDS_PER_DAY)
            commit_weight[cid] = 0.5 ** (age_days / _HALF_LIFE_DAYS)

    # Weighted support per file, weighted co-support per partner, raw co-counts.
    support: dict[str, float] = defaultdict(float)
    total_weight = 0.0
    co_weight: dict[str, float] = defaultdict(float)
    co_count: dict[str, int] = defaultdict(int)
    target_support_raw = 0

    for cid, files in commit_files.items():
        w = commit_weight[cid]
        total_weight += w
        fileset = set(files)
        for f in fileset:
            support[f] += w
        if target in fileset:
            target_support_raw += 1
            for f in fileset:
                if f == target:
                    continue
                co_weight[f] += w
                co_count[f] += 1

    if support.get(target, 0.0) <= 0.0:
        return {"ok": True, "path": target, "total_commits": len(commit_files),
                "partners": [], "note": "target file has no co-change history"}

    import_edges = _import_neighbors(conn, target)
    sup_target = support[target]
    partners: list[dict] = []
    for f, c_count in co_count.items():
        if c_count < min_support:
            continue
        confidence = co_weight[f] / sup_target if sup_target else 0.0
        if confidence < min_confidence:
            continue
        p_f = support[f] / total_weight if total_weight else 0.0
        p_joint = co_weight[f] / total_weight if total_weight else 0.0
        p_target = sup_target / total_weight if total_weight else 0.0
        lift = p_joint / (p_target * p_f) if (p_target and p_f) else 0.0
        if lift <= 1.0:
            continue
        has_edge = f in import_edges
        partners.append(
            {
                "path": f,
                "support": c_count,
                "confidence": round(confidence, 3),
                "lift": round(lift, 2),
                "has_import_edge": has_edge,
                "hidden_coupling": not has_edge,
            }
        )

    # Hidden coupling first, then strongest confidence*lift.
    partners.sort(key=lambda p: (p["has_import_edge"], -(p["confidence"] * p["lift"])))
    return {
        "ok": True,
        "path": target,
        "total_commits": len(commit_files),
        "target_commits": target_support_raw,
        "partners": partners[: max(1, int(limit))],
    }


# --- helpers ----------------------------------------------------------------


def _import_neighbors(conn, path: str) -> set[str]:
    """Files with a resolved import edge to/from *path* (either direction)."""
    row = conn.execute("SELECT id FROM ci_files WHERE path = ?", (path,)).fetchone()
    if row is None:
        return set()
    fid = int(row["id"])
    out: set[str] = set()
    for r in conn.execute(
        """
        SELECT dst.path AS p FROM ci_imports i JOIN ci_files dst ON dst.id = i.to_file_id
        WHERE i.from_file_id = ?
        UNION
        SELECT src.path AS p FROM ci_imports i JOIN ci_files src ON src.id = i.from_file_id
        WHERE i.to_file_id = ?
        """,
        (fid, fid),
    ).fetchall():
        if r["p"]:
            out.add(r["p"])
    return out


def _normalize(path: str) -> str:
    p = Path(path).as_posix()
    return p[2:] if p.startswith("./") else p


def _git_log(root: Path, rng: str, *, max_commits: int) -> list[dict]:
    """Run `git log` and parse commits with their changed-file lists."""
    fmt = f"{_MARK}%H%x1f%ct%x1f%an%x1f%s"
    try:
        proc = subprocess.run(
            [
                "git", "log", rng,
                "--no-merges", "--find-renames", "--no-color",
                f"--max-count={max_commits}",
                f"--pretty=format:{fmt}",
                "--name-only",
            ],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []

    commits: list[dict] = []
    current: dict | None = None
    for line in proc.stdout.splitlines():
        if line.startswith(_MARK):
            if current is not None:
                commits.append(current)
            sha, ts, author, subject = (line[1:].split("\x1f") + ["", "", "", ""])[:4]
            try:
                ts_int = int(ts)
            except ValueError:
                ts_int = 0
            current = {"sha": sha, "ts": ts_int, "author": author,
                       "subject": subject, "files": []}
        elif line.strip() and current is not None:
            current["files"].append(_normalize(line.strip()))
    if current is not None:
        commits.append(current)
    return commits
