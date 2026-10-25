from pathlib import Path
import copy,json,sys
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_fixed_inputs_contain_no_frozen_answers():
    from tools.rust_migration.x86_numeric_diagnostic import fixed_inputs
    value=fixed_inputs(ROOT)
    assert set(value)=={'context','alignment'}
    assert [c['id']for c in value['context']]==['empty-query','passage-boundary511','passage-boundary512']
    assert value['alignment']['id']=='product-float32-float32-float64-4-128-3'
    assert set(value['alignment'])=={'id','family','kind','input'}
    assert all('result'not in c and 'expected'not in c for c in value['context'])


def test_records_nonzero_exit_and_preserves_raw_payload_without_overwrite(tmp_path):
    from tools.rust_migration.x86_numeric_diagnostic import record,verify_record
    argv=[sys.executable,'-c','import sys;print("measured");sys.stderr.write("failure");sys.exit(3)']
    row=record(tmp_path,'failure',argv,cwd=ROOT)
    assert row['exit']==3 and not verify_record(tmp_path,row)
    assert (tmp_path/'failure.stdout').read_text()=='measured\n'
    with pytest.raises(FileExistsError):record(tmp_path,'failure',argv,cwd=ROOT)
    (tmp_path/'failure.stdout').write_text('changed')
    assert verify_record(tmp_path,row)


@pytest.mark.parametrize('actual,expected',[([1.,2.],[1.,2.]),([0.,0.],[0.,0.])])
def test_vector_comparison_keeps_exact_and_frozen_tolerance_views(actual,expected):
    from tools.rust_migration.x86_numeric_diagnostic import vector_difference
    assert vector_difference(actual,expected)==dict(max_abs=0.,exact=True,within_frozen_tolerance=True)


@pytest.mark.parametrize('bad',[[True],[float('nan')],[float('inf')],[],[1.,2.]])
def test_vector_comparison_rejects_malformed_values(bad):
    from tools.rust_migration.x86_numeric_diagnostic import vector_difference
    with pytest.raises(ValueError):vector_difference(bad,[1.])


def test_alignment_intervention_records_actual_kernel_and_both_python_boundaries():
    from tools.rust_migration.x86_numeric_alignment import observe
    from tools.rust_migration.x86_numeric_diagnostic import fixed_inputs
    row=observe(fixed_inputs(ROOT)['alignment'],ROOT)
    assert set(row)=={'source','source_sha256','numpy','blas','similarities','maxima','coverage'}
    assert row['blas']['core']and row['numpy']=='2.4.4'
    assert len(row['similarities'])==4 and len(row['similarities'][0])==3 and len(row['maxima'])==4
    assert row['coverage']['weighted']==pytest.approx(2.1855457487859224,abs=1e-6)


def test_report_verifier_refuses_summary_without_raw_observers(tmp_path):
    from tools.rust_migration.x86_numeric_diagnostic import verify_report
    (tmp_path/'report.json').write_text('{"complete":true,"cause":"cpu"}')
    assert verify_report(tmp_path)

@pytest.fixture
def actual_packet(tmp_path):
    import os,shutil
    source=Path(os.environ.get('KEN_X86_NUMERIC_PACKET',ROOT/'.ken/rust-migration/x86-numerics/local-observations'))
    destination=tmp_path/'packet';shutil.copytree(source,destination);return destination

def test_actual_diagnostic_is_replayable_and_not_acceptance(actual_packet):
    from tools.rust_migration.x86_numeric_diagnostic import verify_report
    assert not verify_report(actual_packet)
    value=json.loads((actual_packet/'report.json').read_bytes())
    assert value['model_acceptance']is False and value['comparison']['cpu_cause_established']is False

@pytest.mark.parametrize('change',['input-answer','python-input-answer','native-output','record-inventory','summary','kernel-env','python-kernel-env','context-order','source-baseline'])
def test_resealed_diagnostic_rejects_wrong_evidence(actual_packet,change):
    from tools.rust_migration.x86_numeric_diagnostic import verify_report
    from tools.rust_migration.native_json import identity
    report_path=actual_packet/'report.json';report=json.loads(report_path.read_bytes())
    def mutate_record(name,kind,change_value):
        row=next(r for r in report['records']if r['name']==name)
        path=actual_packet/(name+'.'+('input.json'if kind=='input'else'stdout'));value=json.loads(path.read_bytes());change_value(value);path.write_text(json.dumps(value));row[kind]=identity(path)
        (actual_packet/(name+'.record.json')).write_text(json.dumps(row))
    if change=='input-answer':mutate_record('alignment-native-rust','input',lambda v:v.update(expected={}))
    elif change=='python-input-answer':mutate_record('alignment-native-python','input',lambda v:v.update(result={}))
    elif change=='native-output':mutate_record('context-native','stdout',lambda v:v['results'][0]['calls'][1].__setitem__(0,999.))
    elif change=='record-inventory':report['records'].pop()
    elif change=='summary':report['comparison']['cpu_cause_established']=True
    elif change in('kernel-env','python-kernel-env'):
        language='python'if change=='python-kernel-env'else'rust'
        row=next(r for r in report['records']if r['name']=='alignment-haswell-'+language);row['environment'].pop('OPENBLAS_CORETYPE')
        (actual_packet/(row['name']+'.record.json')).write_text(json.dumps(row))
    elif change=='context-order':mutate_record('context-native','input',lambda v:v['cases'].reverse())
    else:report['environment']['identical_sources']['Cargo.lock']={report['environment']['candidate']:'different'}
    report_path.write_text(json.dumps(report));assert verify_report(actual_packet)
