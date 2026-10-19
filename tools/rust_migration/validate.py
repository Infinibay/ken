"""Reproducible M0/M1 gates. Local acceptance never implies a platform matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from xml.etree.ElementTree import ParseError as ETError
from pathlib import Path

from .compare import _differences,run_process
from .fixtures import build_fixture
from .inventory import audit_ownership
from .measure import benchmark,summarize_samples
from .receipts import REQUIRED_GATES,aggregate_platforms,assess_gates,assess_parity,compare_python
from .reference import Reference,reference_env,verify_reference,_files
from .preparation import PreparedNativeContext,context_environment

def _write(path: Path,data: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,indent=2)+"\n")

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def bind_native_release(repo:Path,native:Path,example:str)->dict:
    built=repo/'target/release/examples'/example
    result={'ran':True,'passed':False,'built':str(built),'supplied':str(native)}
    try:
        result.update(built_sha256=_sha(built),supplied_sha256=_sha(native))
        result['passed']=result['built_sha256']==result['supplied_sha256']
        if not result['passed']:result['error']='supplied probe differs from fresh release'
    except OSError as error:result['error']=str(error)
    return result

def _digest(rows) -> str:
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()

def _fingerprints(repo: Path,reference: Reference|None,cases: Path) -> dict:
    native=[repo/n for n in ["Cargo.toml","Cargo.lock","rust-toolchain.toml"]]
    native+=sorted(p for p in (repo/"crates").rglob("*") if p.is_file() and (p.suffix==".rs" or p.name=="Cargo.toml"))
    validator=sorted(p for folder in ["tools/rust_migration","migration_tests","tests/rust_migration"] for p in (repo/folder).rglob("*.py"))
    rows=lambda paths:[{"path":p.relative_to(repo).as_posix(),"sha256":_sha(p)} for p in paths]
    if reference is None:
        source=rows([p for p in _files(repo) if p.relative_to(repo).as_posix().startswith('src/ken/')])
    else:
        source=[row for row in json.loads(reference.manifest_path.read_text())["files"] if row["path"].startswith("src/ken/")]
    return {"native_source":_digest(rows(native)),"reference_source":_digest(source),"cases":_sha(cases),"validator":_digest(rows(validator))}

def _command(repo: Path,env: dict,output: Path,name: str,argv: list[str],timeout_s=600) -> dict:
    path=output/f"{name}.log";started=time.monotonic_ns()
    try:
        with path.open("w") as log:
            try: code=subprocess.run(argv,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout_s).returncode
            except subprocess.TimeoutExpired: log.write("\nvalidation command timed out\n");code=124
        return {"ran":True,"passed":code==0,"exit":code,"command":argv,"duration_ns":time.monotonic_ns()-started,"artifact":path.name,"sha256":_sha(path)}
    except OSError as error:
        return {"ran":False,"passed":False,"command":argv,"error":str(error)}

def _verify(repo: Path,manifest: Path) -> dict:
    try:
        changed=verify_reference(repo,manifest)
        return {"ran":True,"passed":not changed,"details":{"changed":changed,"manifest_sha256":_sha(manifest)}}
    except (OSError,ValueError,KeyError) as error:
        return {"ran":True,"passed":False,"error":str(error)}

def _typing_errors(path: Path) -> set[str]:
    return {line for line in path.read_text().splitlines() if re.match(r".+:\d+: error: .+ \[[^]]+\]$",line)}

def _rustc_version(path: Path) -> str:
    versions = [line for line in path.read_text().splitlines() if line.startswith("rustc ")]
    return versions[0] if len(versions) == 1 else ""

def _inventory(repo,reference,env,output,baseline_dir):
    candidates=[baseline_dir/"inventory",repo/"docs/validation/rust-migration-2026-10-18/m0"]
    chosen=None
    for path in candidates:
        try:
            data=json.loads((path/"capture.json").read_text())
            if data.get("reference")==reference.fingerprint and data.get("passed") is True: chosen=path;break
        except (OSError,ValueError): pass
    receipt={"ran":True,"passed":False}
    if chosen is None:
        chosen=output/"inventory"
        receipt=_command(repo,env,output,"inventory",[str(reference.python),"-m","tools.rust_migration.inventory","--reference",str(reference.root),"--out",str(chosen)])
        if not receipt["passed"]: return receipt
    try:
        capture=json.loads((chosen/"capture.json").read_text());owners=json.loads((chosen/"source-owners.json").read_text())
        cli=json.loads((chosen/"cli.json").read_text());mcp=json.loads((chosen/"mcp.json").read_text())
        errors=audit_ownership(reference,owners)
        receipt["passed"]=capture.get("passed") is True and capture.get("reference")==reference.fingerprint and not errors and bool(cli["routes"]) and bool(mcp["tools"]) and mcp["transport"]=="stdio"
        receipt["details"]={"source":str(chosen),"capture_sha256":_sha(chosen/"capture.json"),"routes":len(cli["routes"]),"tools":len(mcp["tools"]),"sources":len(owners),"errors":errors}
    except (OSError,ValueError,KeyError) as error: receipt.update(passed=False,error=str(error))
    return receipt

def _runtime(repo,reference,native,env,output,trace_exec):
    system=platform.system();trace={"ran":False,"passed":False,"platform":system}
    linked=_command(repo,env,output,"native-dependencies",["otool","-L",str(native)] if system=="Darwin" else ["ldd",str(native)])
    tree=_command(repo,env,output,"native-cargo-tree",["cargo","tree","--locked","--workspace","-e","normal"])
    linked_text=(output/"native-dependencies.log").read_text() if linked.get("ran") else ""
    tree_text=(output/"native-cargo-tree.log").read_text() if tree.get("ran") else ""
    errors=[]
    if not linked.get("passed") or not tree.get("passed") or re.search(r"libpython|pyo3|cpython",linked_text+tree_text,re.I): errors.append("native dependency audit failed")
    with tempfile.TemporaryDirectory(prefix="ken-native-outside-") as directory:
        root=Path(directory);copied=root/"ken-rs";shutil.copy2(native,copied);empty=root/"empty-path";empty.mkdir()
        isolated=reference_env(reference,root/"env");isolated["PATH"]=str(empty)
        with build_fixture(root/"data","populated",reference) as fixture:
            result=run_process([str(copied),"status",str(fixture.root),"--json"],root,isolated,10)
            try: errors+=_differences(fixture.expected_report,json.loads(result.stdout))
            except ValueError: errors.append("invalid report outside checkout")
            if result.returncode!=0 or result.stderr or fixture.changed(): errors.append("outside-checkout execution or integrity failed")
            if system=="Linux" and trace_exec:
                executable=shutil.which("strace")
                if executable:
                    trace=_command(repo,isolated,output,"native-trace-output",[executable,"-f","-e","trace=execve,execveat","-o",str(output/"native-exec.trace"),str(copied),"status",str(fixture.root),"--json"])
                    lines=[line for line in (output/"native-exec.trace").read_text().splitlines() if re.search(r"\bexecve(?:at)?\(",line)]
                    trace["exec_attempts"]=len(lines);trace["passed"]=trace["passed"] and len(lines)==1 and str(copied) in lines[0]
                else: trace={"ran":False,"passed":False,"error":"strace is required on Linux"}
    if system=="Linux" and trace.get("passed") is not True: errors.append("Linux exec trace missing or failed")
    return {"ran":True,"passed":not errors,"details":{"errors":errors,"dependency_audit":linked,"cargo_tree":tree,"copied_binary":True,"path_contains_python":False}},trace

def _validation_environment(reference: Reference, repo: Path, output: Path, native: Path,*,context:PreparedNativeContext|None=None) -> dict:
    env=reference_env(reference,output/"environment")
    env["PYTHONPATH"]=os.pathsep.join([str(repo/"src"),str(repo)])
    env.pop("CARGO_TARGET_DIR",None);env.pop("CARGO_BUILD_TARGET",None)
    env.update(KEN_RUST_BIN=str(native),KEN_RUST_REFERENCE=str(reference.root))
    for key in ["KEN_POTION_SNAPSHOT","KEN_MODEL_PROBE","KEN_TABLE_PROBE"]:
        if key in os.environ: env[key]=os.environ[key]
    env.update(context_environment(context))
    return env

def run(repo: Path,reference: Reference,native: Path,output: Path,scope: str="local",platform_receipts: Path|None=None,trace_exec: bool=False,*,original_manifest: Path|None=None,baseline_dir: Path|None=None) -> int:
    repo=repo.resolve();output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    _write(output/"summary.json",{"scope":scope,"passed":False,"status":"running"})
    if scope=="matrix":
        result=aggregate_platforms(platform_receipts);_write(output/"summary.json",result);return int(not result["passed"])
    if scope!="local": raise ValueError("scope must be local or matrix")
    gates={};summary={"scope":"local","platform":platform.system(),"architecture":platform.machine(),"passed":False,"gates":gates,"reference":reference.fingerprint,"model":"not applicable"}
    original_manifest=original_manifest or repo/"docs/validation/rust-migration-2026-10-18/baseline.json"
    baseline_dir=baseline_dir or reference.root.parent
    cases=repo/"docs/validation/rust-migration-2026-10-18/m0/m1-cases.json"
    def finish():
        summary["errors"]=assess_gates(gates,summary.get("execution_error"));summary["passed"]=not summary["errors"]
        summary["M0_accepted"]=all(gates.get(k,{}).get("passed") is True for k in ["originals","reference","inventory","python_contracts"])
        summary["M1_local_accepted"]=summary["passed"];summary["M1_matrix_accepted"]=False
        _write(output/"summary.json",summary)
        return int(not summary["passed"])
    gates["originals"]=_verify(repo,original_manifest);gates["reference"]=_verify(reference.root,reference.manifest_path)
    if not gates["originals"]["passed"] or not gates["reference"]["passed"]: return finish()
    try:
        native=native.resolve();before=_fingerprints(repo,reference,cases);summary["fingerprints"]=before
        env=_validation_environment(reference,repo,output,native)
        py=[str(reference.python),"-m"]
        gates["toolchain"]=_command(repo,env,output,"rust-toolchain",["rustc","--version","--verbose"])
        summary["rustc"]=_rustc_version(output/"rust-toolchain.log") if gates["toolchain"].get("ran") else ""
        gates["toolchain"]["passed"]=gates["toolchain"]["passed"] and summary["rustc"].startswith("rustc 1.95.0 ")
        gates["inventory"]=_inventory(repo,reference,env,output,baseline_dir)
        gates["python_contracts"]=_command(repo,env,output,"python-contracts",[*py,"pytest","tests/test_paths.py","tests/test_status.py","tests/rust_migration","-q"])
        final=output/"python-final.xml"
        gates["python_full"]=_command(repo,env,output,"python-full",[*py,"pytest",f"--junitxml={final}"],3600)
        known=json.loads((repo/"docs/validation/rust-migration-2026-10-18/m0/baseline-results.json").read_text()).get("diagnostic_rerun",{}).get("original_failures",[])
        comparison=compare_python(baseline_dir/"python-baseline.xml",final,known)
        gates["python_full"].update(passed=gates["python_full"].get("exit") in [0,1] and comparison["passed"],details=comparison)
        gates["typing"]=_command(repo,env,output,"python-typing",[*py,"mypy","--no-incremental"])
        old_errors=_typing_errors(baseline_dir/"mypy-baseline.log");current=_typing_errors(output/"python-typing.log")
        gates["typing"].update(passed=gates["typing"].get("exit") in [0,1] and not(current-old_errors) and (bool(current) or gates["typing"].get("exit")==0),details={"previous_errors":sorted(old_errors),"current_errors":sorted(current),"new_errors":sorted(current-old_errors)})
        for name,argv in [("fmt",["cargo","fmt","--all","--","--check"]),("clippy",["cargo","clippy","--locked","--workspace","--all-targets","--","-D","warnings"]),("rust_tests",["cargo","test","--locked","--workspace"]),("release",["cargo","build","--release","--locked","-p","ken-cli"])]:
            gates[name]=_command(repo,env,output,name,argv)
        ignored=re.findall(r"; (\d+) ignored;",(output/"rust_tests.log").read_text())
        gates["rust_tests"]["passed"]=gates["rust_tests"]["passed"] and bool(ignored) and all(int(n)==0 for n in ignored)
        built=repo/"target/release/ken-rs";gates["release"]["passed"]=gates["release"]["passed"] and built.is_file() and native.is_file() and _sha(built)==_sha(native)
        if gates["release"]["passed"]:
            summary["native_sha256"]=_sha(native)
            gates["parity_tests"]=_command(repo,env,output,"parity-tests",[*py,"pytest","migration_tests","-q",f"--junitxml={output/'parity-tests.xml'}"])
            gates["parity"]=_command(repo,env,output,"parity",[*py,"tools.rust_migration.compare","--reference",str(reference.root),"--native",str(native),"--cases",str(cases),"--out",str(output/"parity.json")])
            result=json.loads((output/"parity.json").read_text());expected=[row["id"] for row in json.loads(cases.read_text())["cases"]]
            errors=assess_parity(result,expected,reference.fingerprint);gates["parity"].update(passed=gates["parity"]["passed"] and not errors,details={"errors":errors,"expected":len(expected),"observed":len(result.get("cases",[]))})
            gates["runtime"],summary["trace_exec"]=_runtime(repo,reference,native,env,output,trace_exec)
            result=benchmark(reference,native);_write(output/"benchmark.json",result)
            gates["benchmark"]={"ran":True,"passed":result["passed"],"artifact":"benchmark.json","sha256":_sha(output/"benchmark.json")}
        gates["hygiene"]=_command(repo,env,output,"hygiene",["git","diff","--check"])
        gates["hygiene"]["passed"]=gates["hygiene"]["passed"] and before==_fingerprints(repo,reference,cases)
        gates["originals"]=_verify(repo,original_manifest);gates["reference"]=_verify(reference.root,reference.manifest_path)
    except (OSError,ValueError,KeyError,IndexError,ETError) as error:
        summary["execution_error"]=f"{type(error).__name__}: {error}"
    return finish()

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference",type=Path);parser.add_argument("--native",type=Path)
    parser.add_argument("--out",type=Path,required=True);parser.add_argument("--scope",choices=["local","matrix"],default="local")
    parser.add_argument("--platform-receipts",type=Path);parser.add_argument("--trace-exec",action="store_true")
    parser.add_argument("--original-manifest",type=Path);parser.add_argument("--baseline-dir",type=Path)
    args=parser.parse_args();repo=Path.cwd()
    if args.scope=="local" and (not args.reference or not args.native): parser.error("local scope requires --reference and --native")
    ref=Reference.load(args.reference) if args.scope=="local" else Reference(repo,repo/"unused","",Path(sys.executable))
    result=run(repo,ref,args.native or repo/"unused",args.out,args.scope,args.platform_receipts,args.trace_exec,original_manifest=args.original_manifest,baseline_dir=args.baseline_dir)
    summary=json.loads((args.out/"summary.json").read_text());print(json.dumps({"scope":args.scope,"passed":summary["passed"],"errors":summary.get("errors",[])}));return result

if __name__=="__main__": raise SystemExit(main())
