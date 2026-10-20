"""Exercise actual frozen policy with explicitly controlled model collaborators."""
from pathlib import Path
import hashlib
import json
import threading
import numpy as np
from ken.embedder.st_backend import SentenceTransformerEmbedder
import ken.embedder.st_backend as original

root = Path('/Users/andres/Projects/ken')
source = root / '.ken/rust-migration/m0-m1/reference/src/ken/embedder/st_backend.py'
assert Path(original.__file__).resolve() == source
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()


class ControlledModel:
    def __init__(self, owner, device):
        self.owner, self.device = owner, device

    def get_embedding_dimension(self):
        return 4

    def encode(self, payload, **options):
        assert options == {'batch_size': 16, 'convert_to_numpy': True,
                           'normalize_embeddings': True, 'show_progress_bar': False}
        self.owner.executions.append(self.device)
        if self.owner.mode == 'cpu-raise' and self.device == 'cpu':
            raise RuntimeError('controlled CPU inference')
        if self.device != 'cpu':
            if self.owner.wait_for_second:
                assert self.owner.second_ensured.wait(5), 'second caller never reached the ready model'
            if self.owner.mode == 'raise':
                raise RuntimeError('controlled accelerator inference')
            if self.owner.mode == 'nan':
                return np.full((len(payload), 4), np.nan, dtype=np.float32)
            if self.owner.mode == 'zero':
                return np.zeros((len(payload), 4), dtype=np.float32)
            if self.owner.mode == 'nonunit':
                return np.ones((len(payload), 4), dtype=np.float32)
        values = np.full((len(payload), 4), 0.5, dtype=np.float32)
        if self.owner.mode == 'rounded-bf16' and self.device != 'cpu':
            values *= np.float32(1.003458)
        if self.owner.mode == 'cpu-nan' and self.device == 'cpu':
            values.fill(np.nan)
        return values


class ControlledEncoder(SentenceTransformerEmbedder):
    def __init__(self, device, mode='healthy', fail_cpu=False, fail_gpu=False):
        super().__init__('Qwen/Qwen3-Embedding-0.6B', device=device, dtype='float16', batch_size=16)
        self.mode, self.fail_cpu, self.fail_gpu = mode, fail_cpu, fail_gpu
        self.builds, self.executions = [], []
        self.wait_for_second = False
        self.second_ensured = threading.Event()

    def _build(self, device):
        self.builds.append(device)
        if (device == 'cpu' and self.fail_cpu) or (device != 'cpu' and self.fail_gpu):
            raise RuntimeError('controlled ' + device + ' build')
        return ControlledModel(self, device)

    def _ensure_model(self):
        model = super()._ensure_model()
        if threading.current_thread().name == 'second':
            self.second_ensured.set()
        return model


rows = []
empty = ControlledEncoder('cpu')
assert empty.embed_passages([]) == [] and empty.embed_queries([]) == []
assert empty._model is None and empty.device == 'unknown' and empty.builds == []
rows.append({'case': 'empty_without_load', 'builds': empty.builds, 'device': empty.device})
assert empty.dim == 4 and empty.builds == ['cpu']
rows.append({'case': 'dimension_loads', 'dimension': empty.dim, 'builds': empty.builds.copy()})
for mode in ('raise', 'nan', 'zero', 'nonunit'):
    encoder = ControlledEncoder('mps', mode=mode)
    first = encoder.embed_query('one')
    second = encoder.embed_query('two')
    assert encoder.device == 'cpu' and encoder.builds == ['mps', 'cpu']
    assert encoder.executions == ['mps', 'cpu', 'cpu']
    assert np.isfinite(first).all() and np.isfinite(second).all()
    rows.append({'case': 'permanent_demotion_' + mode, 'builds': encoder.builds,
                 'executions': encoder.executions, 'device': encoder.device, 'vectors': [first.tolist(), second.tolist()]})
encoder = ControlledEncoder('mps', fail_gpu=True)
assert np.isfinite(encoder.embed_query('one')).all() and encoder.device == 'cpu'
assert encoder.builds == ['mps', 'cpu']
rows.append({'case': 'accelerator_load_failure', 'builds': encoder.builds, 'device': encoder.device})
encoder = ControlledEncoder('mps', mode='rounded-bf16')
value = encoder.embed_query('one')
assert encoder.device == 'mps' and encoder.builds == ['mps']
assert abs(float(np.linalg.norm(value)) - 1.) < 1e-6
rows.append({'case': 'healthy_dtype_rounding_stays_accelerated', 'builds': encoder.builds,
             'device': encoder.device, 'vector': value.tolist()})
encoder = ControlledEncoder('cpu', mode='cpu-raise')
try:
    encoder.embed_query('one')
except RuntimeError as error:
    assert str(error) == 'controlled CPU inference'
    rows.append({'case': 'cpu_error_propagates', 'exception': type(error).__name__, 'message': str(error),
                 'device': encoder.device, 'builds': encoder.builds})
else:
    raise AssertionError('original swallowed CPU failure')
encoder = ControlledEncoder('mps', mode='nan', fail_cpu=True)
try:
    encoder.embed_query('one')
except RuntimeError as error:
    assert str(error) == 'controlled cpu build'
else:
    raise AssertionError('original swallowed failed CPU rebuild')
assert encoder.device == 'mps' and encoder._model.device == 'mps'
before = {'device': encoder.device, 'model_device': encoder._model.device, 'builds': encoder.builds.copy()}
encoder.fail_cpu = False
assert np.isfinite(encoder.embed_query('repair')).all() and encoder.device == 'cpu'
rows.append({'case': 'failed_cpu_rebuild_keeps_ready_state_then_repairs', 'failure_state': before,
             'repaired_device': encoder.device, 'builds': encoder.builds})
encoder = ControlledEncoder('mps', mode='nan')
assert encoder.dim == 4
encoder.wait_for_second = True
outputs, failures = [], []


def invoke():
    try:
        outputs.append(encoder.embed_query('concurrent'))
    except BaseException as error:
        failures.append(str(error))


first = threading.Thread(target=invoke, name='first')
second = threading.Thread(target=invoke, name='second')
first.start()
second.start()
first.join(10)
second.join(10)
assert not first.is_alive() and not second.is_alive() and not failures
assert len(outputs) == 2 and all(np.isfinite(value).all() for value in outputs)
assert encoder.builds == ['mps', 'cpu'] and encoder.executions == ['mps', 'cpu', 'cpu']
rows.append({'case': 'concurrent_second_caller_uses_replacement', 'builds': encoder.builds,
             'executions': encoder.executions, 'device': encoder.device, 'thread_failures': failures})
encoder = ControlledEncoder('cpu', mode='cpu-nan')
with np.errstate(invalid='ignore'):
    invalid = encoder.embed_query('one')
assert not np.isfinite(invalid).all() and encoder.device == 'cpu'
rows.append({'case': 'original_cpu_nonfinite_gap', 'all_finite': False, 'device': encoder.device,
             'required_native_policy': 'Reject NaN/Inf per approved M2 specification; do not propagate invalid vectors.'})
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
receipt = {'format': 'ken-original-transformer-lifecycle/1', 'original_source_sha256': source_sha,
           'passed': True, 'cases': rows, 'numpy': np.__version__, 'real_model_inference': False,
           'scope': 'Original adapter policy with controlled failing model collaborators; no GPU numerical or hardware OOM claim.',
           'model_inference_accepted': False}
out = root / '.ken/rust-migration/m2-optional/preflight/original-lifecycle.json'
out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
print(json.dumps({'passed': True, 'cases': len(rows), 'real_model_inference': False}), flush=True)
