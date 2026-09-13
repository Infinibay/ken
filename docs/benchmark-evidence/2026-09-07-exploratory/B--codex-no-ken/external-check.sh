PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
import contextlib, io, os, tempfile
from pathlib import Path
from unittest.mock import patch
from ken import _paths, cli
from ken.daemon import client

with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
    root = Path(tmp).resolve()
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / ".ken").mkdir()
    (root / ".ken/meta.json").write_text("{}")

    with patch.dict(os.environ):
        os.environ.pop("KEN_PROJECT_ROOT", None)
        with contextlib.chdir(sub):
            assert _paths.find_project_root() == root
        os.environ["KEN_PROJECT_ROOT"] = str(sub)
        assert _paths.find_project_root(root) is None
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.main(["hook", "session-start"]) == 0
        assert "skipping hook" in err.getvalue()

    for port, replies, launches in [
        (12345, [{"ok": True}], 0),
        (None, [{"ok": True}], 1),
        (12345, [ConnectionRefusedError(), {"ok": True}], 1),
        (12345, [TimeoutError()], 0),
    ]:
        with patch.object(client, "_read_port", return_value=port), \
             patch.object(client, "_request", side_effect=replies), \
             patch.object(client, "_spawn_and_wait", return_value=23456) as spawn:
            client.post(root, "/rank", {})
            assert spawn.call_count == launches

    with contextlib.chdir(sub), \
         patch.object(client, "post", return_value={"ok": True}) as post, \
         contextlib.redirect_stdout(io.StringIO()):
        for command in ("rank", "explain"):
            assert cli.main([command, "consulta"]) == 0
            assert post.call_args.args[0] == sub
    print("OK: descubrimiento, errores, conexión y excepción rank/explain")
PY
