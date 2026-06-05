"""Config-aware import resolution for JS/TS projects.

Relative imports resolve structurally, but real TS/JS codebases lean on tooling
config that ken must read to resolve the rest:

* ``tsconfig.json`` / ``jsconfig.json`` — ``compilerOptions.baseUrl`` +
  ``paths`` aliases (``@/*`` -> ``src/*``, ``@services/*`` -> ``app/services/*``).
* ``package.json`` — workspace package ``name`` so a bare ``@scope/pkg`` import
  resolves into that package's directory.

Configs are hierarchical: a monorepo has one per sub-package, so each source
file is governed by the **nearest** config walking up the tree, not the root.
We index every such config (recursively) and pick the deepest one whose
directory contains the importing file.

tsconfig files are JSONC (comments + trailing commas), so we strip those before
parsing, and follow a single ``extends`` level to inherit ``paths``/``baseUrl``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments (string-aware) and trailing commas."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    esc = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return _TRAILING_COMMA.sub(r"\1", "".join(out))


def _norm_join(base: str, rel: str) -> str:
    """Join *rel* onto directory *base*, collapsing . and .. (posix)."""
    parts = [p for p in base.split("/") if p] if base else []
    for seg in rel.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _load_jsonc(project_root: Path, rel: str) -> dict | None:
    try:
        text = (project_root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        return json.loads(_strip_jsonc(text))
    except (json.JSONDecodeError, ValueError):
        return None


class AliasResolver:
    """Resolves non-relative JS/TS imports via tsconfig paths + workspace names."""

    def __init__(self, configs: list[dict], packages: dict[str, str], files_set: set[str]):
        # Nearest-first: deeper config directories take precedence.
        self.configs = sorted(configs, key=lambda c: len(c["dir"]), reverse=True)
        self.packages = packages
        self.files_set = files_set

    def resolve(self, module: str, source_path: str, match_fn) -> str | None:
        src_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
        for cfg in self.configs:
            cdir = cfg["dir"]
            if cdir and not (src_dir == cdir or src_dir.startswith(cdir + "/")):
                continue
            for pattern, targets in cfg["paths"].items():
                hit = self._match_alias(pattern, targets, module, cfg["base"], match_fn)
                if hit:
                    return hit
        # Workspace package import (bare `@scope/pkg` or `pkg/subpath`).
        for name, pkg_dir in self.packages.items():
            if module == name or module.startswith(name + "/"):
                sub = module[len(name):].lstrip("/")
                base = _norm_join(pkg_dir, sub) if sub else pkg_dir
                hit = match_fn(base, self.files_set)
                if hit:
                    return hit
        return None

    def is_internal_shape(self, module: str, source_path: str) -> bool:
        """True if *module* matches a tsconfig path alias or a workspace package
        name — i.e. it is *meant* to resolve internally, even if the target file
        is missing. Used to tell a resolution gap apart from an external dep."""
        src_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
        for cfg in self.configs:
            cdir = cfg["dir"]
            if cdir and not (src_dir == cdir or src_dir.startswith(cdir + "/")):
                continue
            for pattern in cfg["paths"]:
                if pattern.endswith("*"):
                    if module.startswith(pattern[:-1]):
                        return True
                elif module == pattern:
                    return True
        for name in self.packages:
            if module == name or module.startswith(name + "/"):
                return True
        return False

    def _match_alias(self, pattern, targets, module, base, match_fn) -> str | None:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if not module.startswith(prefix):
                return None
            rest = module[len(prefix):]
            for t in targets:
                tt = t[:-1] if t.endswith("*") else t
                hit = match_fn(_norm_join(base, tt + rest), self.files_set)
                if hit:
                    return hit
        elif module == pattern:
            for t in targets:
                hit = match_fn(_norm_join(base, t), self.files_set)
                if hit:
                    return hit
        return None


def build_alias_resolver(project_root: Path, paths: list[str], files_set: set[str]) -> AliasResolver:
    """Scan indexed tsconfig/jsconfig/package.json files into an AliasResolver."""
    root = project_root.resolve()
    configs: list[dict] = []
    packages: dict[str, str] = {}

    for rel in paths:
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        cdir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if name in _CONFIG_NAMES:
            entry = _read_tsconfig(root, rel, cdir, depth=0)
            if entry is not None:
                configs.append(entry)
        elif name == "package.json":
            data = _load_jsonc(root, rel)
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                packages[data["name"]] = cdir

    return AliasResolver(configs, packages, files_set)


def _read_tsconfig(root: Path, rel: str, cdir: str, *, depth: int) -> dict | None:
    data = _load_jsonc(root, rel)
    if not isinstance(data, dict):
        return None
    opts = data.get("compilerOptions") or {}
    base_url = opts.get("baseUrl")
    paths = opts.get("paths")

    # Follow one `extends` level to inherit baseUrl/paths when absent.
    if (base_url is None or paths is None) and isinstance(data.get("extends"), str) and depth < 3:
        ext_rel = _norm_join(cdir, data["extends"])
        if not ext_rel.endswith(".json"):
            ext_rel += ".json"
        parent = _read_tsconfig(root, ext_rel, ext_rel.rsplit("/", 1)[0] if "/" in ext_rel else "",
                                depth=depth + 1)
        if parent is not None:
            if base_url is None:
                # baseUrl is relative to the file that declared it; the parent
                # already resolved it against its own dir.
                base_dir = parent["base"]
            else:
                base_dir = _norm_join(cdir, base_url)
            paths = paths or parent["paths"]
            return {"dir": cdir, "base": base_dir, "paths": _clean_paths(paths)}

    if not paths and base_url is None:
        return None
    base_dir = _norm_join(cdir, base_url) if base_url else cdir
    return {"dir": cdir, "base": base_dir, "paths": _clean_paths(paths)}


def _clean_paths(paths) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if isinstance(paths, dict):
        for k, v in paths.items():
            if isinstance(v, list):
                out[k] = [t for t in v if isinstance(t, str)]
            elif isinstance(v, str):
                out[k] = [v]
    return out
