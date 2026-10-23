"""Prepare tiny byte fixtures through the frozen original test helper."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference

_CHILD = r'''
import hashlib,json,runpy,sys
from pathlib import Path
import ken.retrieval.translation_preparation as original
reference,root=map(Path,sys.argv[1:]);root.mkdir(parents=True)
if not Path(original.__file__).resolve().is_relative_to(reference/'src'):
 raise ValueError('original preparation import escaped frozen tree')
helper=reference/'tests/retrieval/test_translation_preparation.py'
namespace=runpy.run_path(str(helper))
source,definition,expected=namespace['translation_files'].__wrapped__(root)
prepared=root/'prepared'/definition['derived']['revision']
original.prepare_translation(definition,prepared,source_snapshot=source)
if {p.name:p.read_bytes() for p in prepared.iterdir()}!=expected:
 raise ValueError('original fixture did not produce its independently defined bytes')
result={'original_helper_verified':True,'helper':'tests/retrieval/test_translation_preparation.py',
 'helper_sha256':hashlib.sha256(helper.read_bytes()).hexdigest(),
 'source':str(source),'prepared':str(prepared),'definition':definition,
 'recipe_sha256':hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()}
saved=result|{'source':source.relative_to(root).as_posix(),'prepared':prepared.relative_to(root).as_posix()}
(root/'manifest.json').write_text(json.dumps(saved,indent=2)+'\n')
print(json.dumps(result))
'''


def generate_preparation(reference: Reference, output: Path) -> dict:
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('frozen source drift')
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-translation-fixture-') as directory:
        child = subprocess.run([str(reference.python), '-c', _CHILD, str(reference.root), str(output)],
                               cwd=output.parent, env=reference_env(reference, Path(directory)),
                               text=True, capture_output=True, timeout=120)
    output.with_suffix('.stderr.log').write_text(child.stderr)
    if child.returncode or child.stderr:
        raise ValueError(f'frozen translation fixture generation failed: {child.stderr}')
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('frozen source drift')
    return json.loads(child.stdout)
