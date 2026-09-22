"""Track installed skill resources without adopting or overwriting user files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SKILL_ROOTS = (".claude/skills", ".agents/skills", ".opencode/skills", ".dsh/skills")
MANIFEST = ".ken/installed-skills.json"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def relative_parts(value: str) -> tuple[str, ...]:
    """Accept canonical relative resource paths only."""
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in (".", "..") for part in path.parts)
        or "\\" in value
    ):
        raise ValueError(f"Invalid skill resource path: {value!r}")
    return path.parts


def local_path(root: Path, relative: str) -> Path:
    """Refuse symlinks anywhere along a managed path, including the leaf."""
    path = root
    parts = relative_parts(relative)
    for index, part in enumerate(parts):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Skill path is a symlink: {relative}")
        if index < len(parts) - 1 and path.exists() and not path.is_dir():
            raise ValueError(f"Skill parent is not a directory: {relative}")
    return path


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass
class SkillOwnership:
    """Last installed hashes, grouped by skill so local edits preserve the bundle."""

    root: Path
    skills: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> SkillOwnership:
        manifest = local_path(root, MANIFEST)
        if not manifest.exists():
            return cls(root)
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError("unsupported manifest version")
            skills = value["skills"]
            if not isinstance(skills, dict):
                raise TypeError("skills must be an object")
            for target, resources in skills.items():
                cls.validate_target(target)
                if not isinstance(resources, dict) or "SKILL.md" not in resources:
                    raise ValueError("skill resources must include SKILL.md")
                for name, checksum in resources.items():
                    relative_parts(name)
                    if not isinstance(checksum, str) or not re.fullmatch(
                        r"[0-9a-f]{64}", checksum
                    ):
                        raise ValueError("invalid resource checksum")
            return cls(root, skills)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid {MANIFEST}: {exc}") from exc

    @staticmethod
    def validate_target(target: str) -> None:
        parts = relative_parts(target)
        if (
            len(parts) != 3
            or "/".join(parts[:2]) not in SKILL_ROOTS
            or not re.fullmatch(r"ken-[a-z0-9]+(?:-[a-z0-9]+)*", parts[2])
        ):
            raise ValueError(f"Invalid managed skill location: {target}")

    def save(self) -> None:
        path = local_path(self.root, MANIFEST)
        if self.skills:
            content = json.dumps(
                {"version": 1, "skills": self.skills}, indent=2, sort_keys=True
            )
            write_atomic(path, (content + "\n").encode())
        else:
            path.unlink(missing_ok=True)

    def check(self, target: str, desired: dict[str, bytes]) -> str | None:
        """Return a reason to preserve the whole skill, or allow reconciliation."""
        try:
            directory = local_path(self.root, target)
            previous = self.skills.get(target)
            if directory.exists() and previous is None:
                return "existing skill is not managed by Ken"
            if directory.exists() and not directory.is_dir():
                return "skill location is not a directory"
            for name in set(previous or {}) | set(desired):
                path = local_path(self.root, target + "/" + name)
                if not path.exists():
                    continue
                if previous is None or name not in previous:
                    return f"existing resource is not managed by Ken: {name}"
                if not path.is_file() or digest(path.read_bytes()) != previous[name]:
                    return f"locally modified resource: {name}"
        except (ValueError, OSError) as exc:
            return str(exc)
        return None
