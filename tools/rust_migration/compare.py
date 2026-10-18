"""Compare real processes against independent expectations and the Python oracle."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from .fixtures import build_fixture
from .reference import Reference, reference_env


@dataclass
class Case:
    id: str
    scenario: str
    mode: str
    argv: list[str]
    expected_exit: int
    expected: dict
    exception_id: str | None = None


@dataclass
class ProcessResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ns: int


def run_process(argv: list[str], cwd: Path, env: dict[str, str], timeout_s: float) -> ProcessResult:
    start = time.monotonic_ns()
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s)
        return ProcessResult(argv, result.returncode, result.stdout, result.stderr, time.monotonic_ns() - start)
    except subprocess.TimeoutExpired:
        return ProcessResult(argv, 124, "", "process timeout", time.monotonic_ns() - start)


def _normalize(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("report must be an object")
    data = json.loads(json.dumps(data))
    if "project_root" in data: data["project_root"] = "<ROOT>"
    if isinstance(data.get("db"), dict) and "path" in data["db"]: data["db"]["path"] = "<ROOT>/.ken/ken.db"
    if data.get("ok") is False and isinstance(data.get("error"), str) and data["error"].startswith("no ken project found at or above "):
        data["error"] = "no ken project found at or above <ROOT>"
    return data


def _differences(expected, actual, path="report") -> list[str]:
    if type(expected) is not type(actual):
        return [f"{path}: expected {type(expected).__name__}, got {type(actual).__name__}"]
    if isinstance(expected, dict):
        errors = [f"{path}.{k}: missing" for k in expected.keys() - actual.keys()]
        errors += [f"{path}.{k}: unexpected" for k in actual.keys() - expected.keys()]
        for key in expected.keys() & actual.keys():
            errors += _differences(expected[key], actual[key], f"{path}.{key}")
        return errors
    if isinstance(expected, list):
        if len(expected) != len(actual): return [f"{path}: array length differs"]
        return [error for i, (x, y) in enumerate(zip(expected, actual))
                for error in _differences(x, y, f"{path}[{i}]")]
    return [] if expected == actual else [f"{path}: value differs"]


def _text(text: str) -> str:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("project_root  : "): lines[i] = "project_root  : <ROOT>\n"
        elif line.startswith("no ken project found at or above "): lines[i] = "no ken project found at or above <ROOT>\n"
    return "".join(lines)


def compare_case(case: Case, expected: dict, python: ProcessResult, native: ProcessResult) -> list[str]:
    errors = []
    if native.returncode != case.expected_exit: errors.append(f"{case.id}: native exit {native.returncode}, expected {case.expected_exit}")
    if python.returncode != case.expected_exit: errors.append(f"{case.id}: Python exit {python.returncode}, expected {case.expected_exit}")
    if case.exception_id in {"data_error", "argument_error"}:
        if native.stdout or not native.stderr or python.stdout or not python.stderr:
            errors.append(f"{case.id}: error must have empty stdout and nonempty stderr")
        return errors
    if case.mode == "json":
        try:
            actual, original = _normalize(json.loads(native.stdout)), _normalize(json.loads(python.stdout))
            original_expected = _normalize(expected)
            if case.exception_id == "health_redirect":
                original_expected["daemon"] = {"running": True, "sessions_active": 1, "idle_s": 2.5, "version": "fixture"}
            errors += [f"{case.id}: native {e}" for e in _differences(_normalize(expected), actual)]
            errors += [f"{case.id}: Python {e}" for e in _differences(original_expected, original)]
            if case.exception_id is None:
                errors += [f"{case.id}: native/Python {e}" for e in _differences(original, actual)]
        except (ValueError, TypeError): errors.append(f"{case.id}: invalid JSON report")
        if native.stderr or python.stderr: errors.append(f"{case.id}: unexpected stderr")
    else:
        if _text(native.stdout) != _text(python.stdout) or _text(native.stderr) != _text(python.stderr):
            errors.append(f"{case.id}: text or streams differ")
    return errors


def run_case(case: Case, reference: Reference, native_command: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="ken-status-parity-") as temp:
        parent = Path(temp)
        results = []
        expected = None
        changes = []
        child_log = parent / "native-children.log"
        shims = parent / "shims"
        shims.mkdir()
        for name in ["python", "python3", "ken", "sh", "bash", "zsh"]:
            shim = shims / name
            shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(child_log))}\nexit 97\n")
            shim.chmod(0o755)
        for engine, command in [("python", [str(reference.python), "-m", "ken"]), ("native", native_command)]:
            with build_fixture(parent / engine, case.scenario, reference) as fixture:
                env = reference_env(reference, parent / engine / "environment")
                if engine == "native": env["PATH"] = str(shims)
                env.update(fixture.environment)
                argv = [*command, "status", str(fixture.start or fixture.root), *case.argv]
                if case.mode == "json": argv.append("--json")
                result = run_process(argv, parent, env, 10)
                if case.mode == "json" and engine == "python": expected = fixture.expected_report
                results.append(result)
                changes.extend(f"{case.id}: {engine} changed {field}" for field in fixture.changed())
        errors = compare_case(case, expected or {}, results[0], results[1]) + changes
        children = child_log.read_text().splitlines() if child_log.exists() else []
        if children: errors.append(f"{case.id}: native executed a forbidden child: {', '.join(children)}")
        return {"id": case.id, "exception_id": case.exception_id, "passed": not errors, "errors": errors,
                "native_children": children, "python": asdict(results[0]), "native": asdict(results[1])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    ref = Reference.load(args.reference)
    if not args.self_check and not args.native: parser.error("--native is required unless --self-check")
    command = [str(ref.python), "-m", "ken"] if args.self_check else [str(args.native.resolve())]
    cases = [Case(**c) for c in json.loads(args.cases.read_text())["cases"]]
    if args.self_check:
        # A Python/Python harness control cannot certify a deliberate Rust
        # restriction. Those cases remain mandatory in native parity.
        cases = [c for c in cases if c.exception_id != "health_redirect"]
    results = [run_case(c, ref, command) for c in cases]
    data = {"kind": "harness-self-check" if args.self_check else "native-parity", "reference": ref.fingerprint,
            "passed": bool(results) and all(r["passed"] for r in results), "cases": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"kind": data["kind"], "passed": data["passed"], "cases": len(results), "failures": [r["id"] for r in results if not r["passed"]]}))
    return int(not data["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
