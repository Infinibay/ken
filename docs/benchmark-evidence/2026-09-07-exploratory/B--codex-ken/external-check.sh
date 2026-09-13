PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 - <<'PY'
import os, tempfile
from pathlib import Path
from unittest.mock import patch
from ken import _paths
from ken.daemon import client
from ken.cli import _rank_cli

with tempfile.TemporaryDirectory(dir=".") as d:
    root = Path(d).resolve()
    sub = root / "a/b"
    sub.mkdir(parents=True)
    (root / ".ken").mkdir()
    (root / ".ken/meta.json").write_text("{}")
    with patch.dict(os.environ, {}, clear=True):
        assert _paths.find_project_root(sub) == root
        with patch.dict(os.environ, {"KEN_PROJECT_ROOT": str(sub)}):
            assert _paths.find_project_root(sub) is None

    cases = [
        ("existente", 12345, [{"ok": True}], False),
        ("ausente", None, [{"ok": True}], True),
        ("obsoleto", 12345, [ConnectionRefusedError(), {"ok": True}], True),
        ("timeout", 12345, [TimeoutError()], False),
    ]
    for name, port, replies, expected in cases:
        with (
            patch.object(client, "_read_port", return_value=port),
            patch.object(client, "_request", side_effect=replies),
            patch.object(client, "_spawn_and_wait", return_value=23456) as spawn,
            patch.object(client, "_clear_port_file") as clear,
        ):
            client._post_with_spawn(root, "/rank", {})
            assert spawn.called == expected
            assert clear.called == (name == "obsoleto")
            print(name, "OK")

    with patch.object(client, "post", return_value={"ok": True}) as post:
        _rank_cli(sub, "q", 1, max_chars=None, as_json=False, stats=False)
        assert post.call_args.args[0] == sub
    print("descubrimiento y excepción de rank: OK")
PY
