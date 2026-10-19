"""Compose complete prior evidence; matching stale receipts cannot close Ettin."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tools.rust_migration.context_validate import CONTEXT_KEYS, CONTEXT_GATES, context_receipt_errors
from tools.rust_migration.ettin_compare import RUNTIME
from tools.rust_migration.ettin_validate import ETTIN_KEYS, ETTIN_GATES, aggregate_ettins

ROOT=Path(__file__).resolve().parents[2]


def test_ettin_matrix_retains_all23gates_native_preparation_and_current_source_binding(tmp_path):
    document=json.loads((ROOT/'docs/validation/rust-migration-2026-10-19/m2-ettin/reference.json').read_text())
    def row(system,arch,folder):
        base=json.loads((ROOT/f'docs/validation/rust-migration-2026-10-18/m2-context/{folder}/summary.json').read_text())
        golden=document['platforms'][f'{system}/{arch}']
        parity={'format':'ken-ettin-parity/1','platform':system,'architecture':arch,
            'passed':True,'errors':[],'M2_accepted':False,'native_exit':0,'native_wall_ns':1,
            'outside_checkout':True,'native_children':[],
            'dependency_audit':{'passed':True},'core_dependency_audit':{'passed':True},
            'exec_attempts':1,'native_sha256':'d'*64,'case_ids':['ettin'],
            'core_identity':base['context_parity']['core_identity'],
            'runtime':RUNTIME|{'native_core':base['context_parity']['core_identity']},
            'reference_runtime':golden['oracle']['runtime'],'stderr':'','stderr_warning_count':0,
            'preparation':{'fresh_cache':True,'reused_without_source':True,
                'artifacts':golden['artifacts'],'source_artifacts':golden['source_artifacts'],
                'recipe_key':hashlib.sha256(json.dumps(golden['definition'],sort_keys=True).encode()).hexdigest()}}
        return {'scope':'ettin-local','platform':system,'architecture':arch,'passed':True,'M2_accepted':False,
            'fingerprints':base['fingerprints']|{k:'e'*64 for k in ETTIN_KEYS-CONTEXT_KEYS},
            'rustc':base['rustc'],'case_ids':['ettin'],'context_base':base,
            'gates':deepcopy(base['gates'])|{g:{'ran':True,'passed':True} for g in ETTIN_GATES if g not in CONTEXT_GATES},
            'ettin_release':{'ran':True,'passed':True,'built_sha256':'d'*64,'supplied_sha256':'d'*64},
            'ettin_parity':parity}
    mac=row('Darwin','arm64','macos');linux=row('Linux','aarch64','linux')
    fingerprints=deepcopy(mac['fingerprints'])
    assert len(ETTIN_GATES)==23
    assert context_receipt_errors(mac['context_base'],expected_fingerprints={k:fingerprints[k] for k in CONTEXT_KEYS})==[]
    def write(rows,current=fingerprints):
        for path in tmp_path.glob('*/summary.json'):path.unlink()
        for index,value in enumerate(rows):
            path=tmp_path/str(index)/'summary.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(value))
        return aggregate_ettins(tmp_path,expected_ids=['ettin'],expected_fingerprints=current)
    assert write([mac,linux])['Ettin_accepted'] is True
    assert write([mac,linux])['M2_accepted'] is False
    assert not write([mac])['passed'] and not write([mac,mac])['passed']
    assert not write([mac,linux],None)['passed'], 'historical matching receipts are not current-source proof'
    for gate in ETTIN_GATES:
        bad=deepcopy(linux);bad['gates'][gate]['passed']=False
        assert not write([mac,bad])['passed'],gate
    for key in ETTIN_KEYS:
        bad=deepcopy(linux);bad['fingerprints'][key]='0'*64
        assert not write([mac,bad])['passed'],key
    for mutate in ['binding','core','fresh','reuse','recipe','artifacts','source','children','exec','stderr','cases',
                   'runtime','basegate','basehash','basescope','basecore','execution_error','globalM2']:
        bad=deepcopy(linux);parity=bad['ettin_parity'];base=bad['context_base']
        if mutate=='binding':bad['ettin_release']['supplied_sha256']='0'*64
        elif mutate=='core':parity['core_identity']=parity['core_identity']|{'sha256':'0'*64}
        elif mutate=='fresh':parity['preparation']['fresh_cache']=False
        elif mutate=='reuse':parity['preparation']['reused_without_source']=False
        elif mutate=='recipe':parity['preparation']['recipe_key']='0'*64
        elif mutate=='artifacts':parity['preparation']['artifacts']={}
        elif mutate=='source':parity['preparation']['source_artifacts']={}
        elif mutate=='children':parity['native_children']=['python']
        elif mutate=='exec':parity['exec_attempts']=2
        elif mutate=='stderr':parity['stderr']='unexpected warning\n'
        elif mutate=='cases':parity['case_ids']=[]
        elif mutate=='runtime':parity['runtime']['cpu_arena']=False
        elif mutate=='basegate':base['gates']['rust_tests']['passed']=False
        elif mutate=='basehash':base['fingerprints']['native_source']='0'*64
        elif mutate=='basescope':base['scope']='other'
        elif mutate=='basecore':base['context_parity']['core_identity']['sha256']='0'*64
        elif mutate=='execution_error':bad['execution_error']='interrupted'
        else:bad['M2_accepted']=True
        assert not write([mac,bad])['passed'],mutate
