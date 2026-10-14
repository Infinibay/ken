"""Prepare tokenizer-bounded source indexes without using the GPU or query labels."""
from __future__ import annotations

import argparse
import json
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from ken.bench.runner import source_manifest
from ken.db import connect, init_schema
from ken.gitignore_filter import iter_files
from ken.indexer import index_files
from ken.retrieval.indexing import passage_policy
from ken.retrieval.profile import RetrievalProfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    parser.add_argument("roots", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    profile = RetrievalProfile.from_dict(json.loads(args.profile.read_text()))
    policy = passage_policy(profile)
    roots = {repo: Path(root) for repo, root in json.loads(args.roots.read_text()).items()}
    args.output.mkdir(parents=True, exist_ok=False)
    indices = args.output / "indices"
    indices.mkdir()
    stats = {}
    for repo, root in sorted(roots.items()):
        if Path(repo).name != repo or repo in (".", ".."):
            raise ValueError("repository id must be a safe index name")
        started = time.perf_counter()
        paths = list(iter_files(root))
        with closing(connect(indices / (repo + ".db"))) as conn:
            init_schema(conn)
            stats[repo] = {**source_manifest(root, paths), **asdict(index_files(
                conn, root, paths, retrieval_policy=policy)), "source_ms": (time.perf_counter()-started)*1000,
                "passages": conn.execute("SELECT COUNT(*) FROM ci_passages").fetchone()[0]}
        (args.output / "source-preparation.json").write_text(json.dumps({"profile": profile.to_dict(),
            "profile_sha256": profile.fingerprint, "repos": stats}, indent=2))
        print(json.dumps({"repo": repo, **stats[repo]}), flush=True)


if __name__ == "__main__":
    main()
