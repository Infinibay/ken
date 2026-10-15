"""Download one official public compact CPU graph; never send repository data."""
import hashlib
import json
import platform
import urllib.request
from pathlib import Path

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
OUT = Path('/private/tmp/ken-search-eval-20261014/jina-pair-research-v84')
OUT.mkdir(exist_ok=True)
assert not any(OUT.iterdir()), 'asset attempt must not replace existing data'
model = 'jinaai/jina-reranker-v1-tiny-en'
with urllib.request.urlopen(f'https://huggingface.co/api/models/{model}', timeout=60) as response:
    info = json.load(response)
revision = info['sha']
assert len(revision) == 40 and info['cardData']['license'] == 'apache-2.0'
target = OUT/revision
target.mkdir()
artifacts = {}
for name in ('onnx/model_int8.onnx', 'config.json', 'tokenizer.json',
             'tokenizer_config.json', 'special_tokens_map.json', 'README.md'):
    path = target/name
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f'https://huggingface.co/{model}/resolve/{revision}/{name}', timeout=60) as response:
        data = response.read()
    path.write_bytes(data)
    artifacts[name] = hashlib.sha256(data).hexdigest()
config = json.loads((target/'config.json').read_text())
assert config['model_type'] == 'bert' and config['num_hidden_layers'] == 4 and config['hidden_size'] == 384
record = {'model_id': model, 'revision': revision, 'root': str(target),
    'license': 'apache-2.0', 'artifacts': artifacts, 'config': config,
    'graph_bytes': (target/'onnx/model_int8.onnx').stat().st_size,
    'host_machine': platform.machine(),
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'protocol_sha256': hashlib.sha256((ROOT/'experiments/search-engine/cpu-jina-prefix-v84.md').read_bytes()).hexdigest(),
    'scope': 'one official public CPU int8 research graph; no quality, code specialization or promotion claim'}
(ROOT/'output/models/jina-pair-registration-v84.json').write_text(json.dumps(record, indent=2))
print(json.dumps({key: record[key] for key in ('model_id', 'revision', 'graph_bytes')}), flush=True)
