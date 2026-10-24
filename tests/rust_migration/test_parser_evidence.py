"""Authenticate actual parser process bytes, not a controller's passing flag."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
from tools.rust_migration.parser_validate import parser_cases, run_parser_capture
from tools.rust_migration.parser_evidence import verify_parser_capture

REPO = Path(__file__).resolve().parents[2]

@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    prepared=os.environ.get('KEN_PARSER_NATIVE_CAPTURE')
    if prepared:return Path(prepared),parser_cases(REPO)
    out = tmp_path_factory.mktemp('parser-evidence') / 'capture'
    probe = Path(os.environ['KEN_PARSER_PROBE']).absolute()
    manifest = Path(os.environ['KEN_GRAMMAR_MANIFEST']).absolute()
    cases = parser_cases(REPO)
    run_parser_capture(REPO, probe, manifest, cases, out)
    return out, cases

def test_actual_external_process_audit_and_complete_results(capture):
    out, cases = capture
    assert verify_parser_capture(out, cases) == []

@pytest.mark.parametrize('name', ['stdout', 'request', 'grammar', 'source', 'binary', 'exit', 'loader', 'cwd', 'summary'])
def test_resealed_process_metadata_cannot_hide_bad_native_evidence(capture, tmp_path, name):
    saved, cases = capture; out = tmp_path / 'capture'; shutil.copytree(saved, out)
    if name == 'loader': (out / 'stderr.log').write_text('libpython3.12.dylib')
    else:
        file = {'stdout': 'stdout.json', 'request': 'inputs.json'}.get(name, 'execution.json')
        value = json.loads((out / file).read_bytes())
        if name == 'stdout': value['cases'].pop()
        elif name == 'request': value['cases'][0]['expected'] = {}
        elif name == 'grammar': value['resources'][0]['sha256'] = '0' * 64
        elif name == 'source': value['sources']['Cargo.lock']['sha256'] = '0' * 64
        elif name == 'binary': value['native_sha256'] = '0' * 64
        elif name == 'exit': value['exit'] = 1
        elif name == 'cwd': value['cwd'] = str(REPO)
        else: value['passed'] = True; value['case_count'] = 0
        (out / file).write_text(json.dumps(value))
    assert verify_parser_capture(out, cases)

@pytest.mark.parametrize('mutation', ['extra', 'hex', 'unicode_hex', 'duplicate', 'manifest'])
def test_native_transport_rejects_invalid_requests_before_success(mutation):
    manifest = Path(os.environ['KEN_GRAMMAR_MANIFEST']).absolute()
    request = {'manifest': str(manifest), 'cases': [{'id':'case','language':'python','hint':'a.py','source_hex':'646566206628293a2070617373'}]}
    if mutation == 'extra': request['cases'][0]['expected'] = {}
    elif mutation == 'hex': request['cases'][0]['source_hex'] = '0g'
    elif mutation == 'unicode_hex': request['cases'][0]['source_hex'] = 'é'
    elif mutation == 'duplicate': request['cases'].append(deepcopy(request['cases'][0]))
    else: request['manifest'] = '/nonexistent/manifest.json'
    result = subprocess.run([os.environ['KEN_PARSER_PROBE']], input=json.dumps(request).encode(), capture_output=True, timeout=10)
    assert result.returncode != 0 and not result.stdout
