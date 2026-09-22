"""Prepare isolated Codex CLI A/B tasks from Ken's real code and memory DB.

The controlled variable is the enriched memory brief, including live validity.
Both modes retain the same historical notes and source index. Retrieval seeds
are fixed so this measures agent use, not retrieval recall. No LLM is invoked by
prepare(); select a prepared session with --run ID, or run its prompt separately
with Codex CLI and use --collect to summarize the JSONL logs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ken.db import connect
from ken.knowledge.context import render_brief
from ken.knowledge.records import ensure_schema, prepare, save
from ken.ranker import FindingItem, RankedItem, RankResult
from ken.ranker.output import render_block


CASES = {
    "mcp": {
        "topic": "mcp-object-cli-parameters",
        "files": [
            "src/ken/mcp/server.py",
            "src/ken/cli.py",
            "tests/test_reasoning_memory.py",
        ],
        "test": "tests/test_reasoning_memory.py::test_cli_decodes_goal_and_premise_objects",
        "prompt": "Quiero exponer una tool nueva que recibe list[dict[str, Any]] y que funcione igual desde MCP y ken tools. ¿Dónde integrarías ese soporte y qué comprobación evitaría repetir bugs anteriores? Confirma el contrato actual y da una recomendación concreta.",
        "rationale": "Hay dos contratos independientes: el esquema MCP/registry y la conversión JSON de argparse. Un test que sólo llama al wrapper MCP no cubre el CLI.",
        "recheck": "Inspeccionar _items_schema y _tool_py_type, y ejecutar test_cli_decodes_goal_and_premise_objects.",
    },
    "body": {
        "topic": "kql2-body-input-projection-dependency-trap-20260921",
        "files": [
            "src/ken/kql2/body.py",
            "src/ken/kql2/source_execution.py",
            "tests/kql2/test_body_field_initializer.py",
        ],
        "test": "tests/kql2/test_body_field_initializer.py",
        "prompt": "Quiero reducir el coste de BODY pasando a su evaluación únicamente los roles que aparecen en SourceExecutor._inputs, en lugar del entorno completo. Evalúa si es una optimización válida hoy y propone una comprobación concreta antes de implementarla.",
        "rationale": "El acceso de member_place a current.values() depende de roles que no aparecen necesariamente en _inputs. La memoria registra que proyectar ese entorno ya provocó regresiones.",
        "recheck": "Auditar member_place y Clause.name y demostrar un conjunto completo de dependencias antes de proyectar el entorno.",
    },
}


def clone_code(destination: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
    for name in ("src", "tests"):
        shutil.copytree(REPO / name, destination / name, ignore=ignore)
    for name in ("AGENTS.md", "README.md", "pyproject.toml", "uv.lock"):
        shutil.copy2(REPO / name, destination / name)
    # Documentation is large because of generated corpora; preserve prose only.
    for file in (REPO / "docs").rglob("*.md"):
        target = destination / file.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)


def run_check(root: Path, target: str) -> dict:
    started = time.monotonic()
    env = os.environ | {"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-o", "addopts=", "-q"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "test": target,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "seconds": time.monotonic() - started,
    }


def prepare_runs(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="ken-coding-memory-", dir="/private/tmp"))
    seed = workspace / "seed"
    clone_code(seed)
    (seed / ".ken").mkdir()
    source = sqlite3.connect(f"file:{REPO / '.ken/ken.db'}?mode=ro", uri=True)
    snapshot = sqlite3.connect(seed / ".ken/ken.db")
    source.backup(snapshot)
    counts = {
        table: snapshot.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "cr_findings",
            "cr_sessions",
            "cr_contexts",
            "cr_interactions",
            "ci_files",
            "ci_symbols",
        )
    }
    snapshot.close()
    source.close()
    (seed / ".ken/meta.json").write_text(
        json.dumps(
            {"project_id": "memory-evaluation", "auth_token": "local-evaluation"}
        )
    )
    checks = {}
    for name, case in CASES.items():
        checks[name] = run_check(seed, case["test"])
        assert checks[name]["exit_code"] == 0, checks[name]
    # Reproduce the old JSON conversion regression only in the disposable copy.
    cli = seed / "src/ken/cli.py"
    original = cli.read_text()
    broken = original.replace(
        'if json_type == "object":\n        return _tool_json_object',
        'if json_type == "object":\n        return str',
    )
    assert broken != original
    cli.write_text(broken)
    checks["mcp_rejected_variant"] = run_check(seed, CASES["mcp"]["test"])
    assert checks["mcp_rejected_variant"]["exit_code"] == 1
    cli.write_text(original)
    (out / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))

    runs = []
    for name, case in CASES.items():
        modes = (
            ("baseline", "memory", "stale-baseline", "stale-memory")
            if name == "mcp"
            else ("baseline", "memory")
        )
        for mode in modes:
            run_id = f"{name}-{mode}"
            root = workspace / run_id
            shutil.copytree(
                seed,
                root,
                ignore=shutil.ignore_patterns(
                    "__pycache__", ".pytest_cache", "*-wal", "*-shm"
                ),
            )
            with connect(root / ".ken/ken.db") as conn:
                row = conn.execute(
                    "SELECT id,content,tags FROM cr_findings WHERE topic=?",
                    (case["topic"],),
                ).fetchone()
                assert row is not None
                ensure_schema(conn)
                evidence = root / "evaluation-evidence.json"
                evidence.write_text(
                    json.dumps(
                        {
                            "current_check": checks[name],
                            "historical_note": row["content"],
                            "rejected_variant": checks.get("mcp_rejected_variant")
                            if name == "mcp"
                            else None,
                            "scope": "Current focused check; historical counts are attributed observations, not re-measured here.",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                save(
                    conn,
                    row["id"],
                    prepare(
                        {
                            "kind": "observation",
                            "rationale": case["rationale"],
                            "evidence": [
                                {
                                    "path": "evaluation-evidence.json",
                                    "note": "Nota histórica y comprobación focal actual.",
                                }
                            ],
                            "dependencies": [{"path": p} for p in case["files"]],
                            "recheck": case["recheck"],
                            "assumptions": [
                                "Comprobación focal; no certifica todas las dependencias transitivas ni otros entornos."
                            ],
                        },
                        root,
                    )
                    if mode.endswith("memory")
                    else None,
                )
                if mode.startswith("stale"):
                    target = root / "src/ken/cli.py"
                    target.write_text(broken)
                result = RankResult(
                    files=[RankedItem(p, "file", 5.0) for p in case["files"]],
                    findings=[FindingItem(case["topic"], row["content"], score=5.0)],
                )
                block = render_block(conn, result, verbose=0, max_chars=2300)
                if mode.endswith("memory"):
                    block += "\n" + render_brief(conn, [case["topic"]], root=root)
            instructions = (
                "Trabaja sólo sobre esta copia de Ken. Es una evaluación de diagnóstico: no modifiques archivos ni memorias. "
                "Puedes consultar Ken y leer código; evita búsquedas o lecturas si el contexto ya resuelve una parte. "
                "Responde en español, máximo 180 palabras, con conclusión, evidencia y prueba recomendada.\n\n"
            )
            prompt = instructions + block + "\n\n" + case["prompt"]
            prompt_path = out / f"{run_id}.prompt.txt"
            prompt_path.write_text(prompt)
            runs.append(
                {
                    "id": run_id,
                    "workspace": str(root),
                    "prompt": str(prompt_path),
                    "prompt_chars": len(prompt),
                    "injected_chars": len(block),
                    "expected_stale": mode.startswith("stale"),
                    "topic": case["topic"],
                }
            )
    manifest = {
        "workspace": str(workspace),
        "source_project": str(REPO),
        "counts": counts,
        "runs": runs,
        "method": "Frozen real DB/code, fixed same retrieval seeds, full legacy memory in both arms, explicit brief injection; diagnostic read-only Codex sessions.",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def run_codex(out: Path, run_id: str) -> None:
    """Run one explicitly selected trial with inherited model/auth, read-only."""
    manifest = json.loads((out / "manifest.json").read_text())
    run = next(r for r in manifest["runs"] if r["id"] == run_id)
    root = Path(run["workspace"])
    if not root.is_dir():
        raise ValueError("Evaluation workspace missing; prepare new trials first")
    args = [
        "codex",
        "exec",
        "--ephemeral",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-C",
        str(root),
    ]
    config = Path.home() / ".codex/config.toml"
    if config.exists():
        for name in tomllib.loads(config.read_text()).get("mcp_servers", {}):
            if name != "ken":
                args += ["-c", f"mcp_servers.{json.dumps(name)}.enabled=false"]
    args += [
        "-c",
        f"mcp_servers.ken.command={json.dumps(sys.executable)}",
        "-c",
        "mcp_servers.ken.args=" + json.dumps(["-m", "ken", "mcp", str(root)]),
        "-c",
        f"mcp_servers.ken.env.PYTHONPATH={json.dumps(str(root / 'src'))}",
        "-c",
        "mcp_servers.ken.required=true",
        "-c",
        "mcp_servers.ken.enabled=true",
    ]
    # argv, never a shell interpolation of the prompt or configuration.
    with (
        Path(run["prompt"]).open() as prompt,
        (out / f"{run_id}.jsonl").open("w") as log,
        (out / f"{run_id}.stderr").open("w") as errors,
    ):
        completed = subprocess.run(
            args, stdin=prompt, stdout=log, stderr=errors, timeout=300
        )
    if completed.returncode:
        raise RuntimeError(f"Codex exited {completed.returncode}; see {run_id}.stderr")
    collect(out)


def collect(out: Path) -> None:
    manifest = json.loads((out / "manifest.json").read_text())
    runs = []
    for run in manifest["runs"]:
        log = out / f"{run['id']}.jsonl"
        if not log.exists():
            continue
        events = [
            json.loads(line)
            for line in log.read_text().splitlines()
            if line.startswith("{")
        ]
        items = [e["item"] for e in events if e.get("type") == "item.completed"]
        usage = next(
            (e["usage"] for e in reversed(events) if e.get("type") == "turn.completed"),
            None,
        )
        final = "\n".join(i["text"] for i in items if i.get("type") == "agent_message")
        (out / f"{run['id']}.answer.md").write_text(final)
        runs.append(
            {
                **run,
                "usage": usage,
                "tools": [
                    i
                    for i in items
                    if i.get("type") in {"command_execution", "mcp_tool_call"}
                ],
                "completed": usage is not None,
            }
        )
    (out / "agent-results.json").write_text(
        json.dumps(runs, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            [
                {
                    k: v
                    for k, v in r.items()
                    if k not in {"tools", "prompt", "workspace"}
                }
                | {"tool_calls": len(r["tools"])}
                for r in runs
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=REPO / "docs/validation/coding-memory-2026-09-21"
    )
    parser.add_argument("--collect", action="store_true")
    parser.add_argument(
        "--run", metavar="ID", help="Run one prepared trial using Codex CLI"
    )
    args = parser.parse_args()
    if args.run:
        run_codex(args.out.resolve(), args.run)
    elif args.collect:
        collect(args.out.resolve())
    else:
        prepare_runs(args.out.resolve())
