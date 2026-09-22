"""Reconcile bundled skills with the project's selected assistant hosts."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ken.skills.catalog import bundled_skills
from ken.skills.ownership import SkillOwnership, digest, local_path, write_atomic


@dataclass
class SkillChanges:
    installed: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    preserved: dict[str, str] = field(default_factory=dict)

    def report(self, *, verbose: bool, root: Path | None = None) -> None:
        if verbose:
            print(
                f"[skills] installed={len(self.installed)}, updated={len(self.updated)}, "
                f"unchanged={len(self.unchanged)}, removed={len(self.removed)}"
            )
            destinations = Counter(
                str(Path(target).parent)
                for target in self.installed + self.updated + self.unchanged
            )
            for destination, count in sorted(destinations.items()):
                path = root / destination if root is not None else Path(destination)
                print(f"[skills] {count} skills at {path}")
        for target, reason in self.preserved.items():
            print(f"[skills] preserved {target}: {reason}", file=sys.stderr)


def skill_destinations(
    *, claude: bool, codex: bool, opencode: bool, deepseek: bool = False
) -> tuple[str, ...]:
    """OpenCode also reads Claude and shared agent skills; avoid a third copy."""
    destinations = []
    if claude:
        destinations.append(".claude/skills")
    if codex:
        destinations.append(".agents/skills")
    if opencode and not destinations:
        destinations.append(".opencode/skills")
    if deepseek and not codex:
        destinations.append(".dsh/skills")
    return tuple(destinations)


def install_skills(
    root: Path,
    *,
    claude: bool = False,
    codex: bool = False,
    opencode: bool = False,
    deepseek: bool = False,
) -> SkillChanges:
    """Install or update selected hosts' skills, preserving entire edited bundles."""
    result = SkillChanges()
    destinations = skill_destinations(
        claude=claude, codex=codex, opencode=opencode, deepseek=deepseek
    )
    if not destinations:
        return result
    ownership = SkillOwnership.load(root.resolve())
    bundles = bundled_skills()
    for destination in destinations:
        for name, resources in bundles.items():
            target = f"{destination}/{name}"
            reason = ownership.check(target, resources)
            if reason:
                result.preserved[target] = reason
                continue
            previous = ownership.skills.get(target)
            changed = False
            for resource, content in resources.items():
                path = local_path(ownership.root, target + "/" + resource)
                if not path.is_file() or path.read_bytes() != content:
                    write_atomic(path, content)
                    changed = True
            for obsolete in set(previous or {}) - set(resources):
                path = local_path(ownership.root, target + "/" + obsolete)
                if path.exists():
                    path.unlink()
                    _prune_empty(path.parent, ownership.root / target)
                    changed = True
            ownership.skills[target] = {
                name: digest(content) for name, content in resources.items()
            }
            ownership.save()
            if previous is None:
                result.installed.append(target)
            elif changed:
                result.updated.append(target)
            else:
                result.unchanged.append(target)
    return result


def uninstall_skills(root: Path) -> SkillChanges:
    """Remove unchanged owned resources; keep edited bundles and all extra files."""
    result = SkillChanges()
    ownership = SkillOwnership.load(root.resolve())
    for target, resources in list(ownership.skills.items()):
        reason = ownership.check(target, {})
        if reason:
            result.preserved[target] = reason
            continue
        for resource in resources:
            path = local_path(ownership.root, target + "/" + resource)
            path.unlink(missing_ok=True)
            _prune_empty(path.parent, ownership.root / target)
        del ownership.skills[target]
        ownership.save()
        result.removed.append(target)
    return result


def _prune_empty(path: Path, boundary: Path) -> None:
    """Prune resource directories and the skill folder, never its host directory."""
    while path.is_relative_to(boundary):
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent
