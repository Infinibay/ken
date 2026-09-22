"""Select applicable contracts without silently narrowing their proof scope."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess

from .model import relative


def overlaps(first: str, second: str) -> bool:
    a, b = PurePosixPath(relative(first)), PurePosixPath(relative(second))
    return a.is_relative_to(b) or b.is_relative_to(a)


def changed_paths(root: Path) -> list[str]:
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, timeout=5
        )
        if result.returncode:
            raise ValueError("changes scope requires a Git worktree with HEAD")
        return result.stdout.decode("utf-8", errors="strict").split("\0")

    # --no-renames includes both the deleted and added identity of a rename.
    return sorted(
        {
            p
            for p in [
                *git("diff", "HEAD", "--name-only", "--no-renames", "-z", "--"),
                *git("ls-files", "--others", "--exclude-standard", "-z"),
            ]
            if p and not {".ken", ".git"}.intersection(PurePosixPath(p).parts)
        }
    )


def affected(
    root: Path,
    records: list[dict],
    changed: list[str],
    *,
    seconds: float = 1.0,
    include_deleted: bool = True,
) -> tuple[set[str], dict]:
    """Include import dependents; missing change events may have erased an edge.

    A path filter is not a deletion event; its caller disables include_deleted.
    """
    import time
    from .snapshot import capture
    from ken.inspection.imports import dependencies

    started = time.monotonic()
    selected: set[str] = set()
    evidence: dict[str, dict] = {}
    for record in records:
        rule = record["definition"]
        if any(overlaps(rule["path"], p) for p in changed):
            selected.add(rule["id"])
            evidence[rule["id"]] = {"basis": "declared_scope"}
            continue
        try:
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError("selection budget exhausted")
            snapshot = capture(root, rule["path"], seconds=remaining)
            deps = dependencies(
                root,
                snapshot,
                seconds=max(0.001, seconds - (time.monotonic() - started)),
            )
            hits = [
                p for p, _ in deps["manifest"] if any(overlaps(p, c) for c in changed)
            ]
            # Deletions can erase an edge before selection. A missing changed
            # source cannot safely exclude a previously dependent rule.
            missing = [
                p for p in changed if include_deleted and not (root / p).exists()
            ]
            if hits or missing or deps.get("issues"):
                selected.add(rule["id"])
                evidence[rule["id"]] = {
                    "basis": "import_dependency" if hits else "conservative",
                    "paths": hits or missing,
                    "issues": deps.get("issues", []),
                }
        except (OSError, ValueError) as exc:
            selected.add(rule["id"])
            evidence[rule["id"]] = {"basis": "conservative", "reason": str(exc)}
    return selected, evidence
