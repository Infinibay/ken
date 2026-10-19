"""Receipt-policy fixtures are not runtime proof; stale/malformed matrices fail."""
from copy import deepcopy
import json
from pathlib import Path

from tools.rust_migration.ettin_validate import ETTIN_KEYS, ETTIN_GATES
from tools.rust_migration.translation_compare import native_identity
from tools.rust_migration.translation_validate import TRANSLATION_KEYS, TRANSLATION_GATES, aggregate_translations

ROOT=Path(__file__).resolve().parents[2]


def native_build(system,arch):
    source={'bytes':24404912,'sha256':'4e6e4f5cb14c209262e33e6816d70221a2fe49eb69eaf0a06f065598ac602c68'}
    files={name:{'bytes':1,'sha256':'a'*64} for name in ['source.tar.gz','lib/libopenblas.a','include/cblas.h','include/openblas_config.h','lib/pkgconfig/openblas.pc']}
    files['source.tar.gz']=source
    return {'format':'ken-translation-build/1','platform':system,'architecture':arch,
        'cmake':{'version':'3.31.10','bytes':1,'sha256':'a'*64},
        'core':{'build_type':'Release','float_backend':'Accelerate' if system=='Darwin' else 'OpenBLAS0.3.26',
            'int8_backend':'Ruy','openmp_runtime':'NONE' if system=='Darwin' else 'COMP',
            'cxx_flags_release':'-O3 -DNDEBUG','cache_sha256':'a'*64,'compiler':{'id':'GNU','version':'12.2.0'}},
        'openblas':None if system=='Darwin' else {'format':'ken-openblas-build/1','platform':'Linux','architecture':'aarch64',
            'version':'0.3.26','source':source,'options':['TARGET=ARMV8','NO_SHARED=1','BUILD_SINGLE=1','NO_LAPACK=1',
                'ONLY_CBLAS=1','USE_OPENMP=1','NUM_THREADS=64','NUM_PARALLEL=1'],
            'compiler':{'path':'/usr/bin/cc','version':'GNU12.2.0'},'artifacts':files,'build_ns':1,'build_log_sha256':'a'*64}}


def test_translation_matrix_requires_all26gates_current_source_and_exact_native_prerequisite_proof(tmp_path):
    document=json.loads((ROOT/'docs/validation/rust-migration-2026-10-19/m2-translation/reference.json').read_text())
    def row(system,arch,folder):
        base=json.loads((ROOT/f'docs/validation/rust-migration-2026-10-19/m2-ettin/{folder}/summary.json').read_text())
        golden=next(r for r in document['oracles'] if r['platform']==system and r['architecture']==arch)
        fingerprints=base['fingerprints']|{key:'e'*64 for key in TRANSLATION_KEYS-ETTIN_KEYS}
        binding={'ran':True,'passed':True,'built_sha256':'d'*64,'supplied_sha256':'d'*64,'native_build':native_build(system,arch)}
        parity={'format':'ken-translation-parity/1','platform':system,'architecture':arch,'passed':True,'errors':[],
            'M2_accepted':False,'native_exit':0,'native_wall_ns':1,'outside_checkout':True,'native_children':[],
            'dependency_audit':{'passed':True,'errors':[]},'exec_attempts':1,'native_sha256':'d'*64,
            'oracle_sha256':fingerprints['translation_oracle'],'raw_oracle_sha256':fingerprints['translation_raw_oracle'],
            'case_ids':['translation'],'stderr':'','runtime':{'engine':'rust','ken_models':'0.18.0'},
            'native_identity':native_identity(system),'reference_runtime':golden['oracle']['runtime'],
            'preparation':{'fresh_cache':True,'reused_without_source':True,'source_artifacts':golden['source_artifacts'],
                'artifacts':golden['prepared_artifacts'],'recipe_key':golden['recipe_sha256']}}
        gates=deepcopy(base['gates'])|{g:{'ran':True,'passed':True} for g in TRANSLATION_GATES if g not in ETTIN_GATES}
        gates['translation_release']=binding
        return {'scope':'translation-local','platform':system,'architecture':arch,'passed':True,'M2_accepted':False,
            'fingerprints':fingerprints,'rustc':base['rustc'],'case_ids':['translation'],'ettin_base':base,
            'gates':gates,'translation_release':binding,'translation_parity':parity}
    mac=row('Darwin','arm64','macos');linux=row('Linux','aarch64','linux');fingerprints=deepcopy(mac['fingerprints'])
    assert len(TRANSLATION_GATES)==26
    def write(rows,current=fingerprints):
        for path in tmp_path.glob('*/summary.json'):path.unlink()
        for index,value in enumerate(rows):
            path=tmp_path/str(index)/'summary.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(value))
        return aggregate_translations(tmp_path,expected_ids=['translation'],expected_fingerprints=current)
    assert write([mac,linux])['Translation_accepted'] is True
    assert write([mac,linux])['M2_accepted'] is False
    assert not write([mac])['passed'] and not write([mac,mac])['passed']
    assert not write([mac,linux],None)['passed']
    for gate in TRANSLATION_GATES:
        bad=deepcopy(linux);bad['gates'][gate]['passed']=False
        assert not write([mac,bad])['passed'],gate
    for key in TRANSLATION_KEYS:
        bad=deepcopy(linux);bad['fingerprints'][key]='0'*64
        assert not write([mac,bad])['passed'],key
    for change in ['binding','build','compiler','cmake','blas','source','recipe','fresh','reuse','artifacts',
                   'identity','runtime','stderr','exec','children','oracle','raw_oracle','basegate','basefingerprint',
                   'basescope','case_ids','globalM2','execution_error']:
        bad=deepcopy(linux);parity=bad['translation_parity'];build=bad['translation_release']['native_build'];base=bad['ettin_base']
        if change=='binding':bad['translation_release']['supplied_sha256']='0'*64
        elif change=='build':build['core']['build_type']='Debug'
        elif change=='compiler':build['core']['compiler']={}
        elif change=='cmake':build['cmake']['version']='4.0.0'
        elif change=='blas':build['openblas']['options']=[]
        elif change=='source':parity['preparation']['source_artifacts']={}
        elif change=='recipe':parity['preparation']['recipe_key']='0'*64
        elif change=='fresh':parity['preparation']['fresh_cache']=False
        elif change=='reuse':parity['preparation']['reused_without_source']=False
        elif change=='artifacts':parity['preparation']['artifacts']={}
        elif change=='identity':parity['native_identity']['float_backend']='Ruy'
        elif change=='runtime':parity['runtime']['engine']='python'
        elif change=='stderr':parity['stderr']='unrecorded warning\n'
        elif change=='exec':parity['exec_attempts']=2
        elif change=='children':parity['native_children']=['python']
        elif change=='oracle':parity['oracle_sha256']='0'*64
        elif change=='raw_oracle':parity['raw_oracle_sha256']='0'*64
        elif change=='basegate':base['gates']['rust_tests']['passed']=False
        elif change=='basefingerprint':base['fingerprints']['native_source']='0'*64
        elif change=='basescope':base['scope']='other'
        elif change=='case_ids':parity['case_ids']=[]
        elif change=='globalM2':bad['M2_accepted']=True
        else:bad['execution_error']='interrupted'
        assert not write([mac,bad])['passed'],change


def test_missing_native_build_prerequisite_fails_before_running_prior_suites(tmp_path,monkeypatch):
    from tools.rust_migration import translation_validate as tv
    from tools.rust_migration.preparation import PreparedNativeContext, PreparedNativeEttin, PreparedNativeTranslation, PreparedTranslationBuild
    from tools.rust_migration.reference import Reference
    import sys
    monkeypatch.setattr(tv,'translation_fingerprints',lambda *args:{})
    def forbidden(*args,**kwargs):raise AssertionError('missing prerequisites must fail before expensive suites')
    monkeypatch.setattr(tv,'validate_ettin',forbidden)
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'core',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe')
    translation=PreparedNativeTranslation(tmp_path/'source',tmp_path/'probe',PreparedTranslationBuild(tmp_path/'missing-cmake'))
    result=tv.validate_translation(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',
        tmp_path/'table.npz',context,ettin,translation,tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest')
    assert result==1
    receipt=json.loads((tmp_path/'out/summary.json').read_text())
    assert receipt['passed'] is False and receipt['M2_accepted'] is False
    assert 'CMake' in receipt['execution_error']
