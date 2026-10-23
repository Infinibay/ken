"""Capture the frozen Python owner's source membership on actual project trees."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from .reference import Reference, reference_env

OWNERS = ('src/ken/_paths.py', 'src/ken/gitignore_filter.py')

CAPTURE = r'''
import hashlib, importlib.metadata, json, pathlib, platform, sys, tempfile
from ken.gitignore_filter import GitignoreMatcher, iter_entries, iter_files
import ken.gitignore_filter, ken._paths
request = json.load(sys.stdin)
root = pathlib.Path(request['reference']).resolve()
for module in (ken.gitignore_filter, ken._paths):
    if not pathlib.Path(module.__file__).resolve().is_relative_to(root):
        raise ValueError('wrong original module')
rows = []
for case in request['cases']:
    with tempfile.TemporaryDirectory(prefix='ken-source-original-') as directory:
        project = pathlib.Path(directory)
        for name, content in case.get('files', {}).items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode('utf-8'))
        for name, content in case.get('byte_files', {}).items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes.fromhex(content))
        for name, target in case.get('links', {}).items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        matcher = GitignoreMatcher(project)
        ignored = [matcher.is_ignored(pathlib.Path(q['path']), is_dir=q['is_dir'])
                   for q in case.get('queries', [])]
        walks = []
        for scope in case.get('scopes', ['.']):
            try:
                entries = [{'path': p.as_posix(), 'is_dir': d}
                           for p, d in iter_entries(project, path=scope)]
                files = [p.as_posix() for p in iter_files(project, path=scope)]
                walks.append(dict(scope=scope, entries=entries, files=files))
            except Exception as error:
                walks.append(dict(scope=scope, error=dict(type=type(error).__name__, message=str(error))))
        rows.append(dict(id=case['id'], ignored=ignored, walks=walks))
print(json.dumps(dict(cases=rows, runtime=dict(python=platform.python_version(),
    system=platform.system(), machine=platform.machine(), pathspec=importlib.metadata.version('pathspec')))))
'''


def capture_sources(reference: Reference, cases: list[dict], expected_sources: dict[str, str],
                    sandbox: Path) -> dict:
    """Fail on owner drift before importing anything from the original checkout."""
    if set(expected_sources) != set(OWNERS):
        raise ValueError('complete original source identities required')
    for name, digest in expected_sources.items():
        try:
            actual = hashlib.sha256((reference.root / name).read_bytes()).hexdigest()
        except OSError as error:
            raise ValueError('missing original source: ' + name) from error
        if actual != digest:
            raise ValueError('changed original source: ' + name)
    execution = subprocess.run(
        [str(reference.python), '-c', CAPTURE], cwd=reference.root,
        env=reference_env(reference, sandbox), text=True,
        input=json.dumps({'reference': str(reference.root), 'cases': cases}),
        capture_output=True, timeout=60, check=False)
    if execution.returncode:
        raise RuntimeError('original source capture failed: ' + execution.stderr[-4000:])
    if len(execution.stdout.encode()) > 8 * 1024 * 1024:
        raise ValueError('original source capture exceeded bound')
    result = json.loads(execution.stdout)
    result.update(format='ken-source-reference/1', sources=expected_sources,
                  definitions=cases, script_sha256=hashlib.sha256(CAPTURE.encode()).hexdigest(),
                  execution={'exit': execution.returncode, 'stderr': execution.stderr,
                             'stdout': execution.stdout})
    return result


def compatibility_cases() -> list[dict]:
    """Inputs only; every decision/order is obtained from the original process."""
    builtins = ('.ken/', '.git/', '.hg/', '.svn/', '.claude/', '.agents/skills/',
                '.opencode/skills/', '.dsh/skills/', '__pycache__/', '*.pyc', '.venv/',
                'node_modules/', 'target/', 'dist/', 'build/', '.DS_Store')
    files = {'good.py': '', '.hidden': ''}
    queries = []
    for pattern in builtins:
        if pattern.endswith('/'):
            directory = pattern[:-1]
            files[directory + '/source.py'] = ''
            queries += [{'path': directory, 'is_dir': True},
                        {'path': directory + '/source.py', 'is_dir': False}]
        else:
            filename = 'compiled.pyc' if pattern == '*.pyc' else pattern
            files[filename] = files['nested/' + filename] = ''
            queries += [{'path': filename, 'is_dir': False},
                        {'path': 'nested/' + filename, 'is_dir': False}]
    cases = [{'id': 'builtins', 'files': files, 'queries': queries, 'scopes': ['.']}]
    candidates = ('root.txt', 'nested/root.txt', 'a.log', 'nested/a.log',
                  'keep.log', 'nested/keep.log', 'space name.txt', '#hash', '!bang',
                  'file1.txt', 'file9.txt', 'filea.txt', 'file[.txt', 'trailing ',
                  'src/main.py', 'src/deep/main.py', 'pkg/cache/a', 'cache/a',
                  'café/niño.rs', '.hidden', 'bad\ufffd.txt')
    patterns = [
        ('glob', '*.log\n!keep.log\n'),
        ('anchored', '/root.txt\n'),
        ('double-star', '**/main.py\n!src/deep/main.py\n'),
        ('directories', 'cache/\n'),
        ('classes', 'file[0-9].txt\n!file9.txt\n'),
        ('unclosed-class', 'file[.txt\n'),
        ('escapes', r'space\ name.txt' + '\n' + r'\#hash' + '\n' + r'\!bang' + '\n'),
        ('trailing-spaces', 'trailing\\ \n# comment\n'),
        ('line-separators', 'root.txt\r\na.log\rkeep.log\x0bfile1.txt\x0cfile9.txt'
                            '\x1cfilea.txt\x1dspace name.txt\x1e#hash\x85!bang\u2028.hidden\u2029'),
        ('unicode', 'café/\n'),
    ]
    for name, rules in patterns:
        inputs = {p: '' for p in candidates}
        inputs['.gitignore'] = rules
        cases.append({'id': name, 'files': inputs,
                      'queries': [{'path': p, 'is_dir': False} for p in candidates] +
                                 [{'path': 'cache', 'is_dir': True}, {'path': 'cache', 'is_dir': False}],
                      'scopes': ['.', 'src', 'missing', 'root.txt']})
    cases += [
        {'id': 'barriers-and-scopes', 'files': {
            '.gitignore': '*.env\ndrop.py\nignored/\n',
            '.kenignore': 'archive/\nsrc/*.py\n!src/keep.py\n!secret.env\n!.ken/\n',
            'pkg/.gitignore': '*.py\n!src/keep.py\n',
            'ignored/src/.gitignore': '!keep.py\n',
            'secret.env': '', 'src/drop.py': '', 'src/keep.py': '',
            'pkg/src/drop.py': '', 'pkg/src/keep.py': '', 'sibling/other.py': '',
            'archive/old.py': '', '.ken/cache.py': '', 'ignored/src/keep.py': ''},
         'queries': [{'path': p, 'is_dir': False} for p in
                     ('secret.env', 'src/keep.py', 'src/drop.py', '.ken/cache.py',
                      'pkg/src/keep.py', 'pkg/src/drop.py')],
         'scopes': ['.', 'pkg/src', 'ignored/src', 'archive', '..']},
        {'id': 'invalid-utf8-rules', 'files': {'bad\ufffd.txt': '', 'good.py': ''},
         'byte_files': {'.gitignore': b'bad\xff.txt\n'.hex()},
         'queries': [{'path': 'bad\ufffd.txt', 'is_dir': False}], 'scopes': ['.']},
        {'id': 'internal-alias', 'files': {'pkg/a.py': '', 'pkg/b.py': ''},
         'links': {'alias': 'pkg'}, 'queries': [], 'scopes': ['.', 'alias']},
        {'id': 'nested-kenignore-is-data', 'files': {
            'pkg/.kenignore': '*.py\n', 'pkg/keep.py': '', '.gitignore': ''},
         'queries': [{'path': 'pkg/keep.py', 'is_dir': False}], 'scopes': ['.', 'pkg']},
    ]
    return cases
