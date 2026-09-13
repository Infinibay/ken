PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

repo = Path.cwd().resolve()
spec = importlib.util.spec_from_file_location(
    'ken_paths_check', repo / 'src/ken/_paths.py'
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with TemporaryDirectory(prefix='.path-check-', dir=repo) as tmp:
    base = Path(tmp)
    root = base / 'project'
    outside = base / 'outside'
    sibling = base / 'project-extra'
    for directory in (root, outside, sibling):
        directory.mkdir()
        (directory / 'ok.txt').write_text('fixture', encoding='utf-8')
    (root / 'sub').mkdir()
    (root / 'link-in').symlink_to(root / 'ok.txt')
    (root / 'link-out').symlink_to(outside / 'ok.txt')
    (root / 'broken-in').symlink_to(root / 'missing.txt')
    (root / 'broken-out').symlink_to(outside / 'missing.txt')

    cases = [
        ('relative internal', 'ok.txt', root / 'ok.txt'),
        ('absolute internal', root / 'ok.txt', root / 'ok.txt'),
        ('absolute external', outside / 'ok.txt', None),
        ('parent escape', '../outside/ok.txt', None),
        ('parent internal', 'sub/../ok.txt', root / 'ok.txt'),
        ('sibling prefix', sibling / 'ok.txt', None),
        ('symlink internal', 'link-in', root / 'ok.txt'),
        ('symlink external', 'link-out', None),
        ('broken symlink internal', 'broken-in', root / 'missing.txt'),
        ('broken symlink external', 'broken-out', None),
        ('missing internal', 'missing.txt', root / 'missing.txt'),
        ('missing external', '../outside/missing.txt', None),
    ]
    for name, supplied, expected in cases:
        try:
            result = module.resolve_project_path(root, supplied)
        except ValueError as exc:
            assert expected is None, (name, exc)
            assert str(exc).startswith('path escapes project root: ')
            print(f'{name}: REJECT ValueError')
        else:
            assert expected is not None, (name, result)
            assert result == expected.resolve(), (name, result, expected)
            print(f'{name}: ACCEPT exists={result.exists()}')
    print(f'Assertions passed: {len(cases)} cases')

assert not base.exists(), 'Fixture cleanup failed'
print('Fixture removed')
PY
