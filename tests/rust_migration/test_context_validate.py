"""Context acceptance must retain complete prior gates and exact native identity."""
from copy import deepcopy
import json
from pathlib import Path

from tools.rust_migration.context_validate import CONTEXT_KEYS, CONTEXT_GATES, aggregate_contexts
from tools.rust_migration.context_compare import RUNTIME,core_for_platform
from tools.rust_migration.table_validate import TABLE_KEYS,TABLE_GATES


def test_context_matrix_rejects_stale_base_wrong_core_and_missing_proof(tmp_path):
    registration=json.loads((Path(__file__).resolve().parents[2]/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json').read_text())
    def row(system,arch):
        base={'scope':'table-local','platform':system,'architecture':arch,'passed':True,'M2_accepted':False,
            'fingerprints':{k:'a'*64 for k in TABLE_KEYS},'rustc':'rustc 1.95.0 (same)',
            'case_ids':['table'],'gates':{g:{'ran':True,'passed':True} for g in TABLE_GATES},
            'table_release':{'ran':True,'passed':True,'built_sha256':'b'*64,'supplied_sha256':'b'*64},
            'table_parity':{'passed':True,'outside_checkout':True,'native_children':[],
                'dependency_audit':{'passed':True},'exec_attempts':1,'native_sha256':'b'*64}}
        return {'scope':'context-local','platform':system,'architecture':arch,'passed':True,'M2_accepted':False,
            'fingerprints':{k:'a'*64 for k in CONTEXT_KEYS},'rustc':base['rustc'],'table_base':base,
            'case_ids':['one'],'gates':{g:{'ran':True,'passed':True} for g in CONTEXT_GATES},
            'context_release':{'ran':True,'passed':True,'built_sha256':'c'*64,'supplied_sha256':'c'*64},
            'context_parity':{'passed':True,'outside_checkout':True,'native_children':[],
                'dependency_audit':{'passed':True},'core_dependency_audit':{'passed':True},
                'exec_attempts':1,'native_sha256':'c'*64,'core_identity':core_for_platform(registration,system,arch),
                'runtime':RUNTIME|{'native_core':core_for_platform(registration,system,arch)},'stderr':'','stderr_warning_count':0}}
    mac=row('Darwin','arm64');linux=row('Linux','aarch64')
    def write(rows):
        for path in tmp_path.glob('*/summary.json'):path.unlink()
        for index,value in enumerate(rows):
            path=tmp_path/str(index)/'summary.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(value))
        return aggregate_contexts(tmp_path,expected_ids=['one'],table_case_ids=['table'],
            expected_fingerprints={k:'a'*64 for k in CONTEXT_KEYS})
    assert write([mac,linux])['Context_accepted'] is True
    assert write([mac,linux])['M2_accepted'] is False
    assert not write([mac])['passed'] and not write([mac,mac])['passed']
    stale_mac,stale_linux=deepcopy(mac),deepcopy(linux)
    for value in [stale_mac,stale_linux]:
        value['fingerprints']['native_source']='0'*64
        value['table_base']['fingerprints']['native_source']='0'*64
    assert not write([stale_mac,stale_linux])['passed'], 'matching stale receipts are not current-source acceptance'
    for gate in CONTEXT_GATES:
        bad=deepcopy(linux);bad['gates'][gate]['passed']=False;assert not write([mac,bad])['passed']
    for key in CONTEXT_KEYS:
        bad=deepcopy(linux);bad['fingerprints'][key]='0'*64;assert not write([mac,bad])['passed']
    for key,value in [('sha256','0'*64),('version','1.25.2'),('os','macos'),('api',31)]:
        bad=deepcopy(linux);bad['context_parity']['core_identity'][key]=value;assert not write([mac,bad])['passed']
    for key,value in [('outside_checkout',False),('native_children',['python']),('exec_attempts',2),
                      ('dependency_audit',{'passed':False}),('core_dependency_audit',{'passed':False}),
                      ('native_sha256','0'*64)]:
        bad=deepcopy(linux);bad['context_parity'][key]=value;assert not write([mac,bad])['passed']
    for mutate in ['basegate','basehash','binding','execution_error','ids']:
        bad=deepcopy(linux)
        if mutate=='basegate':bad['table_base']['gates']['rust_tests']['passed']=False
        elif mutate=='basehash':bad['table_base']['fingerprints']['native_source']='0'*64
        elif mutate=='binding':bad['context_release']['supplied_sha256']='0'*64
        elif mutate=='ids':bad['case_ids']=[]
        else:bad['execution_error']='interrupted'
        assert not write([mac,bad])['passed'],mutate
