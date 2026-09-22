"""Serialize graph acquisition across processes, not query execution."""
from __future__ import annotations

import fcntl
from pathlib import Path
from typing import BinaryIO


class AcquisitionLock:
    def __init__(self, database: Path, *, enabled: bool):
        self.handle: BinaryIO | None = None
        if enabled:
            database.parent.mkdir(parents=True, exist_ok=True)
            handle = database.with_suffix('.acquire.lock').open('ab')
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except BaseException:
                handle.close()
                raise
            self.handle = handle

    def close(self) -> None:
        if self.handle is not None:
            handle, self.handle = self.handle, None
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
