"""Prepare an explicit local retrieval profile without changing assistant wiring."""
from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path


def configure(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="retrieval_command", required=True)
    index = sub.add_parser("index", help="prepare or update source passages and local model views")
    index.add_argument("--path", default=".")
    index.add_argument("--profile", type=Path, help="immutable retrieval profile JSON; otherwise reuse active profile")
    index.add_argument("--json", action="store_true")
    prepare = sub.add_parser("prepare", help="prepare the best complete CPU search configuration")
    prepare.add_argument("--path", default=".")
    prepare.add_argument("--json", action="store_true")


def dispatch(args: argparse.Namespace) -> int:
    from ken import _paths
    from ken.db import connect, init_schema
    from ken.gitignore_filter import iter_files
    from ken.retrieval.candidates import active_profile
    from ken.retrieval.indexing import index_project
    from ken.retrieval.profile import RetrievalProfile

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: project directory does not exist: {root}", file=sys.stderr)
        return 1
    _paths.ken_dir(root).mkdir(parents=True, exist_ok=True)
    try:
        with closing(connect(_paths.db_path(root))) as conn:
            init_schema(conn)
            if args.retrieval_command == "prepare":
                from ken.indexer import index_files
                from ken.retrieval.passages import PassagePolicy
                from ken.retrieval.best_search import prepare_best
                index_files(conn, root, iter_files(root), retrieval_policy=PassagePolicy())
                best_result = prepare_best(conn, root)
                if not _paths.meta_path(root).exists():
                    _paths.meta_path(root).write_text("{}", encoding="utf-8")
                print(json.dumps(best_result, ensure_ascii=False) if args.json else
                      f"Prepared best search: {best_result['indexed_files']} files, {best_result['owners']} owners.")
                return 0
            profile = (RetrievalProfile.from_dict(json.loads(args.profile.read_text()), upgrade_representation=True)
                       if args.profile else active_profile(conn, upgrade_for_indexing=True))
            started = time.perf_counter()
            stats = index_project(conn, root, iter_files(root), profile=profile)
            result = {"profile_version": profile.fingerprint, "profile": profile.to_dict(),
                      "source": asdict(stats), "passages": conn.execute("SELECT COUNT(*) FROM ci_passages").fetchone()[0],
                      "elapsed_ms": (time.perf_counter() - started) * 1000}
        if not _paths.meta_path(root).exists():
            _paths.meta_path(root).write_text("{}", encoding="utf-8")
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        print(f"error: retrieval preparation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False) if args.json else
          f"Prepared {result['passages']} source passages; profile {profile.fingerprint}.")
    return 0
