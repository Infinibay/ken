"""A real native public factory consumer runs outside checkout with audited execs."""
import os
from pathlib import Path
from tools.rust_migration.integration_process import run_factory


def test_actual_cold_public_factory_uses_no_source_optional_runtime_or_python(tmp_path):
    repo=Path(__file__).resolve().parents[2]
    target=Path(os.environ.get('CARGO_TARGET_DIR',repo/'.ken/rust-migration/m2-fastembed/target-final-ci'))
    probe=Path(os.environ.get('KEN_INTEGRATION_PROBE',target/'release/examples/model_integration_probe'))
    request={'format':'ken-model-factory-request/1','policy':'offline',
        'cache_root':str(tmp_path/'cache'),'private_parent':str(tmp_path/'private'),
        'bundled_npz':str(tmp_path/'absent.npz'),'source_overrides':{},
        'device':{'kind':'cpu'},'fastembed_device':'cpu',
        'selection':{'kind':'legacy_encoder','name':'ken/static-qwen3-r512-v2'},
        'cases':[{'id':'cold-empty','call':{'operation':'passages','texts':[]}}]}
    result=run_factory(probe,request,tmp_path/'observed',deadline_s=20)
    assert result['actual']['selection']['family']=='static_table'
    assert result['actual']['initial_prepared'] is False
    assert result['actual']['after_empty_prepared'] is False
    assert result['actual']['rows'][0]['result']=={'vectors':[]}
    assert result['actual']['runtime']=={'onnx':None,'torch':None,'mlx':None}
    assert result['receipt']['outside_checkout'] is True
    assert result['receipt']['owned_after_exit']==[]
    assert not (tmp_path/'absent.npz').exists()
