"""Protocol fixtures exercise semantic rejection; they are not neural evidence."""
from copy import deepcopy
import pytest
from tools.rust_migration.integration_compare import compare_factory


def observation():
    expected = {
        'selection': {'role': 'encoder', 'family': 'sentence_transformer',
                      'model_id': 'BAAI/bge-m3', 'revision': 'a'*40,
                      'backend': 'sentence-transformers', 'dtype': 'float32',
                      'device': 'cpu', 'sequence_length': 512, 'batch_size': 16},
        'compatible_key': 'original-key',
        'runtime': {'backend': 'torch', 'declared_core_version': '2.9.0',
                    'module': {'bytes': 3, 'sha256': 'b'*64}},
        'rows': [{'id': 'one', 'vectors': [[1., 0.]], 'prepared': True}],
        'source_files': {'crate.rs': {'bytes': 4, 'sha256': 'c'*64}},
    }
    actual = deepcopy(expected)
    actual.update(format='ken-model-factory-observation/1', policy='offline',
                  initial_prepared=False, after_empty_prepared=False)
    execution = {'exit_code': 0, 'outside_checkout': True, 'dependency_audit': {'passed': True},
                 'platform': 'linux', 'trace': 'execve("/tmp/native", ["/tmp/native"], []) = 0\n',
                 'audit_syscalls': ['execve', 'execveat', 'connect'],
                 'sentinel_invocations': [], 'owned_after_exit': []}
    predecessors = {'storage': {'verified': True}, 'core': {'verified': True}}
    return actual, expected, execution, predecessors


def check(data):
    actual, expected, execution, predecessors = data
    return compare_factory(actual, expected, execution=execution, predecessors=predecessors)


def test_literal_semantics_require_actual_native_observations():
    assert check(observation()) == []


@pytest.mark.parametrize('mutation', [
    'missing-family', 'missing-role', 'wrong-revision', 'wrong-compatible-key',
    'wrong-runtime', 'wrong-module', 'changed-source', 'offline-connect',
    'missing-execveat', 'missing-storage', 'missing-core', 'partial-vectors',
    'wrong-vectors', 'nonfinite', 'cold-loaded', 'empty-loaded', 'wrong-device',
])
def test_corruption_still_rejects_after_outer_file_hashes_are_resealed(mutation):
    data = observation(); actual, expected, execution, predecessors = data
    if mutation.startswith('missing-') and mutation[8:] in ('family', 'role'):
        del actual['selection'][mutation[8:]]
    elif mutation == 'wrong-revision': actual['selection']['revision'] = 'd'*40
    elif mutation == 'wrong-compatible-key': actual['compatible_key'] = 'another-key'
    elif mutation == 'wrong-runtime': actual['runtime']['declared_core_version'] = '2.8.0'
    elif mutation == 'wrong-module': actual['runtime']['module']['sha256'] = 'e'*64
    elif mutation == 'changed-source': actual['source_files']['crate.rs']['sha256'] = 'f'*64
    elif mutation == 'offline-connect': execution['trace'] += 'connect(3, {}, 10) = 0\n'
    elif mutation == 'missing-execveat': execution['audit_syscalls'].remove('execveat')
    elif mutation in ('missing-storage', 'missing-core'): del predecessors[mutation[8:]]
    elif mutation == 'partial-vectors': actual['rows'][0]['vectors'] = []
    elif mutation == 'wrong-vectors': actual['rows'][0]['vectors'][0][0] = 0.5
    elif mutation == 'nonfinite': actual['rows'][0]['vectors'][0][0] = float('nan')
    elif mutation == 'cold-loaded': actual['initial_prepared'] = True
    elif mutation == 'empty-loaded': actual['after_empty_prepared'] = True
    elif mutation == 'wrong-device': actual['selection']['device'] = 'mps'
    # There is deliberately no outer passed flag or digest in this API: resealing
    # transport bytes cannot excuse a semantic mismatch against pinned inputs.
    assert check(data), mutation
