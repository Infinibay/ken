"""Reproducible storage decision experiment on tracked source files.

    PYTHONPATH=.:src python -m examples.bench.ast_storage.experiment build \
        ../codex /tmp/ken-ast-storage
    PYTHONPATH=.:src python -m examples.bench.ast_storage.experiment query \
        /tmp/ken-ast-storage flatbuffers

Build once, query each backend in a fresh process, repeat in alternating order.
No writes to the repository being analyzed. This does not run the GoF catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter
from contextlib import closing
from itertools import pairwise
from pathlib import Path

import numpy as np

from ken.structural.frontend import LANGUAGES, parser_for

from .codec import (
    FIELDS,
    Dictionary,
    decode_flat,
    decode_flat_scalar,
    decode_packed,
    encode_flat,
    encode_packed,
    flatten,
)
from .matching import QUERIES, Matcher, oracle

BACKENDS = ("sqlite", "flatbuffers", "packed")
GROUPED = ("flatbuffers_grouped", "packed_grouped")


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def peak_mb():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024**2 if platform.system() == "Darwin" else 1024)


def fingerprint(rows):
    return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()


def connect(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA cache_size=-16384")
    return db


def create(db, backend):
    db.execute(
        "CREATE TABLE units(unit INTEGER PRIMARY KEY,path TEXT,language TEXT,hash TEXT,source BLOB,ast BLOB)"
    )
    db.execute("CREATE TABLE dictionary(id INTEGER PRIMARY KEY,word TEXT)")
    if backend == "sqlite":
        db.execute(
            "CREATE TABLE nodes(unit INTEGER,node INTEGER,"
            + ",".join(name + " INTEGER" for name in FIELDS)
            + ",PRIMARY KEY(unit,node)) WITHOUT ROWID"
        )
    elif backend in GROUPED:
        db.execute(
            "CREATE TABLE postings(kind INTEGER,unit INTEGER,nodes BLOB,PRIMARY KEY(kind,unit)) WITHOUT ROWID"
        )
    else:
        db.execute(
            "CREATE TABLE postings(kind INTEGER,unit INTEGER,node INTEGER,subtree_end INTEGER,PRIMARY KEY(kind,unit,node)) WITHOUT ROWID"
        )


def write_unit(db, backend, unit, path, language, source, columns, *, replace=False):
    if replace:
        table = "nodes" if backend == "sqlite" else "postings"
        db.execute(f"DELETE FROM {table} WHERE unit=?", (unit,))
    blob = (
        None
        if backend == "sqlite"
        else encode_flat
        if backend.startswith("flatbuffers")
        else encode_packed
    )
    db.execute(
        "INSERT OR REPLACE INTO units VALUES (?,?,?,?,?,?)",
        (
            unit,
            path,
            language,
            hashlib.sha256(source).hexdigest(),
            source,
            blob(columns) if blob else None,
        ),
    )
    if backend == "sqlite":
        lists = [c.tolist() for c in columns]
        db.executemany(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
            ((unit, i, *row) for i, row in enumerate(zip(*lists))),
        )
    elif backend in GROUPED:
        ids = np.flatnonzero(columns[6] & 1).astype("<u4")
        kinds = columns[0][ids]
        order = np.argsort(kinds, kind="stable")
        ids, kinds = ids[order], kinds[order]
        boundaries = np.flatnonzero(np.r_[True, kinds[1:] != kinds[:-1], True])
        db.executemany(
            "INSERT INTO postings VALUES (?,?,?)",
            (
                (int(kinds[a]), unit, ids[a:b].tobytes())
                for a, b in pairwise(boundaries)
                if b > a
            ),
        )
    else:
        db.executemany(
            "INSERT INTO postings VALUES (?,?,?,?)",
            (
                (int(columns[0][i]), unit, int(i), int(columns[3][i]))
                for i in np.flatnonzero(columns[6] & 1)
            ),
        )


class Shifted:
    def __init__(self, column, start):
        self.column, self.start = column, start

    def __getitem__(self, index):
        return self.column[index - self.start]


def run_query(path, backend, query, matcher, *, only_unit=None):
    # Read-only connection: queries cannot migrate or rebuild the cache.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA cache_size=-16384")
        table = "nodes" if backend == "sqlite" else "postings"
        kinds = sorted(matcher.roots[query])
        where = " AND flags&1!=0" if backend == "sqlite" else ""
        if only_unit is not None:
            where += " AND unit=?"
        selection = "unit,nodes" if backend in GROUPED else "unit,node,subtree_end"
        ordering = "unit,kind" if backend in GROUPED else "unit,node"
        sql = f"SELECT {selection} FROM {table} WHERE kind IN ({','.join('?' for _ in kinds)}){where} ORDER BY {ordering}"
        hits, examined, decoded_nodes, files = [], 0, 0, set()
        current, columns = None, None
        parameters = kinds if only_unit is None else [*kinds, only_unit]
        candidates = db.execute(sql, parameters)
        if backend in GROUPED:
            candidates = (
                (unit, int(node), None)
                for unit, payload in candidates
                for node in np.frombuffer(payload, dtype="<u4")
            )
        for unit, node, end in candidates:
            examined += 1
            files.add(unit)
            if backend == "sqlite":
                rows = db.execute(
                    "SELECT "
                    + ",".join(FIELDS)
                    + " FROM nodes WHERE unit=? AND node>=? AND node<? ORDER BY node",
                    (unit, node, end),
                ).fetchall()
                columns = tuple(Shifted(c, node) for c in zip(*rows))
                decoded_nodes += len(rows)
            elif unit != current:
                blob = db.execute(
                    "SELECT ast FROM units WHERE unit=?", (unit,)
                ).fetchone()[0]
                decode = {
                    "flatbuffers": decode_flat,
                    "packed": decode_packed,
                    "flatbuffers_scalar": decode_flat_scalar,
                    "flatbuffers_grouped": decode_flat,
                    "packed_grouped": decode_packed,
                }[backend]
                columns = decode(blob)
                current = unit
            if matcher.match(query, columns, node):
                hits.append((unit, int(columns[4][node]), int(columns[5][node])))
    return hits, {
        "candidates": examined,
        "files": len(files),
        "sqlite_materialized_node_rows": decoded_nodes,
    }


def build(root, output, limit, backends=BACKENDS):
    output.mkdir(parents=True, exist_ok=False)
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
    paths = [
        p
        for p in tracked.decode().split("\0")
        if Path(p).suffix in LANGUAGES and (root / p).is_file()
    ]
    paths.sort()
    if limit:
        paths = paths[:limit]
    dictionaries, databases = Dictionary(), {}
    build_times = {backend: 0.0 for backend in backends}
    for backend in backends:
        db = connect(output / (backend + ".sqlite"))
        create(db, backend)
        databases[backend] = db
    expected = {query: [] for query in QUERIES}
    read_s = parse_s = projection_s = oracle_s = 0.0
    node_count = named_count = source_bytes = 0
    errors, manifest, languages = [], [], Counter()
    update = None
    for unit, path in enumerate(paths):
        started = time.perf_counter()
        source = (root / path).read_bytes()
        read_s += time.perf_counter() - started
        language = LANGUAGES[Path(path).suffix]
        started = time.perf_counter()
        tree = parser_for(language, path).parse(source)
        parse_s += time.perf_counter() - started
        started = time.perf_counter()
        columns = flatten(tree, dictionaries)
        projection_s += time.perf_counter() - started
        started = time.perf_counter()
        for query, hits in oracle(tree).items():
            expected[query].extend((unit, *hit) for hit in hits)
        oracle_s += time.perf_counter() - started
        node_count += len(columns[0])
        named_count += int(np.count_nonzero(columns[6] & 1))
        source_bytes += len(source)
        languages[language] += 1
        if tree.root_node.has_error:
            errors.append(path)
        manifest.append((path, hashlib.sha256(source).hexdigest()))
        if language == "python" and (update is None or len(source) > update[0]):
            update = (len(source), unit, path)
        # Rotate build order so one format does not always benefit from going last.
        shift = unit % len(backends)
        order = backends[shift:] + backends[:shift]
        for backend in order:
            started = time.perf_counter()
            write_unit(
                databases[backend], backend, unit, path, language, source, columns
            )
            if unit % 32 == 31:
                databases[backend].commit()
            build_times[backend] += time.perf_counter() - started
        if unit % 250 == 249:
            print("BUILD", unit + 1, "nodes", node_count, flush=True)
    sizes, payload = {}, {}
    for backend, db in databases.items():
        started = time.perf_counter()
        db.executemany(
            "INSERT INTO dictionary VALUES (?,?)", enumerate(dictionaries.words)
        )
        if backend == "sqlite":
            db.execute(
                "CREATE INDEX candidates ON nodes(kind,unit,node) WHERE flags&1!=0"
            )
        else:
            # Supports replacement without scanning the project-wide kind index.
            db.execute("CREATE INDEX posting_unit ON postings(unit)")
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        build_times[backend] += time.perf_counter() - started
        payload[backend] = db.execute(
            "SELECT coalesce(sum(length(ast)),0) FROM units"
        ).fetchone()[0]
        db.close()
        sizes[backend] = (output / (backend + ".sqlite")).stat().st_size
    dump(
        output / "oracle.json",
        {q: {"matches": len(v), "sha256": fingerprint(v)} for q, v in expected.items()},
    )
    dump(output / "manifest.json", manifest)
    import flatbuffers

    report = {
        "root": str(root),
        "scope": "all tracked files supported by structural frontend"
        if not limit
        else f"first {limit} tracked supported files",
        "files": len(paths),
        "languages": dict(languages),
        "nodes": node_count,
        "named_nodes": named_count,
        "source_bytes": source_bytes,
        "parse_errors": errors,
        "read_seconds": read_s,
        "parse_seconds": parse_s,
        "projection_seconds": projection_s,
        "oracle_seconds_excluded": oracle_s,
        "persistence_seconds": build_times,
        "total_cold_seconds": {
            b: read_s + parse_s + projection_s + t for b, t in build_times.items()
        },
        "database_bytes": sizes,
        "ast_payload_bytes": payload,
        "build_peak_mb": peak_mb(),
        "built_backends": backends,
        "update_candidate": update,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "flatbuffers": flatbuffers.__version__,
        "numpy": np.__version__,
        "sqlite": sqlite3.sqlite_version,
        "limitations": [
            "Syntax only, no GoF or cross-file semantic evaluation",
            "Equivalent minimal SQLite columns, not current complete graph schema",
            "Shared parsing/projection; persistence timed separately and rotated per file",
            "Cold means fresh cache, not flushed OS page cache",
            "Raw Tree-sitter trees are not serialized; stable numeric syntax projection is stored",
            "Blobs loaded per candidate file via SQLite, no mmap claim",
        ],
    }
    dump(output / "build.json", report)
    print(json.dumps(report, indent=2), flush=True)


def query(output, backend, label):
    actual = "flatbuffers" if backend == "flatbuffers_scalar" else backend
    path = output / (actual + ".sqlite")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        words = [r[0] for r in db.execute("SELECT word FROM dictionary ORDER BY id")]
    matcher = Matcher(words)
    expected = json.loads((output / "oracle.json").read_text())
    report = {"backend": backend, "queries": {}}
    for name in QUERIES:
        started = time.perf_counter()
        hits, stats = run_query(path, backend, name, matcher)
        elapsed = time.perf_counter() - started
        digest = fingerprint(hits)
        assert digest == expected[name]["sha256"], (
            backend,
            name,
            len(hits),
            expected[name],
        )
        report["queries"][name] = {
            "seconds": elapsed,
            "matches": len(hits),
            "sha256": digest,
            **stats,
        }
        print(backend, name, round(elapsed, 4), len(hits), flush=True)
    report["query_peak_mb"] = peak_mb()
    report["batch_seconds"] = sum(q["seconds"] for q in report["queries"].values())
    dump(output / f"query-{label}-{backend}.json", report)


def update(output, label, backends=BACKENDS):
    report = json.loads((output / "build.json").read_text())
    _, unit, path = report["update_candidate"]
    results = {}
    shift = int(label) % len(backends) if label.isdigit() else 0
    for backend in backends[shift:] + backends[:shift]:
        db = connect(output / (backend + ".sqlite"))
        original = db.execute(
            "SELECT language,source,hash FROM units WHERE unit=?", (unit,)
        ).fetchone()
        unchanged = db.execute(
            "SELECT unit,hash FROM units WHERE unit!=? ORDER BY unit", (unit,)
        ).fetchall()
        language, source, _ = original
        dictionary = Dictionary()
        dictionary.words = [
            r[0] for r in db.execute("SELECT word FROM dictionary ORDER BY id")
        ]
        dictionary.ids = {word: i for i, word in enumerate(dictionary.words)}
        changed = (
            source
            + b"\n\ndef ken_storage_probe(value):\n    if value == 81723:\n        return probe(value)\n"
        )
        started = time.perf_counter()
        tree = parser_for(language, path).parse(changed)
        assert not tree.root_node.has_error
        columns = flatten(tree, dictionary)
        parse_projection = time.perf_counter() - started
        started = time.perf_counter()
        write_unit(db, backend, unit, path, language, changed, columns, replace=True)
        db.executemany(
            "INSERT OR REPLACE INTO dictionary VALUES (?,?)",
            enumerate(dictionary.words),
        )
        db.commit()
        publication = time.perf_counter() - started
        assert (
            unchanged
            == db.execute(
                "SELECT unit,hash FROM units WHERE unit!=? ORDER BY unit", (unit,)
            ).fetchall()
        )
        matcher = Matcher(dictionary.words)
        # Independently verify new and old candidates in the changed unit.
        expected = oracle(tree)
        for name in QUERIES:
            hits, _ = run_query(
                output / (backend + ".sqlite"), backend, name, matcher, only_unit=unit
            )
            assert sorted((a, b) for u, a, b in hits if u == unit) == sorted(
                expected[name]
            )
        results[backend] = {
            "parse_projection_seconds": parse_projection,
            "publication_seconds": publication,
            "total_seconds": parse_projection + publication,
            "source_growth_bytes": len(changed) - len(source),
            "unchanged_unit_hashes_equal": True,
            "updated_candidates_equal_oracle": True,
        }
        # Restore exactly the original unit so query repetitions remain comparable.
        old = flatten(parser_for(language, path).parse(source), dictionary)
        write_unit(db, backend, unit, path, language, source, old, replace=True)
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()
    dump(
        output / f"update-{'grouped-' if backends == GROUPED else ''}{label}.json",
        {"path": path, "original_bytes": len(source), "backends": results},
    )
    print(json.dumps(results, indent=2))


def measure(output, repeats, *, grouped=False):
    """Isolate query memory and caches; preserve every raw sample."""
    backends = GROUPED if grouped else BACKENDS
    results = {backend: [] for backend in backends}
    for repeat in range(1, repeats + 1):
        order = backends if repeat % 2 else tuple(reversed(backends))
        for backend in order:
            started = time.perf_counter()
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    __package__ + ".experiment",
                    "query",
                    str(output),
                    backend,
                    "--label",
                    str(repeat),
                ],
                check=True,
            )
            sample = json.loads((output / f"query-{repeat}-{backend}.json").read_text())
            sample["process_wall_seconds"] = time.perf_counter() - started
            results[backend].append(sample)
    if not grouped:
        subprocess.run(
            [
                sys.executable,
                "-m",
                __package__ + ".experiment",
                "query",
                str(output),
                "flatbuffers_scalar",
                "--label",
                "1",
            ],
            check=True,
        )
    updates = []
    for repeat in range(1, repeats + 1):
        subprocess.run(
            [
                sys.executable,
                "-m",
                __package__ + ".experiment",
                "update",
                str(output),
                "--label",
                str(repeat),
                *(["--grouped"] if grouped else []),
            ],
            check=True,
        )
        updates.append(
            json.loads(
                (
                    output / f"update-{'grouped-' if grouped else ''}{repeat}.json"
                ).read_text()
            )
        )
    summary = {}
    for backend, samples in results.items():
        summary[backend] = {
            "batch_median_seconds": statistics.median(
                s["batch_seconds"] for s in samples
            ),
            "batch_samples_seconds": [s["batch_seconds"] for s in samples],
            "query_peak_mb_samples": [s["query_peak_mb"] for s in samples],
            "process_wall_samples_seconds": [
                s["process_wall_seconds"] for s in samples
            ],
            "queries": {
                q: {
                    "median_seconds": statistics.median(
                        s["queries"][q]["seconds"] for s in samples
                    ),
                    "matches": samples[0]["queries"][q]["matches"],
                    "sha256": samples[0]["queries"][q]["sha256"],
                }
                for q in QUERIES
            },
            "update_total_median_seconds": statistics.median(
                s["backends"][backend]["total_seconds"] for s in updates
            ),
            "update_publication_median_seconds": statistics.median(
                s["backends"][backend]["publication_seconds"] for s in updates
            ),
        }
    dump(output / ("summary-grouped.json" if grouped else "summary.json"), summary)
    print(json.dumps(summary, indent=2))


def repack(output):
    """Isolate grouped posting-list construction on the same stored syntax."""
    original = output / "flatbuffers.sqlite"
    with closing(
        sqlite3.connect(original.resolve().as_uri() + "?mode=ro", uri=True)
    ) as source_db:
        dictionaries = source_db.execute(
            "SELECT id,word FROM dictionary ORDER BY id"
        ).fetchall()
        databases, timings = {}, {b: 0.0 for b in GROUPED}
        for backend in GROUPED:
            path = output / (backend + ".sqlite")
            if path.exists():
                raise FileExistsError(path)
            databases[backend] = connect(path)
            create(databases[backend], backend)
        for unit, path, language, source, blob in source_db.execute(
            "SELECT unit,path,language,source,ast FROM units ORDER BY unit"
        ):
            columns = decode_flat(blob)
            shift = unit % 2
            for backend in GROUPED[shift:] + GROUPED[:shift]:
                started = time.perf_counter()
                write_unit(
                    databases[backend], backend, unit, path, language, source, columns
                )
                if unit % 32 == 31:
                    databases[backend].commit()
                timings[backend] += time.perf_counter() - started
        report = {}
        for backend, db in databases.items():
            started = time.perf_counter()
            db.executemany("INSERT INTO dictionary VALUES (?,?)", dictionaries)
            db.execute("CREATE INDEX posting_unit ON postings(unit)")
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            timings[backend] += time.perf_counter() - started
            report[backend] = {
                "persistence_seconds": timings[backend],
                "posting_rows": db.execute("SELECT count(*) FROM postings").fetchone()[
                    0
                ],
            }
            db.close()
            report[backend]["database_bytes"] = (
                (output / (backend + ".sqlite")).stat().st_size
            )
        dump(
            output / "grouped-build.json",
            {
                "backends": report,
                "scope": "persistence only from identical cached syntax; excludes input reads/decoding, parsing and projection",
            },
        )
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("build")
    p.add_argument("root", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--backend", choices=(*BACKENDS, *GROUPED))
    p = commands.add_parser("query")
    p.add_argument("output", type=Path)
    p.add_argument("backend", choices=(*BACKENDS, *GROUPED, "flatbuffers_scalar"))
    p.add_argument("--label", default="1")
    p = commands.add_parser("update")
    p.add_argument("output", type=Path)
    p.add_argument("--label", default="1")
    p.add_argument("--grouped", action="store_true")
    p = commands.add_parser("measure")
    p.add_argument("output", type=Path)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--grouped", action="store_true")
    p = commands.add_parser("repack")
    p.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(
            args.root.resolve(),
            args.output,
            args.limit,
            (args.backend,) if args.backend else BACKENDS,
        )
    elif args.command == "query":
        query(args.output, args.backend, args.label)
    elif args.command == "measure":
        if args.repeats < 1:
            parser.error("--repeats must be positive")
        measure(args.output, args.repeats, grouped=args.grouped)
    elif args.command == "repack":
        repack(args.output)
    else:
        update(args.output, args.label, GROUPED if args.grouped else BACKENDS)


if __name__ == "__main__":
    main()
