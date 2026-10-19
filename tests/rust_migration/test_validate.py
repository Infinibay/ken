import hashlib
import json
import sys
import xml.etree.ElementTree as E
from pathlib import Path

from tools.rust_migration.reference import Reference
from tools.rust_migration.validate import REQUIRED_GATES,assess_gates,assess_parity,compare_python,run,summarize_samples


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data));return path

def junit(path,states):
    suite=E.Element("testsuite")
    for name,state in states:
        t=E.SubElement(suite,"testcase",classname="tests.legacy",name=name)
        if state!="passed": E.SubElement(t,state)
    E.ElementTree(suite).write(path)

def receipts():
    return {name:{"ran":True,"passed":True} for name in REQUIRED_GATES}

def local(platform):
    return {"scope":"local","platform":platform,"passed":True,"gates":receipts(),
            "fingerprints":{name:"a"*64 for name in ["native_source","reference_source","cases","validator"]},
            "rustc":"rustc 1.95.0 (fixture)","trace_exec":{"ran":platform=="Linux","passed":platform=="Linux"}}

def test_missing_or_failed_receipt_cannot_pass():
    assert assess_gates(receipts())==[]
    assert assess_gates(receipts(),execution_error="input disappeared during validation")
    for key in REQUIRED_GATES:
        for broken in [None,{"ran":False,"passed":True},{"ran":True,"passed":False}]:
            data=receipts()
            if broken is None: del data[key]
            else: data[key]=broken
            assert assess_gates(data)
    assert assess_parity({"kind":"native-parity","passed":True,"reference":"r","cases":[]},["one"],"r")
    assert assess_parity({"kind":"harness-self-check","passed":True,"reference":"r","cases":[{"id":"one","passed":True,"errors":[]}]},["one"],"r")


def test_rustup_notices_do_not_replace_the_compiler_identity(tmp_path):
    from tools.rust_migration import validate

    log = tmp_path / "rust-toolchain.log"
    version = "rustc 1.95.0 (59807616e 2026-04-14)"
    log.write_text("info: syncing channel updates\nwarn: auto-installed\n" + version + "\nrelease: 1.95.0\n")
    assert validate._rustc_version(log) == version
    log.write_text("info: compiler installation failed\n")
    assert validate._rustc_version(log) == ""
    log.write_text(version + "\nrustc 1.99.1 (different compiler)\n")
    assert validate._rustc_version(log) == ""

def test_reference_drift_blocks_promotion(tmp_path,monkeypatch):
    from tools.rust_migration import validate
    repo=tmp_path/"repo";source=repo/"src/ken/a.py";source.parent.mkdir(parents=True);source.write_text("OLD=1\n")
    manifest=write_json(repo/"reference-manifest.json",{"fingerprint":"r","files":[{"path":"src/ken/a.py","sha256":hashlib.sha256(source.read_bytes()).hexdigest()}],"scope":["src/ken/**"]})
    ref=Reference(repo,manifest,"r",Path(sys.executable));source.write_text("CHANGED=1\n")
    monkeypatch.setattr(validate,"_command",lambda *a,**k: (_ for _ in ()).throw(AssertionError("external process after drift")))
    out=tmp_path/"receipt"
    assert run(repo,ref,tmp_path/"native",out,original_manifest=manifest)!=0
    summary=json.loads((out/"summary.json").read_text());assert summary["passed"] is False
    assert summary["gates"]["reference"]["details"]["changed"]==["src/ken/a.py"]

def test_original_failures_stay_visible(tmp_path):
    baseline=tmp_path/"baseline.xml";final=tmp_path/"final.xml"
    junit(baseline,[("old","failure"),("skip","skipped"),("okay","passed")])
    junit(final,[("old","failure"),("skip","skipped"),("okay","passed")])
    report=compare_python(baseline,final);assert report["passed"];assert report["previous_failures"]=={"tests.legacy::old":"failure"}
    junit(final,[("old","passed"),("skip","skipped"),("okay","passed"),("new","failure")])
    report=compare_python(baseline,final);assert not report["passed"];assert report["new_failures"]==["tests.legacy::new"]
    assert report["previous_failures"]=={"tests.legacy::old":"passed"}
    junit(final,[("old","failure"),("skip","skipped"),("okay","skipped")])
    assert not compare_python(baseline,final)["passed"]
    junit(final,[("old","passed")]);assert not compare_python(baseline,final)["passed"]

def test_incomplete_matrix_fails(tmp_path):
    data=tmp_path/"platforms";write_json(data/"mac/summary.json",local("Darwin"));out=tmp_path/"result"
    ref=Reference(tmp_path,tmp_path/"unused","r",Path(sys.executable))
    assert run(tmp_path,ref,tmp_path/"unused",out,scope="matrix",platform_receipts=data)!=0
    assert json.loads((out/"summary.json").read_text())["passed"] is False

def test_matrix_requires_comparable_sources_and_linux_trace(tmp_path):
    data=tmp_path/"platforms";write_json(data/"mac/summary.json",local("Darwin"));linux=local("Linux");path=write_json(data/"linux/summary.json",linux)
    ref=Reference(tmp_path,tmp_path/"unused","r",Path(sys.executable));out=tmp_path/"result"
    assert run(tmp_path,ref,tmp_path/"unused",out,scope="matrix",platform_receipts=data)==0
    linux["fingerprints"]["cases"]="b"*64;write_json(path,linux)
    assert run(tmp_path,ref,tmp_path/"unused",out,scope="matrix",platform_receipts=data)!=0
    linux=local("Linux");linux["trace_exec"]["ran"]=False;write_json(path,linux)
    assert run(tmp_path,ref,tmp_path/"unused",out,scope="matrix",platform_receipts=data)!=0

def test_benchmark_keeps_all_samples_and_uses_nearest_rank():
    samples=[{"engine":e,"scenario":s,"duration_ns":i,"rss_bytes":i,"exit":0} for e in ["python","native"] for s in ["metadata_only","installed_empty","populated"] for i in range(1,31)]
    report=summarize_samples(samples);assert report["passed"]
    assert report["metrics"]["native/populated"]=={"samples":30,"median_ns":15.5,"p95_ns":29,"max_ns":30,"max_rss_bytes":30}
    assert not summarize_samples(samples[:-1])["passed"]
    samples[-1]["exit"]=1;assert not summarize_samples(samples)["passed"]

def test_explicit_native_model_preparation_reaches_validation_only(tmp_path, monkeypatch):
    from tools.rust_migration.validate import _validation_environment
    ref=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    monkeypatch.setenv('KEN_POTION_SNAPSHOT','/prepared/pinned-revision')
    monkeypatch.setenv('KEN_MODEL_PROBE','/prepared/native-model-probe')
    monkeypatch.setenv('KEN_TABLE_PROBE','/prepared/native-table-probe')
    monkeypatch.setenv('KEN_PROJECT_ROOT','/unrelated/project')
    env=_validation_environment(ref,tmp_path,tmp_path/'output',tmp_path/'native')
    assert env['KEN_POTION_SNAPSHOT']=='/prepared/pinned-revision'
    assert env['KEN_MODEL_PROBE']=='/prepared/native-model-probe'
    assert env['KEN_TABLE_PROBE']=='/prepared/native-table-probe'
    assert env['KEN_RUST_BIN']==str(tmp_path/'native')
    assert 'KEN_PROJECT_ROOT' not in env
    from tools.rust_migration.reference import reference_env
    isolated=reference_env(ref,tmp_path/'oracle-env')
    assert 'KEN_POTION_SNAPSHOT' not in isolated and 'KEN_MODEL_PROBE' not in isolated
    assert 'KEN_TABLE_PROBE' not in isolated
