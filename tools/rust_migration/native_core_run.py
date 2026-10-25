"""Execute one immutable host packet using the prepared CPU cores."""
from pathlib import Path
import json,os,platform,sys
from .command_gates import run_command_gates,run_lint_gates
from .native_json import load
from .native_core_packet import capture_packet,snapshot_packet
from .native_core_gates import ROOT_COMMANDS,TORCH_COMMANDS,LINT_COMMANDS,TORCH_LINT,test_files

def run_host(repo:Path,sdk:Path,out:Path,torch_target:Path):
    ready=load(sdk/'PREPARATION.json');gates=out/'gates';gates.mkdir(parents=True)
    original=os.environ.copy()
    try:
        os.environ.update(KEN_ORT_LIBRARY=ready['prepared']['onnx_library'],LIBTORCH=ready['prepared']['torch_core'],LIBTORCH_CXX11_ABI='1',CARGO_TARGET_DIR=str(repo/'target'))
        os.environ.pop('LIBTORCH_USE_PYTORCH',None);os.environ.pop('LIBTORCH_BYPASS_VERSION_CHECK',None)
        loader='DYLD_LIBRARY_PATH'if platform.system()=='Darwin'else'LD_LIBRARY_PATH';os.environ[loader]=str(Path(ready['prepared']['torch_core'])/'lib')
        run_command_gates(gates,ROOT_COMMANDS,record_name='ROOT.json')
        os.environ['CARGO_TARGET_DIR']=str(torch_target)
        run_command_gates(gates,TORCH_COMMANDS,record_name='TORCH.json')
        records=load(gates/'ROOT.json');records.update(load(gates/'TORCH.json'));(gates/'RUST.json').write_text(json.dumps(records,indent=2)+'\n')
        suffix='dylib'if platform.system()=='Darwin'else'so';module=torch_target/f'debug/libken_torch_backend.{suffix}'
        os.environ['CARGO_TARGET_DIR']=str(repo/'target')
        capture_packet(repo,module,sdk,out)
        os.environ.update(KEN_NATIVE_CORE_PACKET=str(out),KEN_INTEGRATION_PROBE=str(repo/'target/debug/examples/model_integration_probe'))
        command=[sys.executable,'-m','pytest','-o','addopts=','-q',*test_files(repo)]
        run_command_gates(gates,{'python-list':[*command,'--collect-only'],'python-tests':[*command,'--junitxml='+str(gates/'python.xml')]},record_name='PYTHON.json')
        run_lint_gates(gates,LINT_COMMANDS)
        os.environ['CARGO_TARGET_DIR']=str(torch_target);(gates/'torch-lint').mkdir()
        run_lint_gates(gates/'torch-lint',TORCH_LINT)
        snapshot_packet(repo,out)
    finally:
        os.environ.clear();os.environ.update(original)
