"""Download public official small ONNX artifacts only; never send repo/query data."""
import hashlib
import json
import platform
import urllib.request
from pathlib import Path

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
OUT = Path('/private/tmp/ken-search-eval-20261014/marco-pair-research-v73')
OUT.mkdir(exist_ok=False)
records = []
for short in ('TinyBERT-L2', 'MiniLM-L6'):
    model = f'cross-encoder/ms-marco-{short}-v2'
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{model}', timeout=60) as response:
        info = json.load(response)
    revision = info['sha']
    assert len(revision) == 40 and info['cardData']['license'] == 'apache-2.0'
    target = OUT/short/revision
    target.mkdir(parents=True)
    hashes = {}
    for name in ('onnx/model_qint8_arm64.onnx', 'config.json', 'tokenizer.json',
                 'tokenizer_config.json', 'special_tokens_map.json', 'README.md'):
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f'https://huggingface.co/{model}/resolve/{revision}/{name}', timeout=60) as response:
            data = response.read()
        path.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    config = json.loads((target/'config.json').read_text())
    assert config['model_type'] == 'bert' and config['num_hidden_layers'] in (2, 6)
    records.append({'model_id': model, 'revision': revision, 'root': str(target),
        'license': 'apache-2.0', 'artifacts': hashes, 'config': config,
        'graph_bytes': (target/'onnx/model_qint8_arm64.onnx').stat().st_size,
        'host_machine': platform.machine(),
        'scope': 'official public CPU int8 research assets; no quality/promotion claim'})
    (ROOT/'output/models/marco-pair-registration-v73.json').write_text(json.dumps(records, indent=2))
    print(json.dumps({k: records[-1][k] for k in ('model_id', 'revision', 'graph_bytes')}), flush=True)
