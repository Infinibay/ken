"""Verify the actual noneditable global package and its default CLI/MCP output."""
import asyncio
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys

import ken
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

c = Path('/Users/andres/.codex/worktrees/compact-default-output/ken')
r = Path('/Users/andres/Projects/ken')
expected = json.loads((c / 'docs/validation/compact-output-2026-10-16-best-default/source-receipt-v178.json').read_text())
package = Path(ken.__file__).resolve()
assert package.is_relative_to('/Users/andres/.local/share/uv/tools/ken-rank/')
site = package.parent.parent
for name, digest in expected['source_files'].items():
    assert name.startswith('src/')
    target = site / Path(name).relative_to('src')
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest, name
direct = json.loads(metadata.distribution('ken-rank').read_text('direct_url.json'))
assert 'dir_info' not in direct
fixture = Path(expected['fixture'])
env = dict(os.environ)
env.pop('PYTHONPATH', None)
env['HF_HUB_OFFLINE'] = '1'
cli = '/Users/andres/.local/bin/ken'
question = 'Who reads stored application settings?'
args = [cli, 'tools', '--path', str(fixture), 'who', question, '--path', 'reader.py']
text = subprocess.check_output(args, env=env, cwd='/private/tmp', text=True)
assert 'return get_value(key)' in text and '6 |' in text and 'score_kind' not in text
raw = json.loads(subprocess.check_output(args + ['--output-format', 'json', '--full'], env=env, cwd='/private/tmp', text=True))
first = raw['candidates'][0]
assert first['symbol'] == 'Reader'
assert first['source']['sha256'] == hashlib.sha256((fixture / 'reader.py').read_bytes()).hexdigest()
default = subprocess.check_output([cli, 'default-model'], env=env, cwd='/private/tmp', text=True)
assert 'minishlab/potion-code-16M-v2' in default
captures = []

async def exercise():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'ken', 'mcp', str(fixture)], env=env)
    with Path('/private/tmp/ken-installed-output-mcp-v178.log').open('w') as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for tool, arguments in [('ken_who', {'question': question, 'path': 'reader.py'}),
                                        ('ken_calculate', {'expression': '(1/3 + 1/6) * 6'})]:
                    reply = await session.call_tool(tool, arguments)
                    assert not reply.is_error and not reply.structured_content
                    output = '\n'.join(p.text for p in reply.content)
                    if tool == 'ken_who':
                        assert 'return get_value(key)' in output and 'score_kind' not in output
                    else:
                        assert output == '(1/3 + 1/6) * 6 = 3'
                    captures.append({'tool': tool, 'arguments': arguments, 'output': output})

asyncio.run(exercise())
wheel = Path(sys.argv[1])
receipt = {'status': 'VERIFIED_GLOBAL_NONEDITABLE_PACKAGE_AND_ACTUAL_DEFAULT_CLI_MCP',
           'source_commit': sys.argv[2], 'package_file': str(package), 'package_version': metadata.version('ken-rank'),
           'verified_package_files': len(expected['source_files']),
           'source_receipt_sha256': hashlib.sha256((c / 'docs/validation/compact-output-2026-10-16-best-default/source-receipt-v178.json').read_bytes()).hexdigest(),
           'direct_url': direct, 'wheel_bytes': wheel.stat().st_size,
           'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
           'default_model_output': default, 'cli_who': text, 'new_global_mcp': captures,
           'no_release_or_tag': True, 'existing_mcp_process_restarted': False,
           'scope': 'Installed output proof only; no accuracy/latency claim or private benchmark inputs.'}
(r / 'output/installed-useful-output-v178.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'status': receipt['status'], 'source_commit': receipt['source_commit'],
                  'files': receipt['verified_package_files'], 'cli_who': text}))
