"""Mutation tests of receipt policy; fixture rows are not new runtime proof."""
from copy import deepcopy
import json
from pathlib import Path

from tools.rust_migration.policy_compare import GOLDEN,RUNTIME
from tools.rust_migration.policy_reference import policy_cases,policy_prompts
from tools.rust_migration.policy_validate import POLICY_GATES,POLICY_KEYS,aggregate_policies
from tools.rust_migration.translation_validate import TRANSLATION_GATES
from tools.rust_migration.validate import _sha

ROOT=Path(__file__).resolve().parents[2]


def test_policy_matrix_requires28_current_gates26_inputs_fresh_binary_and_recursive_prior_proof(tmp_path):
    ids=[c['id'] for c in policy_cases()];oracles=json.loads(GOLDEN.read_text())['oracles']
    def row(folder):
        base=json.loads((ROOT/f'docs/validation/rust-migration-2026-10-19/m2-translation/{folder}/summary.json').read_text())
        system=base['platform'];arch=base['architecture'];oracle=next(r for r in oracles if r['platform']==system)
        fingerprints=base['fingerprints']|{'policy_cases':_sha(GOLDEN.with_name('cases.json')),'policy_oracle':_sha(GOLDEN)}
        binding={'ran':True,'passed':True,'built_sha256':'d'*64,'supplied_sha256':'d'*64}
        parity={'format':'ken-model-policy-parity/1','platform':system,'architecture':arch,'passed':True,'errors':[],
            'M2_accepted':False,'native_exit':0,'native_wall_ns':1,'outside_checkout':True,'native_children':[],
            'dependency_audit':{'passed':True,'errors':[]},'exec_attempts':1,'native_sha256':'d'*64,
            'oracle_sha256':fingerprints['policy_oracle'],'cases_sha256':fingerprints['policy_cases'],
            'case_ids':ids,'prompt_models':policy_prompts(),'stderr':'','runtime':deepcopy(RUNTIME),
            'reference_oracle':oracle['oracle'],'reference_fingerprint':oracle['reference_fingerprint'],
            'reference_source_fingerprint':fingerprints['reference_source']}
        gates=deepcopy(base['gates'])|{'policy_release':binding,'policy_parity':{'ran':True,'passed':True}}
        return {'scope':'policy-local','platform':system,'architecture':arch,'passed':True,'M2_accepted':False,
            'fingerprints':fingerprints,'rustc':base['rustc'],'case_ids':ids,'translation_base':base,
            'gates':gates,'policy_release':binding,'policy_parity':parity}
    mac=row('macos');linux=row('linux');current=deepcopy(mac['fingerprints'])
    assert len(POLICY_KEYS)==26 and len(POLICY_GATES)==28
    def write(rows,fingerprints=current):
        for path in tmp_path.glob('*/summary.json'):path.unlink()
        for index,value in enumerate(rows):
            path=tmp_path/str(index)/'summary.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(value))
        return aggregate_policies(tmp_path,expected_fingerprints=fingerprints)
    assert write([mac,linux])['Policy_accepted'] is True
    assert write([mac,linux])['M2_accepted'] is False
    assert not write([mac])['passed'] and not write([mac,mac])['passed']
    assert not write([mac,linux],None)['passed']
    for gate in POLICY_GATES:
        bad=deepcopy(linux);bad['gates'][gate]['passed']=False
        assert not write([mac,bad])['passed'],gate
    for key in POLICY_KEYS:
        bad=deepcopy(linux);bad['fingerprints'][key]='0'*64
        assert not write([mac,bad])['passed'],key
    for change in ['binding','runtime','needed','stderr','exit','duration','exec','exec-type','children',
                   'oracle','cases','case_ids','prompts','reference','original-source','platform','architecture','basegate','baseinputs','baseproof','M2','interrupted']:
        bad=deepcopy(linux);p=bad['policy_parity'];base=bad['translation_base']
        if change=='binding':bad['policy_release']['supplied_sha256']='0'*64
        elif change=='runtime':p['runtime']['engine']='python'
        elif change=='needed':p['runtime']['model_runtime_needed']=0
        elif change=='stderr':p['stderr']='warning'
        elif change=='exit':p['native_exit']=False
        elif change=='duration':p['native_wall_ns']=True
        elif change=='exec':p['exec_attempts']=2
        elif change=='exec-type':p['exec_attempts']=True
        elif change=='children':p['native_children']=['python']
        elif change=='oracle':p['oracle_sha256']='0'*64
        elif change=='cases':p['cases_sha256']='0'*64
        elif change=='case_ids':p['case_ids']=[]
        elif change=='prompts':p['prompt_models']=[]
        elif change=='reference':p['reference_oracle']['sources']={}
        elif change=='original-source':p['reference_source_fingerprint']='0'*64
        elif change=='platform':p['platform']='Darwin'
        elif change=='architecture':bad['architecture']='x86_64'
        elif change=='basegate':base['gates']['rust_tests']['passed']=False
        elif change=='baseinputs':base['fingerprints']['native_source']='0'*64
        elif change=='baseproof':base['translation_parity']['native_children']=['python']
        elif change=='M2':bad['M2_accepted']=True
        else:bad['execution_error']='interrupted'
        assert not write([mac,bad])['passed'],change


def test_missing_policy_executable_fails_before_running_expensive_prior_suites(tmp_path,monkeypatch):
    from tools.rust_migration import policy_validate as pv
    from tools.rust_migration.preparation import PreparedNativeContext,PreparedNativeEttin,PreparedNativeTranslation
    from tools.rust_migration.reference import Reference
    import sys
    def forbidden(*args,**kwargs):raise AssertionError('missing policy probe must fail before prior suites')
    monkeypatch.setattr(pv,'validate_translation',forbidden)
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'library',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe')
    translation=PreparedNativeTranslation(tmp_path/'translation',tmp_path/'translation-probe')
    assert pv.validate_policy(tmp_path,reference,tmp_path/'model',tmp_path/'potion',tmp_path/'table',tmp_path/'table.npz',
        context,ettin,translation,tmp_path/'missing-probe',tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest')==1
    row=json.loads((tmp_path/'out/summary.json').read_text())
    assert row['passed'] is False and row['M2_accepted'] is False
    assert 'policy probe' in row['execution_error']
