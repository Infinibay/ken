"""Acceptance policy: incomplete evidence or equal failure counts cannot pass."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED_GATES=("originals","reference","inventory","toolchain","python_contracts","python_full","typing",
                "fmt","clippy","rust_tests","release","parity_tests","parity","runtime","benchmark","hygiene")

def assess_gates(receipts: dict,execution_error=None) -> list[str]:
    if not isinstance(receipts,dict): return ["invalid gate receipts"]
    return (["execution_error"] if execution_error else [])+[name for name in REQUIRED_GATES if not isinstance(receipts.get(name),dict)
            or receipts[name].get("ran") is not True or receipts[name].get("passed") is not True]

def assess_parity(report: dict, expected_ids: list[str], reference: str) -> list[str]:
    errors=[]
    if report.get("kind")!="native-parity" or report.get("reference")!=reference or report.get("passed") is not True:
        errors.append("not a successful native-parity receipt for this reference")
    rows=report.get("cases",[])
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows): return errors+["invalid cases"]
    ids=[r.get("id") for r in rows]
    if not ids or len(set(ids))!=len(ids) or set(ids)!=set(expected_ids): errors.append("missing, duplicate or unexpected case IDs")
    if any(r.get("passed") is not True or r.get("errors")!=[] or r.get("native_children")!=[] for r in rows): errors.append("failed or incomplete case")
    return errors

def junit_states(path: Path) -> dict[str,str]:
    root=ET.parse(path).getroot();states={}
    for test in root.iter("testcase"):
        key=f"{test.get('classname')}::{test.get('name')}"
        if key in states: raise ValueError(f"duplicate test ID: {key}")
        states[key]=next((tag for tag in ["error","failure","skipped"] if test.find(tag) is not None),"passed")
    if not states: raise ValueError("empty JUnit receipt")
    return states

def compare_python(baseline: Path, final: Path, extra_known_failures=()) -> dict:
    before=junit_states(baseline);after=junit_states(final)
    legacy=lambda key:not key.startswith("tests.rust_migration.")
    previous={key for key,state in before.items() if state in {"error","failure"} and legacy(key)}
    known=previous|{key for key in extra_known_failures if legacy(key)}
    failed={key for key,state in after.items() if state in {"error","failure"}}
    new_failures=sorted(failed-known)
    new_skips=sorted(key for key,state in after.items() if state=="skipped" and before.get(key)!="skipped")
    missing=sorted(key for key in before if legacy(key) and key not in after)
    return {"passed":not(new_failures or new_skips or missing),"collected":len(after),
            "new_failures":new_failures,"new_skips":new_skips,"missing_tests":missing,
            "previous_failures":{key:after.get(key,"not collected") for key in sorted(known)},
            "current_failures":sorted(failed)}

def aggregate_platforms(directory: Path | None) -> dict:
    errors=[];rows=[]
    if directory:
        for path in sorted(directory.rglob("summary.json")):
            try:
                row=json.loads(path.read_text())
                if not isinstance(row,dict): raise ValueError("receipt must be an object")
                if row.get("scope")=="local": rows.append(row)
            except (OSError,ValueError): errors.append(f"unreadable platform receipt: {path.name}")
    if sorted(r.get("platform","") for r in rows)!=["Darwin","Linux"]: errors.append("exactly one Linux and one macOS receipt required")
    signatures=[]
    for row in rows:
        if row.get("passed") is not True or assess_gates(row.get("gates",{}),row.get("execution_error")): errors.append(f"incomplete local receipt: {row.get('platform')}")
        fingerprints=row.get("fingerprints",{})
        if set(fingerprints)!={"native_source","reference_source","cases","validator"} or any(not isinstance(v,str) or len(v)!=64 for v in fingerprints.values()): errors.append("missing source identities")
        signatures.append((fingerprints,row.get("rustc")))
        if not str(row.get("rustc","")).startswith("rustc 1.95.0 "): errors.append("unexpected Rust toolchain")
        if row.get("platform")=="Linux" and not all(row.get("trace_exec",{}).get(k) is True for k in ["ran","passed"]): errors.append("Linux exec trace missing or failed")
    if signatures and any(signature!=signatures[0] for signature in signatures): errors.append("platform sources, cases, validator or toolchain differ")
    return {"scope":"matrix","passed":not errors and len(rows)==2,"errors":errors,
            "platforms":[r.get("platform") for r in rows],"M1_matrix_accepted":not errors and len(rows)==2}
