"""Synthetic projects whose expected status is derived from declared rows."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .reference import Reference

COUNT_NAMES = ("files", "files_embedded", "symbols", "symbols_embedded", "sessions", "active_sessions",
               "contexts", "prompt_contexts", "prompt_contexts_embedded", "interactions", "session_scores",
               "findings", "findings_embedded", "intent_sources", "intent_sources_embedded")
INDEX = "run `ken install .` or re-run it to populate the code index"
STALE = "indexed files are missing on disk; run `ken install .` to resync after branch changes"
EMBED = 'run `ken rank "your task"` once to lazily build embeddings'
PARTIAL = "embeddings are partial; use `ken install . --embed --embed-limit N` to warm more of the project when semantic recall matters"
SEED = "submit at least one prompt through a hooked agent to seed context history"
HOOK = "verify tool hooks are recording reads/edits; no interactions have been captured"
END = "end the active session to snapshot predictive scores"
HISTORY = "let hooks run through a few real turns to build predictive history"
SAVE = "save reusable project facts with `ken remember TOPIC CONTENT`"


def state(root: Path) -> dict:
    result = {}
    for name in ["meta.json", "daemon.port"]:
        p = root / ".ken" / name
        result[name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    db = root / ".ken/ken.db"
    if db.is_file():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                result["database"] = "\n".join(conn.iterdump())
        except sqlite3.DatabaseError:
            result["database"] = hashlib.sha256(db.read_bytes()).hexdigest()
    else:
        result["database"] = None
    return result


@dataclass
class Fixture:
    root: Path
    expected_report: dict
    before_state: dict = field(default_factory=dict)
    health_log: list = field(default_factory=list)
    writer: sqlite3.Connection | None = None
    server: HTTPServer | None = None
    thread: threading.Thread | None = None
    release: threading.Event = field(default_factory=threading.Event)
    start: Path | None = None
    environment: dict = field(default_factory=dict)

    def changed(self) -> list[str]:
        now = state(self.root)
        return [k for k in self.before_state if self.before_state[k] != now[k]]

    def close(self) -> None:
        self.release.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)
        if self.writer:
            self.writer.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _serve(fixture: Fixture, kind: str) -> dict:
    payload = {"sessions_active": 1, "idle_s": 2.5, "version": "fixture"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            fixture.health_log.append({"path": self.path, "authorization": self.headers.get("Authorization")})
            code, body = 200, json.dumps(payload).encode()
            if kind == "empty": body = b""
            elif kind == "empty_object": body = b"{}"
            elif kind == "invalid": body = b"not-json"
            elif kind == "array": body = b"[]"
            elif kind == "null": body = b"null"
            elif kind == "unauthorized": code, body = 401, b"denied"
            elif kind == "error": code, body = 500, b"error"
            elif kind == "redirect" and self.path == "/health": code, body = 302, b""
            if self.headers.get("Authorization") != "Bearer fixture-token":
                code, body = 401, b"denied"
            self.send_response(code)
            if code == 302:
                self.send_header("Location", f"http://127.0.0.1:{fixture.server.server_port}/ready")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if kind == "slow":
                fixture.release.wait(2)
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    fixture.server = HTTPServer(("127.0.0.1", 0), Handler)
    fixture.thread = threading.Thread(target=lambda: fixture.server.serve_forever(poll_interval=.02), daemon=True)
    fixture.thread.start()
    (fixture.root / ".ken/daemon.port").write_text(str(fixture.server.server_port))
    return {"running": True, **payload} if kind == "up" else {"running": False}


def _size(db: Path) -> str:
    if not db.exists(): return "missing"
    size = db.stat().st_size
    for unit in ["B", "KiB", "MiB", "GiB"]:
        if size < 1024: return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TiB"


def build_fixture(parent: Path, scenario: str, reference: Reference) -> Fixture:
    root = parent.resolve() / "project ü with spaces"
    root.mkdir(parents=True)
    fixture = Fixture(root, {})
    marker = root / ".ken"
    if scenario in {"no_project", "marker_only"}:
        if scenario == "marker_only": marker.mkdir()
        fixture.before_state = state(root)
        fixture.expected_report = {"ok": False, "error": f"no ken project found at or above {root}"}
        return fixture
    marker.mkdir()
    meta = {"project_id": "fixture-project", "auth_token": "fixture-token"}
    if scenario == "missing_id": del meta["project_id"]
    if scenario == "missing_token": del meta["auth_token"]
    (marker / "meta.json").write_text("{" if scenario == "invalid_meta" else json.dumps(meta))
    db = marker / "ken.db"
    counts = dict.fromkeys(COUNT_NAMES, 0)
    stale_paths = []
    populated = scenario in {"populated", "slots", "mixed", "closed_session"}
    n = 7 if scenario == "stale" else 2 if scenario in {"partial", "mixed"} else 1 if populated or scenario in {"wal", "no_embeddings", "stale_cycle"} else 0
    if scenario != "metadata_only":
        conn = sqlite3.connect(db)
        conn.executescript((reference.root / "src/ken/schema.sql").read_text())
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        counts["files"] = n
        for i in range(n):
            rel = f"src/missing{i}.py" if scenario == "stale" else f"src/live{i}.py"
            if scenario != "stale":
                p = root / rel; p.parent.mkdir(exist_ok=True); p.write_text("def f(): return 1\n")
                if scenario == "stale_cycle":
                    p.unlink(); p.symlink_to(p.name)
            if scenario in {"stale", "stale_cycle"}:
                stale_paths.append(rel)
            embedded = populated or scenario == "partial" and i == 0
            slot = i if embedded and (scenario == "slots" or scenario == "mixed" and i == 1) else None
            blob = b"vector" if embedded and slot is None else None
            file_id = conn.execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,embedding,vec_slot) VALUES(?,?,?,?,?,?)",
                                   (rel, bytes(32), 1, 1, blob, slot)).lastrowid
            counts["files_embedded"] += int(embedded)
            if scenario != "stale":
                conn.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,embedding,vec_slot) VALUES(?,?,?,?,?,?,?,?)",
                             (file_id, "function", "f", "f", 1, 1, blob, slot))
                counts["symbols"] += 1
                counts["symbols_embedded"] += int(embedded)
        if populated or scenario == "prompts_only":
            ended = 2 if scenario == "closed_session" else None
            session = conn.execute("INSERT INTO cr_sessions(agent_id,started_at,ended_at) VALUES('fixture',1,?)", (ended,)).lastrowid
            conn.execute("INSERT INTO cr_contexts(session_id,kind,content,iteration,embedding,created_at) VALUES(?,'user_prompt','fixture',1,?,1)", (session, b"vector"))
            counts.update(sessions=1, active_sessions=int(ended is None), contexts=1, prompt_contexts=1, prompt_contexts_embedded=1)
            if populated:
                conn.execute("INSERT INTO cr_interactions(session_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(?,1,'read','file','src/live0.py',1,1)", (session,))
                conn.execute("INSERT INTO cr_session_scores(session_id,target_kind,target_path,score,pattern,created_at) VALUES(?,'file','src/live0.py',1,'read_edit',1)", (session,))
                conn.execute("INSERT INTO cr_findings(topic,content,tags,embedding,created_at,updated_at) VALUES('fixture','note','[]',?,1,1)", (b"vector",))
                conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,embedding,updated_at) VALUES(1,'module_docstring','fixture',?,1)", (b"vector",))
                counts.update(interactions=1, session_scores=1, findings=1, findings_embedded=1, intent_sources=1, intent_sources_embedded=1)
        conn.commit()
        if scenario == "wal": fixture.writer = conn
        else: conn.close()
    if scenario == "corrupt_db": db.write_bytes(b"not sqlite")
    if scenario == "old_schema":
        with sqlite3.connect(db) as conn: conn.execute("DROP TABLE ci_symbols")
    daemon = {"running": False}
    if scenario.startswith("health_") or scenario == "missing_token":
        daemon = _serve(fixture, "up" if scenario == "missing_token" else scenario.removeprefix("health_"))
    if scenario == "invalid_port": (marker / "daemon.port").write_text("not-a-port")
    base = {"ok": True, "project_root": str(root), "project_id": "fixture-project",
            "db": {"path": str(db), "size": _size(db), "exists": db.is_file()}, "installed": db.is_file()}
    if db.is_file() and scenario not in {"corrupt_db", "old_schema"}:
        embedded = counts["files_embedded"] + counts["symbols_embedded"]
        total = counts["files"] + counts["symbols"]
        recommendations = []
        if not n: recommendations.append(INDEX)
        elif stale_paths: recommendations.append(STALE)
        if n and not embedded: recommendations.append(EMBED)
        elif embedded < total: recommendations.append(PARTIAL)
        if not counts["prompt_contexts_embedded"]: recommendations.append(SEED)
        elif not counts["interactions"]: recommendations.append(HOOK)
        if not counts["session_scores"]: recommendations.append(END if counts["active_sessions"] else HISTORY)
        if not counts["findings_embedded"]: recommendations.append(SAVE)
        base.update(counts=counts,
                    index_health={"stale_files": len(stale_paths), "sample": sorted(stale_paths)[:5]},
                    rank_signals={"index": "yes" if n else "empty", "embeddings": "none" if not embedded else "ready" if embedded == total else f"partial({embedded}/{total})",
                                  "predictive": "yes" if populated else "no", "findings": "yes" if populated else "no"},
                    embedding_coverage={"embedded": embedded, "total": total, "percent": round(embedded / total * 100, 1) if total else 0.0},
                    recommendations=recommendations, daemon=daemon)
    fixture.expected_report = base
    if scenario in {"nested", "missing_start", "override_empty"}:
        fixture.start = root / "a/b"
        if scenario != "missing_start": fixture.start.mkdir(parents=True)
    if scenario in {"override_valid", "override_invalid", "override_empty", "tilde_override"}:
        fixture.environment["KEN_PROJECT_ROOT"] = str(root)
        if scenario == "override_valid": fixture.start = parent / "outside"
        elif scenario == "override_invalid":
            fixture.environment["KEN_PROJECT_ROOT"] = str(parent / "absent")
            fixture.expected_report = {"ok": False, "error": f"no ken project found at or above {root}"}
        elif scenario == "override_empty": fixture.environment["KEN_PROJECT_ROOT"] = ""
        else:
            fixture.environment.update(HOME=str(parent), KEN_PROJECT_ROOT="~/" + root.name)
    if scenario == "symlink_start":
        fixture.start = parent / "linked"
        fixture.start.symlink_to(root, target_is_directory=True)
    if scenario == "shared_symlinks":
        (root/"l0").symlink_to(".", target_is_directory=True)
        for level in range(1,25):
            previous=f"l{level-1}"
            (root/f"l{level}").symlink_to(f"{previous}/{previous}", target_is_directory=True)
        fixture.start=root/"l24"
    fixture.before_state = state(root)
    return fixture
