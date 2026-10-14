"""File-transactional projections of canonical code identities and source passages."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Sequence

from ken.retrieval.model import EntityKey, Passage, Span
from ken.retrieval.passages import EXTRACTOR_VERSION, PassagePolicy
from ken.retrieval.tokenization import code_tokens


def generation(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='retrieval_generation'").fetchone()
    return int(row[0]) if row else 0


def replace_file_passages(conn: sqlite3.Connection, file_id: int,
                          passages: list[Passage], generation_id: int | None = None, *,
                          source_hash: str | None = None,
                          policy: PassagePolicy | None = None) -> None:
    """Publish inside the caller's transaction; never commit a partial file."""
    if not conn.in_transaction:
        raise ValueError("passage replacement requires the file transaction")
    policy = policy or PassagePolicy()
    symbols = {(r["kind"], r["qualname"], r["line_start"], r["line_end"]): r["id"]
               for r in conn.execute("SELECT * FROM ci_symbols WHERE file_id=?", (file_id,))}
    conn.execute("DELETE FROM ci_passages WHERE file_id=?", (file_id,))
    for p in passages:
        symbol_id = None
        if p.entity.qualname is not None:
            key = (p.entity.kind, p.entity.qualname, p.entity_span.start_line, p.entity_span.end_line)
            if key not in symbols:
                raise ValueError(f"passage has no canonical symbol: {p.entity.qualname}")
            symbol_id = symbols[key]
        cur = conn.execute(
            "INSERT INTO ci_passages(file_id,symbol_id,line_start,line_end,fields_json,role,split_reason,implementation_start_line) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (file_id, symbol_id, p.span.start_line, p.span.end_line,
             json.dumps(p.fields, ensure_ascii=False, separators=(",", ":")), p.role, p.split_reason,
             p.implementation_start_line),
        )
        passage_id = cur.lastrowid
        for name, text in p.fields.items():
            counts = Counter(code_tokens(text))
            conn.execute("INSERT INTO ci_passage_lengths(passage_id,field,length) VALUES (?,?,?)",
                         (passage_id, name, sum(counts.values())))
            conn.executemany("INSERT INTO ci_passage_terms(passage_id,field,term,tf) VALUES (?,?,?,?)",
                             [(passage_id, name, term, count) for term, count in counts.items()])
    digest = source_hash or (passages[0].source_hash if passages else hashlib.sha256(b"").hexdigest())
    if any(p.source_hash != digest for p in passages):
        raise ValueError("mixed source generations in passage replacement")
    conn.execute(
        "INSERT INTO ci_retrieval_files(file_id,source_hash,extractor_version,tokenizer_version,max_tokens) "
        "VALUES (?,?,?,?,?) ON CONFLICT(file_id) DO UPDATE SET "
        "source_hash=excluded.source_hash,extractor_version=excluded.extractor_version,"
        "tokenizer_version=excluded.tokenizer_version,max_tokens=excluded.max_tokens",
        (file_id, digest, EXTRACTOR_VERSION, policy.tokenizer_version, policy.max_tokens),
    )


def load_passage_map(conn: sqlite3.Connection, ids: Sequence[int] | None = None) -> dict[int, Passage]:
    if ids is not None and not ids:
        return {}
    sql = ("SELECT p.*, f.path,f.language,r.source_hash FROM ci_passages p "
           "JOIN ci_files f ON f.id=p.file_id JOIN ci_retrieval_files r ON r.file_id=p.file_id ")
    params = list(ids) if ids is not None else []
    if ids is not None:
        sql += "WHERE p.id IN (" + ",".join("?" for _ in ids) + ") "
    rows = conn.execute(sql + "ORDER BY p.file_id,p.line_start,p.id", params).fetchall()
    if not rows:
        return {}
    file_ids = sorted({r["file_id"] for r in rows})
    symbols: dict[int, tuple[EntityKey, Span]] = {}
    ordinals: dict[tuple[str, str, str], int] = {}
    for row in conn.execute(
        "SELECT s.*, f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id "
        "WHERE s.file_id IN (" + ",".join("?" for _ in file_ids) + ") "
        "ORDER BY s.file_id,s.line_start,s.id", file_ids
    ):
        key = (row["path"], row["kind"], row["qualname"])
        ordinal = ordinals.get(key, 0)
        ordinals[key] = ordinal + 1
        name = row["qualname"] or row["name"]
        owner = name.rsplit(".", 1)[0] if "." in name else None
        symbols[row["id"]] = (EntityKey(row["path"], row["kind"], name, owner, ordinal),
                              Span(row["line_start"], row["line_end"]))
    out: dict[int, Passage] = {}
    for row in rows:
        span = Span(row["line_start"], row["line_end"])
        identity, extent = symbols.get(row["symbol_id"], (EntityKey(row["path"], "module", None), span))
        out[row["id"]] = Passage(identity, span, json.loads(row["fields_json"]), row["source_hash"],
                                extent, row["language"] or "text", row["role"], row["split_reason"],
                                implementation_start_line=row["implementation_start_line"])
    return out


def load_passages(conn: sqlite3.Connection, entity: EntityKey | None = None) -> list[Passage]:
    return [p for p in load_passage_map(conn).values() if entity is None or p.entity == entity]
