"""Read complete skill bundles from the installed Python package."""

from __future__ import annotations

import re
from importlib.resources import files
from importlib.resources.abc import Traversable

# These skills author queries. Other skills use higher-level tools and do not
# need to load the language manual. Each installed bundle remains self-contained.
_KQL_AUTHORS = frozenset(
    {"ken-find-code-patterns", "ken-investigate-bug", "ken-prevent-regressions"}
)


def bundled_skills() -> dict[str, dict[str, bytes]]:
    """Return skill names and their relative resource files, including references."""
    bundles = {}
    for folder in sorted(
        files("ken.skills").joinpath("bundled").iterdir(), key=lambda p: p.name
    ):
        if not folder.is_dir():
            continue
        if not re.fullmatch(r"ken-[a-z0-9]+(?:-[a-z0-9]+)*", folder.name):
            raise ValueError(f"Invalid bundled skill name: {folder.name}")
        resources = dict(_read_files(folder))
        if "SKILL.md" not in resources:
            raise ValueError(f"Missing SKILL.md in bundled skill: {folder.name}")
        if folder.name in _KQL_AUTHORS:
            for name, content in _read_files(
                files("ken.skills").joinpath("references/kql2"), "references/kql2/"
            ):
                if name in resources:
                    raise ValueError(f"Duplicate shared skill resource: {name}")
                resources[name] = content
        bundles[folder.name] = resources
    if not bundles:
        raise ValueError("The Ken package contains no bundled skills")
    return bundles


def _read_files(folder: Traversable, prefix: str = ""):
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        name = prefix + entry.name
        if entry.is_dir():
            yield from _read_files(entry, name + "/")
        elif entry.is_file():
            yield name, entry.read_bytes()
