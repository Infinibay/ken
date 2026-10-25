"""Authenticate saved native bytes and independently replay their semantics."""
from __future__ import annotations

import hashlib, json, math, re
from pathlib import Path
from .fastembed_process import decode_frames, _distinct, _nonfinite
from .policy_evidence import _relative
from .transformer_compare import compare_transformer, request_policy
from .transformer_reference import CATALOG, freeze_profile_budget, profile_key

OWNERSHIP_CASES = (
    'actual_cpu_loads_even_for_empty_then_scores_raw_batches_and_keeps_its_owned_source',
    'concurrent_first_use_serializes_one_owned_judge',
    'cpu_late_failure_and_nonfinite_return_no_partial_scores_without_retry',
    'actual_concurrent_first_use_shares_one_session_and_source_copy',
)


def gate_errors(files: dict[str, bytes], row: dict, source_root: Path) -> list[str]:
    """A passing flag cannot replace raw gate output or the fixed capacity bar."""
    try:
        def require(condition, message):
            if not condition: raise ValueError(message)
        gates = row['gates']
        for name, gate in gates.items():
            if name == 'native_mlx' and row['platform'] == 'linux': continue
            path = str(_relative(gate['artifact'])); raw = files[path]
            require(hashlib.sha256(raw).hexdigest() == gate['sha256'], 'gate artifact identity differs: '+name)
            if name == 'capacity': continue
            value = raw.decode()
            if name.startswith('native_'):
                passed = sum(int(n) for n in re.findall(r'test result: ok\. (\d+) passed;', value))
                require(passed >= (7 if name == 'native_mlx' else 14) and
                        '0 failed' in value and '0 ignored' in value,
                        'incomplete native test output: '+name)
            else:
                passed = re.search(r'\b(\d+) passed\b', value)
                require(passed is not None and int(passed[1]) >= (95 if name == 'transformer_unit' else 1)
                        and re.search(r'\b[1-9]\d* (failed|errors?|skipped|xfailed)\b', value) is None,
                        'incomplete or skipped transformer tests: '+name)
        owners = files['native-owners.log'].decode()
        for case in OWNERSHIP_CASES:
            require(any(case in line and line.endswith(' ... ok') for line in owners.splitlines()),
                    'missing actual lifecycle regression: '+case)
        require('0 failed' in owners and '0 ignored' in owners, 'failed native lifecycle tests')
        capacity = json.loads(files[gates['capacity']['artifact']], object_pairs_hook=_distinct, parse_constant=_nonfinite)
        from .transformer_sources import capacity_plan
        registry = json.loads((source_root/'tools/rust_migration/data/transformer-cores.json').read_bytes())
        models = json.loads((source_root/'crates/ken-models/resources/transformer-catalog.json').read_bytes())['models']
        from .transformer_cores import transformer_cores
        cores = transformer_cores(registry,row['platform'],row['architecture'])
        modules = {}
        for backend in {c['backend'] for c in cores}:
            sizes = {p['native_module']['bytes'] for p in row['profiles'] if p['runtime']['backend'] == backend}
            require(len(sizes) == 1, 'one current module size per native backend required')
            modules[backend] = next(iter(sizes))
        plans = [capacity_plan(model, core, module_bytes=modules[core['backend']], acquire=True)
                 for model in models for core in cores
                 if core['backend'] == 'torch' or model['architecture'] == 'qwen3']
        require(capacity['model_plans'] == plans, 'model/core/private-copy capacity or3GiB reserve changed')
        need = max(p['required_free_bytes'] for p in plans)
        fields = ('next_phase_required_free_bytes', 'observed_free_bytes', 'measured_allocated_bytes',
                  'measured_allocated_plus_next_phase_bytes', 'declared_total_bytes')
        require(all(type(capacity[k]) is int and capacity[k] > 0 for k in fields), 'positive measured capacities required')
        require(capacity['next_phase_required_free_bytes'] == need and capacity['observed_free_bytes'] >= need
                and capacity['measured_allocated_plus_next_phase_bytes'] == capacity['measured_allocated_bytes']+need
                and capacity['measured_allocated_plus_next_phase_bytes'] <= capacity['declared_total_bytes'],
                'measured transformer peak/free space exceeds declared capacity')
        return []
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        return ['transformer gate evidence: '+str(error)]


def source_identity(root: Path) -> dict:
    paths = {root/'Cargo.toml', root/'Cargo.lock'}
    for folder in ('crates/ken-models', 'crates/ken-native-model-api',
                   'native/ken-torch-backend', 'native/ken-mlx-backend'):
        for path in (root/folder).rglob('*'):
            relative = path.relative_to(root/folder)
            # FastEmbed is a separate executable and is not compiled into any transformer probe.
            if (path.is_file() and relative.as_posix() != 'examples/fastembed_probe.rs'
                    and not any(p in ('tests', 'target', '.ken', '__pycache__') for p in relative.parts)):
                paths.add(path)
    return {str(p.relative_to(root)): {'bytes': p.stat().st_size,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths) if p.is_file()}


def profile_errors(files: dict[str, bytes], row: dict, original: dict,
                   source_root: Path, registered_core: dict) -> list[str]:
    try:
        def require(condition, message):
            if not condition: raise ValueError(message)
        prefix = str(_relative(row['directory'])) + '/'
        def raw(name):
            return files[prefix+name]
        def document(name):
            return json.loads(raw(name), object_pairs_hook=_distinct, parse_constant=_nonfinite)
        require(row['key'] == profile_key(original), 'wrong original profile binding')
        require(row['source_files'] == source_identity(source_root), 'stale/incomplete native source identity')
        require(row['runtime'] == registered_core, 'stale or unregistered native core/libraries')
        execution = row['execution']
        require(execution['native_exit'] == 0 and execution['outside_checkout'] is True
                and execution['native_children'] == [] and execution['owned_after_exit'] == []
                and execution['execution_audit'] is True, 'incomplete native process/ownership audit')
        for name in ('host_binary', 'native_module'):
            identity = row[name]
            require(set(identity) == {'bytes', 'sha256'} and type(identity['bytes']) is int
                    and identity['bytes'] > 0 and re.fullmatch('[0-9a-f]{64}', identity['sha256']) is not None,
                    'invalid native binary identity')
        require(execution['native_sha256'] == row['host_binary']['sha256'], 'native host release binding differs')
        budget = freeze_profile_budget(original)['execution_deadline_seconds']
        require(execution['fixed_deadline_s'] == budget, 'original fixed deadline changed')
        require(type(execution['elapsed_s']) in (int, float) and math.isfinite(execution['elapsed_s'])
                and 0 < execution['elapsed_s'] <= budget, 'invalid actual execution timing')
        inputs = document('inputs.json')
        policy = request_policy(original)
        require({k: inputs[k] for k in policy} == policy, 'public native inputs differ from original')
        capture = original['capture']
        definition = next(m for m in json.loads(CATALOG.read_text())['models']
                          if m['name'] == capture['settings']['model_id'])
        require(inputs['model'] == definition, 'native model/assets/config declaration differs')
        allowed = set(policy) | {'model', 'runtime', 'snapshot', 'private_parent', 'module', 'core_root'}
        require(set(inputs) == allowed, 'missing or unexpected native input fields')
        for name in ('snapshot', 'private_parent', 'module', 'core_root'):
            require(Path(inputs[name]).is_absolute(), 'absolute prepared native input required')
        suffix = (definition['assets']['model_id'].replace('/', '--'), definition['assets']['revision'])
        require(Path(inputs['snapshot']).parts[-2:] == suffix, 'wrong source model/revision path')
        runtimes = inputs['runtime']
        require(runtimes['format'] == 'ken-native-transformer/1' and
                runtimes['backend'] == registered_core['backend'], 'native runtime backend differs')
        require(runtimes['runtimes'] == [{'os': original['platform'], 'arch': 'aarch64',
                'core_version': registered_core['core_version'], 'module': row['native_module'],
                'libraries': registered_core['libraries']}], 'native module/core identity mismatch')
        loader = raw('stderr.log').decode()
        library = ('libmlx.dylib' if registered_core['backend'] == 'mlx' else
                   ('libtorch_cpu.so' if original['platform'] == 'linux' else 'libtorch_cpu.dylib'))
        require('libtorch_python' not in loader and 'libpython' not in loader and any(
                'ken-transformer-' in line and library in line for line in loader.splitlines()),
                'missing actual private native core or forbidden Python linkage')
        if original['platform'] == 'linux':
            require(execution['exec_attempts'] == 1 and
                    execution['execution_audit_syscalls'] == ['execve', 'execveat'],
                    'both Linux execution syscalls must be audited')
            trace = raw('exec.trace').decode()
            require(len(re.findall(r'\bexecve(?:at)?\(', trace)) == 1 and
                    execution['command'][-2] in trace, 'unexpected or missing native Linux exec')
        else:
            require(execution['exec_attempts'] is None, 'invalid macOS exec audit claim')
        frames = decode_frames(raw('actual.json').decode())
        require(len(frames) == 1, 'one complete actual output required')
        expected_identity = {'arch': 'aarch64', 'os': original['platform'],
            'backend': registered_core['backend'], 'declared_core_version': registered_core['core_version'],
            'libraries': registered_core['libraries'], 'module': row['native_module']}
        require(all(item['preparation']['runtime'] == expected_identity for item in frames[0]['rows']),
                'actual runtime identity differs from verified native module/core closure')
        return compare_transformer(original, frames[0])['errors']
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, StopIteration) as error:
        return ['transformer execution evidence: '+str(error)]
