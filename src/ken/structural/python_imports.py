"""Explicit Python module locations shared by acquisition and semantic linking."""

from pathlib import PurePosixPath
import posixpath


def targets(origin: str, module: str, paths: set[str]) -> list[str]:
    dots = len(module) - len(module.lstrip("."))
    tail = module[dots:].replace(".", "/")
    if dots:
        base = str(PurePosixPath(origin).parent)
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        stems = [posixpath.normpath(posixpath.join(base, tail))]
    else:
        stems = [
            tail,
            "src/" + tail,
            posixpath.join(str(PurePosixPath(origin).parent), tail),
        ]
    return sorted(
        {
            p
            for stem in stems
            for p in (stem + ".py", stem + "/__init__.py")
            if p in paths
        }
    )
