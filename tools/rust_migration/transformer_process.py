"""One bounded native public call process, independent of numerical policy."""
from __future__ import annotations

import json, math, os, platform, selectors, shutil, signal, subprocess, tempfile, time
from pathlib import Path
from .fastembed_process import decode_frames, digest

RAW_LIMIT = 16 * 1024 * 1024


def run_transformer(probe: Path, request: dict, out: Path, *, deadline_s: float,
                    audit: bool = True) -> dict:
    if type(deadline_s) not in (int, float) or not math.isfinite(deadline_s) or deadline_s <= 0:
        raise ValueError('positive finite transformer deadline required')
    if not probe.is_absolute() or not probe.is_file() or not os.access(probe, os.X_OK):
        raise ValueError('explicit regular native executable required')
    with probe.open('rb') as source:
        if source.read(4) not in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
            raise ValueError('native executable required; interpreter scripts rejected')
    payload = json.dumps(request, allow_nan=False).encode()
    if len(payload) > RAW_LIMIT:
        raise ValueError('oversized transformer request')
    out.mkdir(parents=True, exist_ok=False)
    process = None
    started = None
    with tempfile.TemporaryDirectory(prefix='ken-transformer-process-') as temporary:
        root = Path(temporary)
        binary, inputs, private = root/'probe', root/'request.json', root/'private'
        private.mkdir(); (root/'sentinel').mkdir(); (root/'home').mkdir()
        shutil.copy2(probe, binary)
        identity = digest(probe)
        owned_request = dict(request)
        if 'private_parent' in owned_request:
            owned_request['private_parent'] = str(private)
        inputs.write_text(json.dumps(owned_request, allow_nan=False))
        (out/'inputs.json').write_bytes(inputs.read_bytes())
        environment = {k: v for k, v in os.environ.items() if k not in
                       {'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'PYTHONPATH'}}
        environment.update(PATH=str(root/'sentinel'), HOME=str(root/'home'), TMPDIR=str(root),
                           TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        command = [str(binary), str(inputs)]
        if platform.system() == 'Darwin':
            environment['DYLD_PRINT_LIBRARIES'] = '1'
        elif audit:
            tracer = shutil.which('strace')
            if tracer is None:
                raise ValueError('Linux execve and execveat audit required')
            command = [tracer, '--seccomp-bpf', '-f', '-e', 'trace=execve,execveat',
                       '-o', str(out/'exec.trace'), *command]
            environment['LD_DEBUG'] = 'libs'
        total = [0, 0]
        try:
            with selectors.DefaultSelector() as selector, (out/'stdout.json').open('wb') as stdout, (out/'stderr.log').open('wb') as stderr:
                started = time.monotonic()
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, cwd=root, env=environment,
                                           start_new_session=True, bufsize=0)
                for index, stream, output in [(0, process.stdout, stdout), (1, process.stderr, stderr)]:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, (index, output))
                deadline = started + deadline_s
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('transformer execution deadline exceeded')
                    for key, _ in selector.select(min(remaining, .05)):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj); continue
                        index, output = key.data
                        total[index] += len(data)
                        if total[index] > RAW_LIMIT:
                            raise ValueError('oversized transformer process output')
                        output.write(data)
                process.wait(timeout=max(.001, deadline-time.monotonic()))
                if process.returncode:
                    raise ValueError(f'native transformer exited {process.returncode}')
            frames = decode_frames((out/'stdout.json').read_text())
            if len(frames) != 1:
                raise ValueError('one JSON transformer response required')
            attempts = None
            if platform.system() == 'Linux' and audit:
                import re
                lines = [line for line in (out/'exec.trace').read_text().splitlines()
                         if re.search(r'\bexecve(?:at)?\(', line)]
                attempts = len(lines)
                if attempts != 1 or str(binary) not in lines[0]:
                    raise ValueError('only initial native exec allowed')
            if list(private.iterdir()):
                raise ValueError('native transformer left owned model/core files')
            if digest(binary) != identity or digest(probe) != identity:
                raise ValueError('native transformer executable changed')
            return {'actual': frames[0], 'receipt': {
                'native_sha256': identity, 'native_exit': 0, 'native_children': [],
                'outside_checkout': True, 'owned_after_exit': [], 'command': command,
                'execution_audit': audit, 'exec_attempts': attempts,
                'execution_audit_syscalls': ['execve', 'execveat'] if attempts is not None else [],
                'fixed_deadline_s': deadline_s, 'elapsed_s': time.monotonic()-started}}
        finally:
            if process is not None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
                process.stdout.close(); process.stderr.close()
