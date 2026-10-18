"""Freeze working-tree inputs and keep an isolated, content-verified Python oracle."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PRIVATE = {".git", ".ken", ".venv", ".superpowers", ".agents", ".codex", ".claude",
           ".infinidev", ".dsh", "__pycache__", ".pytest_cache", ".mypy_cache", "target"}
MIGRATION_ADDITIONS = ("tests/rust_migration/",)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _eligible(repo: Path, path: Path) -> bool:
    rel = path.relative_to(repo)
    if set(rel.parts) & PRIVATE or path.name.startswith(".env"):
        return False
    return path.is_file() and path.resolve().is_relative_to(repo.resolve())


def _files(repo: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=repo, capture_output=True)
    candidates = (repo / p for p in os.fsdecode(result.stdout).split("\0") if p) if result.returncode == 0 else repo.rglob("*")
    return sorted({p for p in candidates if _eligible(repo, p)})


def verify_reference(repo: Path, manifest: Path) -> list[str]:
    data = json.loads(manifest.read_text())
    expected = {r["path"]: r["sha256"] for r in data["files"]}
    changed = {name for name, digest in expected.items()
               if not (repo / name).is_file() or _hash(repo / name) != digest}
    for path in _files(repo):
        name = path.relative_to(repo).as_posix()
        if name in expected or name.startswith(MIGRATION_ADDITIONS):
            continue
        if any(fnmatch.fnmatchcase(name, scope) or name.startswith(scope.rstrip("/") + "/")
               for scope in data.get("scope", [])):
            changed.add(name)
    return sorted(changed)


@dataclass(frozen=True)
class Reference:
    root: Path
    manifest_path: Path
    fingerprint: str
    python: Path

    @classmethod
    def load(cls, root: Path) -> Reference:
        root = root.resolve()
        path = root / "reference-manifest.json"
        data = json.loads(path.read_text())
        return cls(root, path, data["fingerprint"], Path(data["python"]))


def freeze_reference(repo: Path, destination: Path) -> Reference:
    repo, destination = repo.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = _files(repo)
    records = [{"path": p.relative_to(repo).as_posix(), "sha256": _hash(p)} for p in paths]
    fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    stage = Path(tempfile.mkdtemp(prefix=".oracle-", dir=destination.parent))
    try:
        for row in records:
            target = stage / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / row["path"], target)
        if _files(repo) != paths or any(_hash(repo / r["path"]) != r["sha256"] or
                                      _hash(stage / r["path"]) != r["sha256"] for r in records):
            raise RuntimeError("reference changed while freezing")
        python = repo / ".venv/bin/python"
        if not python.is_file():
            python = Path(sys.executable)
        data = {"format": "ken-rust-oracle/1", "scope": [], "fingerprint": fingerprint,
                "python": str(python.absolute()), "files": records}
        (stage / "reference-manifest.json").write_text(json.dumps(data, indent=2) + "\n")
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return Reference.load(destination)


def reference_env(reference: Reference, sandbox: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("KEN_") and "proxy" not in k.lower()}
    for name in ["home", "config", "cache"]:
        (sandbox / name).mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(sandbox / "home"), KEN_CONFIG_DIR=str(sandbox / "config"),
               KEN_CACHE_DIR=str(sandbox / "cache"), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([str(reference.root / "src"), str(reference.root)]))
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify", "freeze"])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    changed = verify_reference(args.repo, args.manifest)
    if changed:
        print(json.dumps({"passed": False, "changed": changed}))
        return 1
    if args.action == "freeze":
        if args.out is None:
            parser.error("freeze requires --out")
        ref = freeze_reference(args.repo, args.out)
        print(json.dumps({"passed": True, "root": str(ref.root), "fingerprint": ref.fingerprint}))
    else:
        print(json.dumps({"passed": True, "changed": []}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
