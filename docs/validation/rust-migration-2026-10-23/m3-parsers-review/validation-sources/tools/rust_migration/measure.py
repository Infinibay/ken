"""Fresh-process wall time and kernel maximum RSS, including failed samples."""
from __future__ import annotations

import contextlib
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .compare import _differences
from .fixtures import build_fixture
from .reference import Reference,reference_env

SCENARIOS=("metadata_only","installed_empty","populated")

def summarize_samples(samples: list[dict]) -> dict:
    errors=[];metrics={}
    expected={(engine,scenario) for engine in ["python","native"] for scenario in SCENARIOS}
    if any((s.get("engine"),s.get("scenario")) not in expected for s in samples): errors.append("unexpected sample group")
    for engine,scenario in sorted(expected):
        group=[s for s in samples if s.get("engine")==engine and s.get("scenario")==scenario]
        if len(group)!=30 or any(s.get("exit")!=0 or s.get("errors") or s.get("timeout") or
                any(type(s.get(k)) is not int or s[k]<=0 for k in ["duration_ns","rss_bytes"]) for s in group):
            errors.append(f"incomplete/failed samples: {engine}/{scenario}");continue
        durations=sorted(s["duration_ns"] for s in group)
        metrics[f"{engine}/{scenario}"]={"samples":len(group),"median_ns":statistics.median(durations),
            "p95_ns":durations[math.ceil(.95*len(group))-1],"max_ns":max(durations),"max_rss_bytes":max(s["rss_bytes"] for s in group)}
    return {"passed":not errors,"errors":errors,"metrics":metrics,"samples":samples}

def _measure(argv: list[str],cwd: Path,env: dict) -> dict:
    with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
        started=time.monotonic_ns();process=subprocess.Popen(argv,cwd=cwd,env=env,stdout=stdout,stderr=stderr)
        expired=threading.Event()
        def kill():
            expired.set()
            try: process.kill()
            except OSError: pass
        timer=threading.Timer(10,kill);timer.start()
        try:
            _,status,usage=os.wait4(process.pid,0)
            elapsed=time.monotonic_ns()-started
            process.returncode=os.waitstatus_to_exitcode(status)
        finally: timer.cancel()
        stdout.seek(0);stderr.seek(0)
        return {"exit":process.returncode,"duration_ns":elapsed,"rss_bytes":int(usage.ru_maxrss)*(1 if platform.system()=="Darwin" else 1024),
                "timeout":expired.is_set(),"stdout":stdout.read().decode(),"stderr":stderr.read().decode()}

def benchmark(reference: Reference,native: Path) -> dict:
    samples=[];preparation_ns=0;mutations=[]
    with tempfile.TemporaryDirectory(prefix="ken-status-measure-") as directory:
        root=Path(directory);empty=root/"empty-path";empty.mkdir()
        for scenario in SCENARIOS:
            started=time.monotonic_ns()
            with contextlib.ExitStack() as stack:
                fixtures={engine:stack.enter_context(build_fixture(root/f"{scenario}-{engine}",scenario,reference)) for engine in ["python","native"]}
                envs={engine:reference_env(reference,root/f"env-{engine}") for engine in fixtures};envs["native"]["PATH"]=str(empty)
                commands={"python":[str(reference.python),"-m","ken"],"native":[str(native)]}
                preparation_ns+=time.monotonic_ns()-started
                for index in range(30):
                    for engine in (["python","native"] if index%2==0 else ["native","python"]):
                        fixture=fixtures[engine]
                        result=_measure([*commands[engine],"status",str(fixture.root),"--json"],root,envs[engine])
                        errors=[]
                        try: errors=_differences(fixture.expected_report,json.loads(result["stdout"]))
                        except ValueError: errors=["invalid JSON"]
                        if result["stderr"]: errors.append("unexpected stderr")
                        samples.append({"engine":engine,"scenario":scenario,"index":index,**{k:v for k,v in result.items() if k not in {"stdout","stderr"}},"errors":errors})
                for engine,fixture in fixtures.items(): mutations.extend(f"{scenario}/{engine}:{field}" for field in fixture.changed())
    report=summarize_samples(samples)
    report.update(preparation_ns=preparation_ns,model="not applicable",rss="kernel wait4 maximum per process; bytes",wall="monotonic spawn through wait4 completion; includes watchdog setup",mutations=mutations)
    report["passed"]=report["passed"] and not mutations
    return report
