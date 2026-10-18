"""A model family passes only with matching complete platform evidence."""
from copy import deepcopy
import json

from tools.rust_migration.model_validate import REQUIRED_GATES, aggregate_models, assess_model_samples


def local(platform):
    return {'scope': 'model-local', 'platform': platform, 'passed': True, 'M2_accepted': False,
        'fingerprints': {key: 'a'*64 for key in ('native_source','reference_source','cases','validator','oracle','registration')},
        'rustc': 'rustc 1.95.0 (59807616e 2026-04-14)',
        'case_ids': ['case'], 'gates': {gate:{'ran':True,'passed':True} for gate in REQUIRED_GATES},
        'model_parity': {'passed': True, 'outside_checkout': True, 'native_children': [],
                         'dependency_audit': {'passed': True}, 'exec_attempts':1}}


def test_platform_aggregation_rejects_drift_missing_platform_and_inference_failure(tmp_path):
    paths=[]
    for platform in ['Darwin','Linux']:
        folder=tmp_path/platform; folder.mkdir(); path=folder/'summary.json'; paths.append(path)
        path.write_text(json.dumps(local(platform)))
    assert aggregate_models(tmp_path, expected_ids=['case'])['Potion_accepted'] is True
    assert aggregate_models(tmp_path, expected_ids=['case'])['M2_accepted'] is False
    original=local('Linux')
    for mutation in ['weights','cases','failed','trace','gate','ids','execution_error']:
        bad=deepcopy(original)
        if mutation=='weights': bad['fingerprints']['registration']='b'*64
        elif mutation=='cases': bad['fingerprints']['cases']='b'*64
        elif mutation=='failed': bad['model_parity']['passed']=False
        elif mutation=='trace': bad['model_parity']['exec_attempts']=2
        elif mutation=='gate': bad['gates'].pop('python_full')
        elif mutation=='ids': bad['case_ids']=[]
        else: bad['execution_error']='crashed'
        paths[1].write_text(json.dumps(bad))
        assert aggregate_models(tmp_path, expected_ids=['case'])['passed'] is False, mutation
    paths[1].unlink()
    assert aggregate_models(tmp_path, expected_ids=['case'])['passed'] is False


def test_model_benchmark_rejects_incomplete_or_nonfinite_phase_samples():
    samples=[{'engine':engine,'scenario':scenario,'index':i,'load_ns':10,'inference_ns':20,
              'peak_after_load_bytes':100,'peak_after_inference_bytes':120}
             for engine in ['python','native'] for scenario in ['query','passages'] for i in range(30)]
    assert assess_model_samples(samples)['passed'] is True
    assert assess_model_samples(samples[:-1])['passed'] is False
    wrong=deepcopy(samples); wrong[0]['load_ns']=float('nan')
    assert assess_model_samples(wrong)['passed'] is False
    wrong=deepcopy(samples); wrong[0]['peak_after_inference_bytes']=0
    assert assess_model_samples(wrong)['passed'] is False
