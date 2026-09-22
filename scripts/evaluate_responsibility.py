"""Exercise ken tools who against this project's real index; retain every answer."""

from pathlib import Path
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/validation/responsibility-2026-09-21"
CASES = [
    ("persist", "Who stores reusable findings?", [], "remember"),
    ("register", "Who registers functions as MCP tools and CLI tools?", [], "ken_tool"),
    (
        "json",
        "Who decodes object parameters including each item of an array of objects?",
        [],
        "_tool_json_object",
    ),
    (
        "paths",
        "Who resolves paths and requires them to remain inside the project?",
        [],
        "resolve_project_path",
    ),
    (
        "purpose",
        "Who scores files and symbols by explicit purpose text such as docstrings?",
        [],
        "doc_intent_scores",
    ),
    (
        "snippets",
        "Who returns source snippets for selected symbols or a line range?",
        [],
        "file_snippets",
    ),
    ("persist_es", "¿Quién guarda las memorias entre sesiones?", [], "remember"),
    (
        "persist_es_hypothesis",
        "¿Quién guarda las memorias entre sesiones?",
        ["Store or update a reusable finding"],
        "remember",
    ),
    ("register_es", "¿Quién registra herramientas para MCP y CLI?", [], "ken_tool"),
    (
        "register_es_hypothesis",
        "¿Quién registra herramientas para MCP y CLI?",
        ["Register a function as both an MCP tool and a CLI tool"],
        "ken_tool",
    ),
    (
        "json_paraphrase",
        "Who turns JSON command-line arguments into dictionaries?",
        [],
        "_tool_json_object",
    ),
    ("absent", "Who launches rockets to Mars?", [], None),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for name, question, hypotheses, expected in CASES:
        command = [
            sys.executable,
            "-m",
            "ken",
            "tools",
            "--path",
            str(ROOT),
            "who",
            question,
            "--full",
            "--path",
            "src/ken",
            "--limit",
            "3",
        ]
        if hypotheses:
            command += ["--hypotheses", *hypotheses]
        start = time.monotonic()
        process = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=60
        )
        (OUT / f"{name}.json").write_text(process.stdout)
        (OUT / f"{name}.stderr").write_text(process.stderr)
        if process.returncode:
            raise RuntimeError(process.stderr)
        answer = json.loads(process.stdout)
        found = [c["symbol"] for c in answer["candidates"]]
        result = {
            "case": name,
            "question": question,
            "hypotheses": hypotheses,
            "expected_symbol": expected,
            "found": found,
            "scores": [c["confidence"]["score"] for c in answer["candidates"]],
            "status": answer["status"],
            "seconds": round(time.monotonic() - start, 3),
            "hit_at_1": (found[:1] == [expected]) if expected else not found,
            "hit_at_3": expected in found if expected else not found,
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    (OUT / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
