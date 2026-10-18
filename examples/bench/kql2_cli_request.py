"""Deliver one actual CLI handler response from a newly initialized process.

The envelope's timestamp lets the parent include stdout pipe delivery while
measuring process startup separately. The handler's complete JSON is retained.
"""

import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import time


def main() -> None:
    route, root_text, file_text, cache, *saved = sys.argv[1:]
    root, query_file = Path(root_text), Path(file_text)
    if route == 'kql2_cli':
        from ken.kql2.cli import configure, dispatch
        parser = argparse.ArgumentParser()
        configure(parser)
        entry = ['--saved', saved[0]] if saved else [file_text]
        args = parser.parse_args([*entry, '--root', root_text,
                                  '--cache-mb', cache, '--timeout-ms', '10'])
        def invoke():
            return dispatch(args)
    else:
        from ken.cli import _tools_cli
        from ken.mcp import server
        entry = ['--saved-query', saved[0]] if saved else ['--query', query_file.read_text()]
        def invoke():
            return _tools_cli(root, 'find', ['--scope', 'structure', '--query-language', 'kql/2',
                *entry, '--cache-mb', cache, '--timeout-ms', '10', '--full'],
                list_only=False, compact=False)
    from ken.kql2.process import prepare_process
    prepare_process(freeze=False)
    output = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(output):
        status = invoke()
    print(json.dumps({'started_at':started, 'status':status, 'output':output.getvalue()}), flush=True)


if __name__ == '__main__':
    main()
