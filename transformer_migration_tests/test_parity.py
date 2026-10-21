"""Replay the actual current-candidate native processes as a separate gate."""
import os
from pathlib import Path
from tools.rust_migration.transformer_validate import replay_transformer_profiles


def test_current_complete_native_corpus_preserves_all_original_public_calls():
 value=os.environ.get('KEN_TRANSFORMER_PLATFORM_EXECUTION')
 assert value, 'explicit prepared transformer execution bundle required'
 root=Path(value);assert root.is_absolute()
 report=replay_transformer_profiles(root,Path(__file__).resolve().parents[1])
 assert report['passed'],report['errors']
 assert report['profiles']==(24 if os.uname().sysname=='Darwin' else 9)
