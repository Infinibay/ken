"""`ken uninstall` — remove ken hooks from a project, optionally drop the DB.

We only touch what we put there: ken's hook entries in
`.claude/settings.json`, and (unless `--keep-db`) the `.ken/` directory.
The user's own hooks / settings stay untouched.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ken import _paths
from ken.hooks_template import remove_ken_hooks, write_settings
from ken.install import CLAUDE_SETTINGS


def uninstall(project_path: Path, *, keep_db: bool) -> int:
    root = project_path.resolve()
    if not _paths.meta_path(root).is_file():
        print(f"no .ken project at {root}", file=sys.stderr)
        return 1

    settings_p = root / CLAUDE_SETTINGS
    if settings_p.is_file():
        try:
            existing = json.loads(settings_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        cleaned = remove_ken_hooks(existing)
        if cleaned:
            write_settings(settings_p, cleaned)
            print(f"[hooks] removed ken entries from {CLAUDE_SETTINGS}")
        else:
            settings_p.unlink()
            print(f"[hooks] {CLAUDE_SETTINGS} now empty — deleted")

    if keep_db:
        print(f"[db] keeping .ken/ ({_paths.db_path(root)})")
    else:
        ken_dir = _paths.ken_dir(root)
        if ken_dir.is_dir():
            shutil.rmtree(ken_dir)
            print(f"[db] removed {ken_dir}")

    print(f"✓ ken uninstalled from {root}")
    return 0
