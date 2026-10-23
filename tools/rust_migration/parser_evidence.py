"""Independent authentication of complete parser observations and native audits."""
from __future__ import annotations
import json
from pathlib import Path
import re
from .parser_validate import compare_parser_observations, load

def parser_rust_gate_errors(discovery: str, output: str) -> list[str]:
    """rustdoc adds its test mode only to execution, preserving the case identity."""
    from .integration_validate import rust_gate_errors
    normalized = re.sub(r'^(test .+) - compile fail( \.\.\. (?:ok|FAILED))$', r'\1\2', output, flags=re.M)
    return rust_gate_errors(discovery, normalized)

def verify_parser_capture(directory: Path, cases: list[dict], sources: dict | None = None,
                          native_sha256: str | None = None, lock: dict | None = None) -> list[str]:
    try:
        def require(value, message):
            if not value: raise ValueError(message)
        build = load(directory / 'BUILD.json'); receipt = load(directory / 'execution.json')
        require(set(receipt) == {'format', 'system', 'sources', 'native_sha256', 'resources', 'manifest', 'command', 'cwd', 'env', 'exit', 'timeout_s', 'case_count'}, 'unexpected execution fields or fabricated summary')
        require(receipt['format'] == 'ken-parser-execution/1' and receipt['exit'] == 0 and receipt['timeout_s'] == 60 and receipt['case_count'] == len(cases), 'native parser exit/bound/inventory differs')
        require(build == {key: receipt[key] for key in ('sources', 'native_sha256', 'resources', 'system')}, 'native build/source/grammar identity differs')
        require(re.fullmatch('[0-9a-f]{64}', receipt['native_sha256']) is not None, 'invalid native host identity')
        if sources is not None: require(receipt['sources'] == sources, 'native source snapshot differs')
        if native_sha256 is not None: require(receipt['native_sha256'] == native_sha256, 'native binary differs')
        root = Path(receipt['cwd']); command = receipt['command']; env = receipt['env']
        require(root.is_absolute() and root.name.startswith('ken-parser-process-') and command[-1] == str(root / 'parser-probe'), 'native parser not copied outside checkout')
        require(env['PATH'] == str(root / 'empty-path') and env['HOME'] == str(root / 'home'), 'isolated native environment differs')
        request = load(directory / 'inputs.json')
        require(request == {'manifest': str(root / 'sdk/manifest.json'), 'cases': [dict(id=c['id'], **c['input']) for c in cases]}, 'actual native request differs or contains expectations')
        manifest = receipt['manifest']
        require(manifest['libraries'] == receipt['resources'] and manifest['format'] == 'ken-native-grammars/1', 'prepared grammar manifest differs')
        require(len(receipt['resources']) == 13 and len({r['language'] for r in receipt['resources']}) == 13, 'complete dynamic grammar inventory required')
        if lock is not None:
            platform = lock['pack']['bundles'][manifest['platform']]
            expected = [{**{'language': name}, **{k: row[k] for k in ('file', 'bytes', 'sha256')}} for name, row in sorted(platform['libraries'].items())]
            require(receipt['resources'] == expected and manifest['pack_version'] == lock['pack']['version'] and manifest['pack_revision'] == lock['pack']['revision'], 'pinned grammar resources differ')
        loader = (directory / 'stderr.log').read_bytes()
        require(len(loader) <= 16 * 1024 * 1024 and b'libpython' not in loader and b'libtorch_python' not in loader, 'forbidden Python linkage or oversized loader evidence')
        if receipt['system'] == 'linux':
            require(Path(command[0]).name == 'strace' and command[1:5] == ['--seccomp-bpf', '-f', '-e', 'trace=execve,execveat,connect'], 'actual Linux audit command differs')
            trace = (directory / 'exec.trace').read_text()
            require(len(re.findall(r'\bexecve(?:at)?\(', trace)) == 1 and command[-1] in trace and not re.search(r'\bconnect\(', trace), 'unexpected native subprocess/network')
            require(env['LD_DEBUG'] == 'libs' and b'calling init:' in loader, 'actual Linux loader audit missing')
        else:
            require(receipt['system'] == 'macos' and command == [str(root / 'parser-probe')] and env['DYLD_PRINT_LIBRARIES'] == '1' and b'dyld[' in loader, 'actual macOS loader audit missing')
        errors = compare_parser_observations(cases, load(directory / 'stdout.json'))
        require(not errors, '; '.join(errors))
        return []
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error: return [str(error)]


def aggregate_parser_matrix(directory: Path, repo: Path, *, current: bool = False) -> dict:
    """Accept M3b only, authenticating historical sources and both native platforms."""
    import hashlib
    import tarfile
    import tempfile
    from .integration_validate import _manifest_errors, rust_gate_errors
    from .parser_reference import validate_parser_reference, parser_owner_hashes
    from .parser_validate import source_identity, identity, parser_cases
    from .receipts import junit_states
    from .reference import verify_reference
    result = dict(passed=False, M3b_accepted=False, M3_accepted=False, migration_complete=False, errors=[])
    try:
        def require(value, message):
            if not value: raise ValueError(message)
        errors = _manifest_errors(directory); require(not errors, '; '.join(errors))
        index = load(directory / 'INDEX.json')
        require(index['format'] in ('ken-parser-matrix/1', 'ken-parser-review-repair/1'), 'wrong parser matrix protocol')
        repaired = index['format'] == 'ken-parser-review-repair/1'
        snapshot = directory / 'native-sources'
        require(index['sources'] == source_identity(snapshot), 'native source snapshot differs')
        if current: require(index['sources'] == source_identity(repo), 'current parser source differs')
        for name, expected in index['tooling'].items():
            require(not Path(name).is_absolute() and '..' not in Path(name).parts and identity(directory / 'validation-sources' / name) == expected, 'validation source differs')
        predecessor = dict(path='docs/validation/rust-migration-2026-10-23/m3-source-review', sha256='3a9448aa7489e9c9a99bbf80b6e70e0ed61f1beaf063208f4944443b0340caa9')
        if repaired:
            predecessor = dict(path='docs/validation/rust-migration-2026-10-23/m3-parsers', sha256='263308848530d463d8c807d15d79dbedd586b25eb10fb6968ae3fa24aa7d4edd')
        require(index['predecessor'] == predecessor, 'accepted source discovery predecessor differs')
        require(identity(repo / predecessor['path'] / 'FILES.json')['sha256'] == predecessor['sha256'], 'source discovery receipt changed')
        require(not _manifest_errors(repo / predecessor['path']), 'source discovery artifact changed')
        require(not verify_reference(repo, repo / 'docs/validation/rust-migration-2026-10-18/baseline.json'), 'original files changed')
        require(set(index['platforms']) == {'macos', 'linux'}, 'both actual platforms required')
        cases = parser_cases(snapshot)
        require(len(cases) == (249 if repaired else 239) and len({c['input']['language'] for c in cases}) == 19, 'complete original case inventory required')
        fixtures = snapshot / 'crates/ken-syntax/tests/fixtures'
        for name in ('parser-edges', 'parser-errors', 'c-macro-digits'):
            supplemental = load(fixtures / (name + '.json'))
            executions = supplemental.get('executions', [supplemental])
            observed = []
            for execution in executions:
                require(execution['execution']['exit'] == 0 and bool(execution['script']), 'supplemental original execution missing/failed')
                observed.extend(json.loads(execution['execution']['stdout'])['cases'])
            require(observed == supplemental['cases'], 'supplemental original raw observations differ')
            if 'owners' in supplemental: require(supplemental['owners'] == parser_owner_hashes(repo), 'supplemental original owners differ')
        if repaired:
            supplemental = load(fixtures / 'review-cases.json')
            require(supplemental['owners'] == parser_owner_hashes(repo) and supplemental['execution']['exit'] == 0 and bool(supplemental['script']), 'review original owner/execution differs')
            require(json.loads(supplemental['execution']['stdout'])['cases'] == supplemental['cases'] and len(supplemental['cases']) == 10, 'review raw original observations differ')
            linux_review = load(directory / 'research/original-review-linux.json')
            require(linux_review['execution']['exit'] == 0 and bool(linux_review['script']), 'original Linux review execution missing/failed')
            observed = json.loads(linux_review['execution']['stdout'])
            require(observed['cases'] == supplemental['cases'] and observed['runtime'] == {'system': 'Linux', 'machine': 'aarch64'}, 'original Linux review inputs/platform differ')
            require(observed['owners'] == {k: v for k, v in parser_owner_hashes(repo).items() if k.startswith('src/ken/parsers/')}, 'actual original Linux module origins differ')
        original_cases = None
        for system, platform in index['platforms'].items():
            with tempfile.TemporaryDirectory(prefix='ken-parser-replay-') as temporary:
                raw = Path(temporary)
                with tarfile.open(directory / f'{system}-capture.tar.gz') as archive:
                    archive.extractall(raw, filter='data')
                original = load(raw / 'original/reference.json')
                require(not validate_parser_reference(original), 'invalid original parser reference')
                require(original['owners'] == parser_owner_hashes(repo), 'original parser owners differ')
                require(len(original['cases']) == 215 and len(original['discovered']) == 124, 'complete original suite inventory required')
                runtime = original['runtime']
                require((runtime['system'], runtime['machine'], runtime['python']) == (('Darwin', 'arm64', '3.12.9') if system == 'macos' else ('Linux', 'aarch64', '3.12.9')), 'original platform differs')
                if original_cases is None: original_cases = original['cases']
                require(original['cases'] == original_cases == load(snapshot / 'crates/ken-syntax/tests/fixtures/reference.json')['cases'], 'original platform corpus differs')
                execution = original['test_execution']
                for file, key in [('stdout.log', 'stdout_sha256'), ('stderr.log', 'stderr_sha256'), ('original-observations.json', 'observations_sha256')]:
                    require(identity(raw / 'original' / file)['sha256'] == execution[key], 'raw original process bytes differ')
                observed = load(raw / 'original/original-observations.json')
                require(all(original[k] == v for k, v in observed.items()), 'raw original parser observations differ')
                require(len(junit_states(raw / 'original/original-tests.xml')) == 124 and set(junit_states(raw / 'original/original-tests.xml').values()) == {'passed'}, 'actual original suite failed')
                errors = verify_parser_capture(raw / 'native', cases, index['sources'], platform['native_sha256'], load(snapshot / 'crates/ken-syntax/grammars.lock.json'))
                require(not errors, '; '.join(errors))
                require(load(raw / 'native/execution.json')['system'] == system, 'native platform differs')
            gates = directory / 'gates' / system
            require(not parser_rust_gate_errors((gates / 'rust-list.log').read_text(), (gates / 'rust-tests.log').read_text()), 'native syntax regression suite differs')
            require(len(re.findall(r'^([^\n]+): test$', (gates / 'rust-list.log').read_text(), re.M)) == (33 if repaired else 31), 'complete native syntax tests required')
            states = junit_states(gates / 'python.xml')
            discovered = {path[:-3].replace('/', '.') + '::' + name for path, name in re.findall(r'^(tests/rust_migration/test_(?:parser_[^:\n]+|grammar_prepare)\.py)::(.+)$', (gates / 'python-list.log').read_text(), re.M)}
            require(len(discovered) == 38 and set(states) == discovered and set(states.values()) == {'passed'}, 'complete affected tooling suite required')
            clippy = (gates / 'clippy.log').read_text()
            require('Finished `dev` profile' in clippy and 'error:' not in clippy and 'warning:' not in clippy, 'clippy failed/missing')
            require((gates / 'fmt.log').read_bytes() == b'', 'format failed')
        result.update(passed=True, M3b_accepted=True, per_platform=dict(Rust=33 if repaired else 31, Python=38, cases=249 if repaired else 239, grammar_shapes=215))
    except (OSError, ValueError, KeyError, TypeError, IndexError, tarfile.TarError) as error: result['errors'].append(str(error))
    return result
