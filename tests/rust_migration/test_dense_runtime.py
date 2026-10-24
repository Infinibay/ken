"""Native sidecar selection follows the execution architecture, including replay."""
from pathlib import Path
import pytest
from tools.rust_migration.retrieval_validate import runtime_manifest, runtime_files

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('architecture,library,count', [
    ('aarch64', 'libscipy_openblas64_-7220728c.so', 2),
    ('x86_64', 'libscipy_openblas64_-32a4b2a6.so', 3),
])
def test_sidecar_inventory_selects_the_recorded_execution_architecture(architecture, library, count):
    manifest = runtime_manifest(ROOT, architecture)
    assert manifest['platform'] == 'linux-' + architecture
    assert manifest['library'] == library
    assert manifest['files'] == runtime_files(ROOT, architecture)
    assert len(manifest['files']) == count
    assert all(r['bytes'] > 0 and len(r['sha256']) == 64 for r in manifest['files'].values())

def test_unknown_architecture_is_rejected_before_loading():
    with pytest.raises(ValueError, match='unregistered dense runtime architecture'):
        runtime_manifest(ROOT, 'riscv64')
