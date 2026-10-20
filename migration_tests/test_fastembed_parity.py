"""Real native protocol; the separate parity gate covers all30models/300cases."""
import json,os,shutil,subprocess
from pathlib import Path
from tools.rust_migration.preparation import PreparedNativeFastEmbed
from tools.rust_migration.fastembed_compare import _oracle_inputs,compare_model,native_producer
from tools.rust_migration.fastembed_process import NativeProbeProcess
from tools.rust_migration.fastembed_reference import native_request
from tools.rust_migration.fastembed_sources import source_lease


def prepared():
    values=[]
    for name in ['KEN_FASTEMBED_PROBE','KEN_FASTEMBED_SOURCES','KEN_FASTEMBED_REGISTRY']:
        value=os.environ.get(name,'');path=Path(value)
        assert value and path.is_absolute()and path.exists(),f'explicit prepared {name} required'
        values.append(path)
    result=PreparedNativeFastEmbed(*values,acquire=os.environ.get('KEN_FASTEMBED_ACQUIRE')=='1');result.environment();return result


def library():
    path=Path(os.environ.get('KEN_ORT_LIBRARY',''))
    assert path.is_absolute()and path.is_file(),'explicit prepared KEN_ORT_LIBRARY required'
    return path


def test_native_fastembed_real_text_history_outside_checkout(reference,tmp_path):
    value=prepared();catalogue,cases,originals,core=_oracle_inputs(reference,value)
    name='BAAI/bge-small-en-v1.5';definition=next(m for m in catalogue['models']if m['name']==name)
    wanted=next(r for r in originals if r['model']==name);cases=[c for c in cases if c['model']==name]
    requests=[{'id':name+':control-cold','operation':'status'},*[native_request(c)for c in cases],{'id':name+':control-final','operation':'status'}]
    with source_lease(value,definition,copies=2)as leased:
        with NativeProbeProcess(leased.probe,leased.registry,leased.sources,library(),name,tmp_path/'role')as process:
            frames=[process.send(request)for request in requests]
    assert compare_model(definition,cases,wanted,frames,native_producer(),core)==[]
    assert process.report['native_children']==[]and process.report['outside_checkout']
    assert process.report['owned_after_exit']==[]


def test_native_fastembed_cold_empty_and_invalid_protocol_do_not_load_models(tmp_path):
    value=prepared();model='Qdrant/clip-ViT-B-32-text';work=tmp_path/'work';work.mkdir()
    command=[str(value.probe),'--registry',str(value.registry),'--sources',str(tmp_path/'missing-sources'),'--work',str(work),'--runtime-library',str(tmp_path/'missing-core'),'--model',model]
    requests=[{'id':'cold','operation':'status'},{'id':'empty','operation':'embed','side':'query','texts':[]}]
    child=subprocess.run(command,input=''.join(json.dumps(r)+'\n'for r in requests),text=True,capture_output=True,timeout=30)
    assert child.returncode==0,child.stderr
    frames=[json.loads(line)for line in child.stdout.splitlines()]
    assert all(r['state']=={'model_loaded':False,'device':'unknown','dim':512}for r in frames)
    assert frames[1]['result']=={'shape':[0,512],'batches':[],'vectors_f32le_hex':''}
    assert list(work.iterdir())==[]
    for request in [{},{'id':'bad','operation':'status','expected':{}},{'id':'bad','operation':'prepare','source_setup':{}},{'id':'bad','operation':'embed','side':'query','texts':[False]}]:
        child=subprocess.run(command,input=json.dumps(request)+'\n',text=True,capture_output=True,timeout=30)
        assert child.returncode==1 and child.stderr and not child.stdout
        assert list(work.iterdir())==[]
