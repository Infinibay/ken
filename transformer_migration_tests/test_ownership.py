"""Actual native lifecycle regressions; no synthesized vectors or Python fallback."""
import os,subprocess
from pathlib import Path


def test_real_native_public_owners_survive_source_removal_errors_and_concurrency(tmp_path):
 required=['KEN_TORCH_CORE','KEN_TORCH_MODULE','KEN_TORCH_PREPARATION','CARGO_TARGET_DIR']
 if os.uname().sysname=='Darwin':required+=['KEN_MLX_CORE','KEN_MLX_MODULE']
 assert all(os.environ.get(k) for k in required), 'complete prepared native core paths required'
 assert all(Path(os.environ[k]).is_absolute() for k in required)
 root=Path(__file__).resolve().parents[1]
 command=['cargo','test','--offline','--locked','-p','ken-models','--lib','--','--test-threads=1']
 log=tmp_path/'native-owners.log'
 with log.open('w') as output:
  result=subprocess.run(command,cwd=root,env=os.environ.copy(),stdout=output,stderr=subprocess.STDOUT,timeout=600)
 value=log.read_text()
 assert result.returncode==0,value[-6000:]
 for name in ['actual_cpu_loads_even_for_empty_then_scores_raw_batches_and_keeps_its_owned_source','concurrent_first_use_serializes_one_owned_judge','cpu_late_failure_and_nonfinite_return_no_partial_scores_without_retry','actual_concurrent_first_use_shares_one_session_and_source_copy']:
  assert any(name in line and line.endswith(' ... ok') for line in value.splitlines()),name
 assert '0 failed' in value and '0 ignored' in value
 artifact=os.environ.get('KEN_TRANSFORMER_OWNERSHIP_LOG')
 if artifact:
  destination=Path(artifact);assert destination.is_absolute();destination.write_bytes(log.read_bytes())
