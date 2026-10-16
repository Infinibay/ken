"""Verify installed package against measured source and save actual CLI samples."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

w = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
root = Path('/Users/andres/Projects/ken')
package_root = Path('/Users/andres/.local/share/uv/tools/ken-rank/lib/python3.12/site-packages')
m = json.loads((w / 'output/frozen/public-qualified-locator-v172/SOURCE-MANIFEST.json').read_text())
for name, digest in m['files'].items():
    path = package_root / Path(name).relative_to('src')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
env = dict(os.environ)
env.pop('PYTHONPATH', None)
env['HF_HUB_OFFLINE'] = '1'
cli = '/Users/andres/.local/bin/ken'
base = [cli, 'tools', '--path', '/private/tmp/ken-output-demo-_2xptiit', 'find',
        'Locate the definition of reader::Reader.read_value.', '--scope', 'symbols']
captures = {}
for name, args in [('default-model', [cli, 'default-model']), ('compact', base),
                   ('json', base + ['--output-format', 'json'])]:
    start = time.perf_counter()
    result = subprocess.run(args, cwd='/private/tmp', env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    captures[name] = {'args': args, 'stdout': result.stdout, 'returncode': result.returncode,
                      'ms': (time.perf_counter() - start) * 1000}
data = json.loads(captures['json']['stdout'])
assert data['profile_version'] == 'best-exact-source-v1'
assert len(data['results']) == 1
assert data['results'][0]['path'] == 'reader.py'
assert data['results'][0]['entity']['qualname'] == 'Reader.read_value'
assert captures['compact']['stdout'].startswith('reader.py:6-8 :: Reader.read_value\n6 |')
receipt = {'status': 'ALL422INSTALLED_SOURCE_FILES_MATCH_ACTUAL_MCP_FREEZE',
           'source_commit': '11b0fd625999bc72cb613bfc94883e649e26b19e',
           'source_receipt': '3f56b5848be8fcb44ce6006b754a6cbfb6d609c872521437be5ceeefd6b36197',
           'verified_files': len(m['files']), 'captures': captures,
           'timing_scope': 'Single illustrative CLI observations, not latency benchmark',
           'mcp_existing_process_restarted': False, 'no_release_or_tag': True}
(root / 'output/global-default-final-v176.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'status': receipt['status'], 'files': len(m['files']),
                  'compact': captures['compact']['stdout']}))
