PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from ken._paths import resolve_project_path

with TemporaryDirectory(dir=Path.cwd(), prefix=".path-check-") as tmp:
    base = Path(tmp)
    root = base / "project"
    (root / "src").mkdir(parents=True)
    (root / "src/a.py").write_text("x = 1\n")
    (base / "outside").mkdir()
    for name, target in [
        ("inside", "src"),
        ("escape", "../outside"),
        ("broken-in", "missing.py"),
        ("broken-out", "../absent.py"),
    ]:
        (root / name).symlink_to(target)

    cases = [
        ("src/a.py", "src/a.py"),
        (root / "src/a.py", "src/a.py"),
        ("src/../src/a.py", "src/a.py"),
        ("../outside/a.py", None),
        (base / "outside/a.py", None),
        (base / "project-extra/a.py", None),
        ("inside/a.py", "src/a.py"),
        ("escape/a.py", None),
        ("new/absent.py", "new/absent.py"),
        (root / "new/absent.py", "new/absent.py"),
        ("broken-in", "missing.py"),
        ("broken-out", None),
        (".", "."),
    ]
    for supplied, expected in cases:
        try:
            actual = resolve_project_path(root, supplied)
        except ValueError as exc:
            assert expected is None
            assert str(exc).startswith("path escapes project root: ")
        else:
            assert expected is not None
            assert actual == root / expected
    print(f"{len(cases)} casos OK")
PY
