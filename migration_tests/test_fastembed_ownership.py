"""Native failed-copy repair, source removal and RAII cleanup for five real families."""
import os
from pathlib import Path
from tools.rust_migration.preparation import PreparedNativeFastEmbed
from tools.rust_migration.fastembed_ownership import verify_fastembed_ownership,MODELS


def test_live_native_fastembed_keeps_own_files_after_external_source_removal(reference,tmp_path):
    paths=[]
    for name in ['KEN_FASTEMBED_PROBE','KEN_FASTEMBED_SOURCES','KEN_FASTEMBED_REGISTRY','KEN_ORT_LIBRARY']:
        value=os.environ.get(name,'');path=Path(value)
        assert value and path.is_absolute()and path.exists(),f'explicit prepared {name} required'
        paths.append(path)
    result=verify_fastembed_ownership(reference,PreparedNativeFastEmbed(*paths[:3]),tmp_path/'ownership',library=paths[3])
    assert result['passed'],result['errors']
    assert [m['model']for m in result['models']]==MODELS
    assert result['FastEmbed_accepted']is False and result['M2_accepted']is False
