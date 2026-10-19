"""Mutation tests of receipt policy; fixture rows are not new runtime proof."""
from copy import deepcopy
import json
from pathlib import Path
import hashlib
import pytest

from tools.rust_migration.policy_compare import GOLDEN,RUNTIME
from tools.rust_migration.policy_reference import policy_cases,policy_prompts
from tools.rust_migration.policy_validate import POLICY_GATES,POLICY_KEYS,aggregate_policies,policy_receipt_errors
from tools.rust_migration.translation_validate import TRANSLATION_GATES
from tools.rust_migration.validate import _sha

ROOT=Path(__file__).resolve().parents[2]


def _policy_row(folder):
    ids=[c['id'] for c in policy_cases()];oracles=json.loads(GOLDEN.read_text())['oracles']
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


def test_policy_receipts_require28_current_gates26_inputs_fresh_binary_and_recursive_prior_proof(tmp_path):
    ids=[c['id'] for c in policy_cases()]
    row=_policy_row
    mac=row('macos');linux=row('linux');current=deepcopy(mac['fingerprints'])
    assert len(POLICY_KEYS)==26 and len(POLICY_GATES)==28
    def write(rows,fingerprints=current):
        errors=[]
        if sorted((r['platform'],r['architecture']) for r in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:
            errors.append('missing platform')
        for value in rows:
            try:errors.extend(policy_receipt_errors(value,ids,fingerprints or {}))
            except (ValueError,TypeError,KeyError):errors.append('malformed receipt')
        return {'Policy_accepted':not errors,'M2_accepted':False,'passed':not errors}
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


@pytest.mark.parametrize('damage',['output','missing-output','missing-trace','missing-log','nested-summary',
    'manifest','summary-only','resealed-output','unlisted-trace','unlisted-nested','unsafe-path','symlink'])
def test_matrix_rejects_missing_or_altered_execution_files(tmp_path,damage):
    # These are receipt-policy fixtures, never evidence of an actual model run.
    rows=[_policy_row('macos'),_policy_row('linux')]
    for index,row in enumerate(rows):
        root=tmp_path/str(index);root.mkdir()
        _execution_fixture(root,row)
    current=rows[0]['fingerprints']
    assert aggregate_policies(tmp_path,expected_fingerprints=current)['Policy_accepted'] is True
    root=tmp_path/'1'
    if damage in ('output','resealed-output'):
        path=root/'policy-parity/native.stdout.json';data=json.loads(path.read_text())
        data['results'][0]['project']['model']='wrong/model';path.write_text(json.dumps(data))
    elif damage=='missing-output':(root/'policy-parity/native.stdout.json').unlink()
    elif damage=='missing-trace':(root/'policy-parity/native-exec.trace').unlink()
    elif damage=='missing-log':(root/'base/base/base/base/base/release.log').unlink()
    elif damage=='nested-summary':(root/'base/summary.json').write_text('{}')
    elif damage=='manifest':(root/'execution-artifacts.json').write_text('{}')
    elif damage=='summary-only':
        for path in root.rglob('*'):
            if path.is_file() and path!=root/'summary.json':path.unlink()
    elif damage in ('unlisted-trace','unlisted-nested'):
        (root/('policy-parity/native-exec.trace' if damage=='unlisted-trace' else 'base/summary.json')).unlink()
    elif damage=='symlink':
        path=root/'policy-parity/native.stdout.json';path.unlink();path.symlink_to(tmp_path/'0/policy-parity/native.stdout.json')
    if damage in ('resealed-output','unlisted-trace','unlisted-nested'):
        _fixture_manifest(root,rows[1])
    elif damage=='unsafe-path':
        path=root/'execution-artifacts.json';value=json.loads(path.read_text())
        value['files'][0]['path']='../outside.log';path.write_text(json.dumps(value))
        rows[1]['execution_artifacts']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        (root/'summary.json').write_text(json.dumps(rows[1]))
    result=aggregate_policies(tmp_path,expected_fingerprints=current)
    assert result['Policy_accepted'] is False,damage
    assert result['errors'],damage


def _execution_fixture(root,row):
    def write(path,data):
        target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode())
    node=row;prefix=Path();nodes=[]
    for kind,child in [('policy','translation_base'),('translation','ettin_base'),
                       ('ettin','context_base'),('context','table_base'),('table',None),('model',None)]:
        if kind=='model':
            from tools.rust_migration.model_validate import REQUIRED_GATES,FINGERPRINT_KEYS
            table=node
            node={'scope':'model-local','platform':row['platform'],'architecture':row['architecture'],
                  'passed':True,'M2_accepted':False,'rustc':row['rustc'],
                  'fingerprints':{k:row['fingerprints'][k] for k in FINGERPRINT_KEYS},
                  'gates':{k:deepcopy(table['gates'][k]) for k in REQUIRED_GATES},
                  'model_parity':{'passed':True}}
            prefix=prefix/'base'
        nodes.append((prefix,node))
        for gate in node['gates'].values():
            if 'sha256' in gate:gate['sha256']=hashlib.sha256(b'fixture log\n').hexdigest()
        parity=node[kind+'_parity'];folder=prefix/(kind+'-parity')
        for name in ['native.stdout.json','oracle.json']:write(folder/name,{})
        write(folder/'native.stderr.log',parity.get('stderr','').encode())
        linked=(b'probe:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1)\n' if row['platform']=='Darwin' else
                b'linux-vdso.so.1 (0x1)\nlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x1)\n/lib/ld-linux-aarch64.so.1 (0x1)\n')
        write(folder/'dependencies.log',linked);write(folder/'cargo-tree.log',b'ken-models\n')
        if row['platform']=='Linux':write(folder/'native-exec.trace',b'1 execve("/tmp/native", ["/tmp/native"], 0x0) = 0\n')
        if kind in ('policy','translation'):
            write(folder/'native.request.json',{});write(folder/'oracle.stderr.log',b'')
        if kind in ('ettin','context'):
            for name in ['dependencies.log','cargo-tree.log']:write(folder/'core-audit'/name,b'core audit\n')
        write(folder/'summary.json',parity)
        if child:node=node[child];prefix=prefix/'base'
    for gate in node['gates'].values():
        if 'artifact' in gate:write(prefix/gate['artifact'],b'fixture log\n' if 'sha256' in gate else {'passed':True})
    for name in ['python-final.xml','parity-tests.xml','m1-parity.json','benchmark/cases.json']:
        write(prefix/name,b'<testsuites/>\n' if name.endswith('.xml') else {})
    bench=prefix/'benchmark/processes'
    for name in ['summary.json','native.stdout.json','oracle.json']:write(bench/name,{'passed':True})
    for name in ['native.stderr.log','dependencies.log','cargo-tree.log']:write(bench/name,b'')
    if row['platform']=='Linux':write(bench/'native-exec.trace',b'1 execve("/tmp/native", [], 0x0) = 0\n')
    original=deepcopy(next(o for o in json.loads(GOLDEN.read_text())['oracles'] if o['platform']==row['platform']))
    original['reference_fingerprint']=row['policy_parity']['reference_fingerprint']
    write(Path('policy-parity/oracle.json'),original)
    write(Path('policy-parity/native.stdout.json'),{'format':'ken-model-policy-native/1','runtime':RUNTIME,
        'results':original['results'],'prompts':original['prompts']})
    cases=json.loads(GOLDEN.with_name('cases.json').read_text())
    write(Path('policy-parity/native.request.json'),{'cases':[{'id':c['id'],'input':c['input']} for c in cases['cases']],
        'prompts':cases['prompts']})
    for prefix,node in reversed(nodes):write(prefix/'summary.json',node)
    _fixture_manifest(root,row)


def _fixture_manifest(root,row):
    files=[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,
            'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
           for p in sorted(root.rglob('*')) if p.is_file() and p.name!='execution-artifacts.json' and p!=root/'summary.json']
    (root/'execution-artifacts.json').write_text(json.dumps({'format':'ken-policy-execution/1','files':files}))
    row['execution_artifacts']={'artifact':'execution-artifacts.json',
        'sha256':hashlib.sha256((root/'execution-artifacts.json').read_bytes()).hexdigest()}
    (root/'summary.json').write_text(json.dumps(row))
