PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import os, sys, tempfile, types
from pathlib import Path
from unittest.mock import patch
repo = Path.cwd().resolve()
ken = types.ModuleType('ken')
ken.__path__ = [str(repo/'src/ken')]
sys.modules['ken'] = ken
from ken import _paths
from ken.daemon import client

with tempfile.TemporaryDirectory(dir=repo, prefix='.verify-') as d:
    root = Path(d)
    (root/'.ken').mkdir()
    (root/'.ken/meta.json').write_text('{}')
    nested = root/'a/b'
    nested.mkdir(parents=True)
    with patch.dict(os.environ, {}, clear=True):
        os.chdir(nested)
        try:
            assert _paths.find_project_root() == root
        finally:
            os.chdir(repo)
        with patch.dict(os.environ, KEN_PROJECT_ROOT=str(root)):
            assert _paths.find_project_root(nested) == root
        with patch.dict(os.environ, KEN_PROJECT_ROOT=str(nested)):
            assert _paths.find_project_root(nested) is None
        with patch.object(Path, 'is_file', return_value=False):
            assert _paths.find_project_root(nested) is None
    print('PASS raiz desde cwd, override valido/invalido y ausencia simulada')

    port = _paths.port_path(root)
    for scenario in ('existente', 'ausente', 'obsoleto', 'timeout'):
        port.write_text('12345')
        if scenario == 'ausente':
            port.unlink()
        effects = (
            [ConnectionRefusedError(), {'ok': True}] if scenario == 'obsoleto'
            else [TimeoutError()] if scenario == 'timeout'
            else [{'ok': True}]
        )
        with patch.object(client, '_request', side_effect=effects) as req, \
             patch.object(client, '_spawn_and_wait', return_value=23456) as spawn, \
             patch.object(client.logger, 'warning'):
            result = client._post_with_spawn(root, '/rank', {})
            assert result == (None if scenario == 'timeout' else {'ok': True})
            assert spawn.call_count == int(scenario in ('ausente', 'obsoleto'))
            assert req.call_count == (2 if scenario == 'obsoleto' else 1)
            assert port.exists() == (scenario in ('existente', 'timeout'))
        print('PASS puerto ' + scenario)
print('PASS limpieza automatica; HTTP y spawn simulados')
PY
