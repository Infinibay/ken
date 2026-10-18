"""Prepare an owned process before it accepts prepared query requests."""

from __future__ import annotations

import gc
import os

_prepared_pid: int | None = None
_frozen_pid: int | None = None


def prepare_process(*, freeze: bool) -> None:
    """Collect startup garbage; optionally exclude its live graph until exit.

    Only process entrypoints own this policy. Embedded query clients and sessions
    never change their caller's collector. New objects remain collectible and a
    process startup policy remains in effect until that dedicated process exits.
    """
    from . import automatic
    from ken.checks import report

    global _prepared_pid, _frozen_pid
    pid = os.getpid()
    if _prepared_pid != pid:
        gc.collect()
        _prepared_pid = pid
    if freeze and _frozen_pid != pid:
        gc.freeze()
        _frozen_pid = pid
