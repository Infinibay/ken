"""Public native4.4M weights for bounded CPU-only domain adaptation research."""
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
prior = json.loads((ROOT/'output/models/marco-pair-registration-v73.json').read_text())[0]
assert prior['revision'] == '81d1926f67cb8eee2c2be17ca9f793c7c3bd20cc'
OUT = Path('/private/tmp/ken-search-eval-20261014/marco-tiny-native-v75')/prior['revision']
OUT.mkdir(parents=True, exist_ok=False)
files = {}
for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'README.md'):
    source = Path(prior['root'])/name
    assert hashlib.sha256(source.read_bytes()).hexdigest() == prior['artifacts'][name]
    shutil.copy2(source, OUT/name)
    files[name] = prior['artifacts'][name]
with urllib.request.urlopen(f'https://huggingface.co/{prior["model_id"]}/resolve/{prior["revision"]}/model.safetensors', timeout=60) as response:
    data = response.read()
(OUT/'model.safetensors').write_bytes(data)
files['model.safetensors'] = hashlib.sha256(data).hexdigest()
record = {'model_id': prior['model_id'], 'revision': prior['revision'], 'license': prior['license'],
    'root': str(OUT), 'artifacts': files, 'weight_bytes': len(data),
    'scope': 'public safetensors only, native CPU offline adaptation research; no queries/code sent'}
(ROOT/'output/models/marco-tiny-native-registration-v75.json').write_text(json.dumps(record, indent=2))
print(json.dumps({k: record[k] for k in ('model_id', 'revision', 'weight_bytes')}), flush=True)
