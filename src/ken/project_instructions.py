"""Optional project guidance with ownership separate from user instructions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

from ken.skills.ownership import write_atomic

STATE = '.ken/instructions.json'
AGENTS_START, AGENTS_END = '<!-- ken:instructions:start -->', '<!-- ken:instructions:end -->'
CLAUDE_START, CLAUDE_END = '<!-- ken:agents-import:start -->', '<!-- ken:agents-import:end -->'

GUIDANCE = '''## Code intelligence: ken

Use Ken to locate code and reuse project findings. If a `<context-rank>` block
already names the relevant file, read it before searching again.

Write natural-language code-search queries in **English**, translating the
user's intent yourself. Keep identifiers, paths, quoted source, regexes and
KQL unchanged. Reply to the user in their preferred language.

Start with one focused `ken_find(query=..., scope=...)`: `symbols` for a
function or class, `files` for a file or module, `wiring` for an entry point,
and `text` with `literal=true` for exact source. State the requested piece;
use `piece_kind="class"`, `"module"`, `"symbol"` or `"file"` when known.
Use `purpose="tests"` for tests and distinguish test cases from test helpers.

Read the returned code to verify a match. Compact results are the default;
use `ken_read` for more source and `full=true` only when debugging a ranking.
After two unhelpful searches, read the likeliest file or use a literal search.

Before editing an unfamiliar file, check `ken_recall(path=...)`. For a shared
change, inspect `ken_related(..., relation="blast_radius")` and its tests.
Save non-obvious findings with `ken_remember`, anchored to the relevant file
or symbol; include evidence, assumptions and a recheck step for conclusions.
'''

_SECTIONS = {'AGENTS.md': (AGENTS_START, AGENTS_END, GUIDANCE),
             'CLAUDE.md': (CLAUDE_START, CLAUDE_END, '@AGENTS.md\n')}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def _path(root: Path, relative: str) -> Path:
    result = root
    for part in Path(relative).parts:
        result = result / part
        if result.is_symlink():
            raise ValueError(f'{relative} is a symlink; preserving it')
    return result


def _state(root: Path) -> dict:
    path = _path(root, STATE)
    if not path.exists():
        return {'version': 1, 'files': {}}
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('files'), dict):
        raise ValueError(f'invalid {STATE}; preserving existing instructions')
    for name, record in value['files'].items():
        if (name not in _SECTIONS or not isinstance(record, dict)
                or not isinstance(record.get('sha256'), str)
                or not re.fullmatch('[a-f0-9]{64}', record['sha256'])
                or type(record.get('created')) is not bool):
            raise ValueError(f'invalid ownership in {STATE}')
    return value


def _region(text: str, name: str) -> tuple[int, int] | None:
    start, end, _ = _SECTIONS[name]
    if start not in text and end not in text:
        return None
    if text.count(start) != 1 or text.count(end) != 1 or text.index(end) < text.index(start):
        raise ValueError(f'{name} has incomplete Ken markers; preserving it')
    return text.index(start), text.index(end) + len(end)


def _put(root: Path, name: str, state: dict) -> None:
    path = _path(root, name)
    previous = path.read_bytes() if path.exists() else b''
    text = previous.decode('utf8')
    region = _region(text, name)
    old = state['files'].get(name)
    if region is None and name == 'AGENTS.md' and re.search(r'^##\s+Code intelligence:\s*ken\s*$', text, re.M | re.I):
        raise ValueError('AGENTS.md already has user-managed Ken guidance; preserving it')
    if region is None and name == 'CLAUDE.md' and re.search(r'^\s*@(?:\./)?AGENTS\.md\s*$', text, re.M):
        return
    a, b = region or (len(text), len(text))
    start, end, content = _SECTIONS[name]
    newline = '\r\n' if '\r\n' in text else '\n'
    block = ('\n'.join((start, content.rstrip(), end))).replace('\n', newline)
    if region:
        current = text[a:b]
        if current == block:
            return  # Do not adopt an existing unowned block.
        if not old or _digest(current) != old['sha256']:
            raise ValueError(f'{name} has locally edited or unowned Ken guidance; preserving it')
        updated = text[:a] + block + text[b:]
    else:
        separator = '' if not text else (newline if text.endswith('\n') else newline * 2)
        updated = text + separator + block + newline
    if path.exists() and path.read_bytes() != previous:
        raise ValueError(f'{name} changed while preparing instructions; preserving it')
    created = old['created'] if old else not path.exists()
    write_atomic(path, updated.encode('utf8'))
    state['files'][name] = {'sha256': _digest(block), 'created': created}
    write_atomic(_path(root, STATE), (json.dumps(state, indent=2) + '\n').encode())


def configure_instructions(root: Path, *, choice: bool | None = None,
                           claude: bool = False, verbose: bool = True) -> None:
    """Ask in a terminal, or obey an explicit CLI choice without reading stdin."""
    if choice is False or (choice is None and (not verbose or not sys.stdin.isatty())):
        return
    try:
        state = _state(root)
        if choice is None:
            suffix = ' (with a CLAUDE.md import)' if claude else ''
            while True:
                try:
                    answer = input(f'Append Ken instructions to AGENTS.md{suffix}? [Y/n]: ').strip().casefold()
                except EOFError:
                    return
                if answer in {'n', 'no'}:
                    return
                if answer in {'', 'y', 'yes'}:
                    break
                print('Please answer y or n.')
        _put(root, 'AGENTS.md', state)
        if claude:
            _put(root, 'CLAUDE.md', state)
        if verbose:
            print('[instructions] Ken guidance is available in AGENTS.md')
    except (ValueError, OSError, UnicodeError) as exc:
        print(f'[instructions] {exc}', file=sys.stderr)


def remove_instructions(root: Path) -> None:
    """Remove unchanged owned sections; edited instructions remain user content."""
    try:
        state = _state(root)
        for name, record in state['files'].items():
            try:
                path = _path(root, name)
                if not path.exists():
                    continue
                text = path.read_bytes().decode('utf8')
                region = _region(text, name)
                if region is None:
                    continue
                a, b = region
                if _digest(text[a:b]) != record['sha256']:
                    print(f'[instructions] preserving locally edited {name}')
                    continue
                remaining = text[:a] + text[b:]
                if record['created'] and not remaining.strip():
                    path.unlink()
                else:
                    write_atomic(path, remaining.encode('utf8'))
            except (ValueError, OSError, UnicodeError) as exc:
                print(f'[instructions] {exc}', file=sys.stderr)
        _path(root, STATE).unlink(missing_ok=True)
    except (ValueError, OSError, UnicodeError) as exc:
        print(f'[instructions] {exc}', file=sys.stderr)
