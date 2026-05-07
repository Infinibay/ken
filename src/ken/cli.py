"""ken CLI dispatcher.

Subcommand layout:

    ken install [PATH]                  install + initial index
    ken status [PATH]                   show project state
    ken serve  [PATH]                   start the daemon (stub for now)
    ken hook session-start              hooks invoked by Claude Code (stubs)
    ken hook session-end
    ken hook user-prompt
    ken hook tool-call --phase pre|post
    ken hook stop
    ken uninstall [PATH]

Hook subcommands always read JSON from stdin (Claude Code passes the
event payload there) — for the stub phase they just acknowledge it
silently so the install flow is verifiable end-to-end.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ken import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ken")
    parser.add_argument("--version", action="version", version=f"ken {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="install ken into a project")
    p_install.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")
    p_install.add_argument("-q", "--quiet", action="store_true", help="suppress per-file index output")

    p_status = sub.add_parser("status", help="show ken project status")
    p_status.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")

    p_serve = sub.add_parser("serve", help="run the ken daemon (TODO)")
    p_serve.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")

    p_hook = sub.add_parser("hook", help="hook handlers invoked by Claude Code")
    hook_sub = p_hook.add_subparsers(dest="hook_cmd", required=True)
    hook_sub.add_parser("session-start")
    hook_sub.add_parser("session-end")
    hook_sub.add_parser("user-prompt")
    hook_sub.add_parser("stop")
    p_tool = hook_sub.add_parser("tool-call")
    p_tool.add_argument("--phase", choices=("pre", "post"), required=True)

    p_uninstall = sub.add_parser("uninstall", help="remove ken hooks from a project")
    p_uninstall.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")
    p_uninstall.add_argument("--keep-db", action="store_true", help="don't delete .ken/ken.db")

    args = parser.parse_args(argv)

    if args.cmd == "install":
        from ken.install import install

        install(Path(args.path), verbose=not args.quiet)
        return 0

    if args.cmd == "status":
        from ken.status import show_status

        return show_status(Path(args.path))

    if args.cmd == "serve":
        from ken.serve import serve

        return serve(Path(args.path))

    if args.cmd == "hook":
        from ken.hook import dispatch_hook

        return dispatch_hook(args)

    if args.cmd == "uninstall":
        from ken.install_uninstall import uninstall

        return uninstall(Path(args.path), keep_db=args.keep_db)

    parser.error(f"unknown command: {args.cmd}")
    return 2


def _read_hook_payload() -> dict:
    """Hook commands receive the event payload as JSON on stdin.

    Returns an empty dict if stdin is closed / not a pipe — useful when
    invoking a hook by hand for debugging.
    """
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
