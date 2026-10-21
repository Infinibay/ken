"""SDK preparation publishes only a fully verified native library closure."""
from pathlib import Path
import hashlib
import pytest
from tools.rust_migration.transformer_prepare import copy_torch_sdk


def package(tmp_path):
 root=tmp_path/'torch';(root/'lib').mkdir(parents=True);headers=root/'include/torch/csrc/api/include/torch';headers.mkdir(parents=True);(headers/'version.h').write_text('#define TORCH_VERSION "2.9.0"\n');(root/'lib/libtorch.so').write_bytes(b'core')
 return root,{'core_version':'2.9.0','libraries':{'lib/libtorch.so':{'bytes':4,'sha256':hashlib.sha256(b'core').hexdigest()}}}

def test_verified_sdk_is_distinct_and_has_no_python_library(tmp_path):
 source,core=package(tmp_path);(source/'lib/libtorch_python.so').write_bytes(b'Python')
 target=tmp_path/'sdk';copy_torch_sdk(source,target,core)
 assert (target/'lib/libtorch.so').read_bytes()==b'core' and not (target/'lib/libtorch_python.so').exists()
 assert (source/'lib/libtorch_python.so').read_bytes()==b'Python'
 with pytest.raises(ValueError):copy_torch_sdk(source,target,core)

def test_wrong_core_never_publishes_a_partial_sdk(tmp_path):
 source,core=package(tmp_path);(source/'lib/libtorch.so').write_bytes(b'bad!');target=tmp_path/'sdk'
 with pytest.raises(ValueError,match='library'):copy_torch_sdk(source,target,core)
 assert not target.exists() and (source/'lib/libtorch.so').read_bytes()==b'bad!'
