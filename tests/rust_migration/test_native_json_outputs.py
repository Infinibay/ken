"""Actual native processes distinguish authorized outputs from immutable inputs."""
import hashlib,json,shutil,subprocess
from pathlib import Path
import pytest
from tools.rust_migration.native_json import NativeJsonCapture,verify_native_json,identity

ROOT=Path(__file__).resolve().parents[2]
PREFIX='ken-generated-test-'
MADE={'bytes':4,'sha256':hashlib.sha256(b'made').hexdigest()}
OUTPUTS={'prepared/out':MADE}

@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    root=tmp_path_factory.mktemp('native-writer');source=root/'writer.c';binary=root/'writer'
    source.write_text(r'''
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static void put(const char *path,const char *value){FILE*f=fopen(path,"wb");if(!f)return;fwrite(value,1,strlen(value),f);fclose(f);}
int main(void){char input[4096]={0};fread(input,1,sizeof(input)-1,stdin);
if(!strstr(input,"readonly")){mkdir("prepared",0700);
if(strstr(input,"symlink"))symlink("../source","prepared/out");
else if(!strstr(input,"missing"))put("prepared/out",strstr(input,"damaged")?"bad":"made");
if(strstr(input,"extra"))put("unexpected","extra");
if(strstr(input,"mutate"))put("source","changed");}
puts("{\"ok\":true}");return 0;}
''')
    subprocess.run([shutil.which('cc'),str(source),'-o',str(binary)],check=True)
    return binary

def execute(probe,out,*,mode='write',generated=OUTPUTS):
    kwargs={}if generated is None else{'generated_files':generated}
    with NativeJsonCapture(probe,out,repo=ROOT,prefix=PREFIX,**kwargs)as capture:
        (capture.root/'source').write_bytes(b'seed')
        capture.run({'mode':mode})
    return json.loads((out/'execution.json').read_bytes())

def test_default_readonly_protocol_stays_v1(probe,tmp_path):
    record=execute(probe,tmp_path/'capture',mode='readonly',generated=None)
    assert record['format']=='ken-native-json-execution/1'and record['timeout_s']==60
    assert 'generated_files'not in record
    assert not verify_native_json(tmp_path/'capture',PREFIX)

def test_default_still_rejects_native_writes(probe,tmp_path):
    with pytest.raises(ValueError,match='owned files'):execute(probe,tmp_path/'capture',generated=None)

def test_exact_generated_files_require_explicit_verifier_contract(probe,tmp_path):
    out=tmp_path/'capture';record=execute(probe,out)
    assert record['format']=='ken-native-json-execution/2'and record['timeout_s']==600
    assert record['generated_files']==OUTPUTS
    assert record['owned_after']==record['owned_before']|OUTPUTS
    assert not verify_native_json(out,PREFIX,generated_files=OUTPUTS)
    assert verify_native_json(out,PREFIX)
    assert verify_native_json(out,PREFIX,generated_files={'prepared/foreign':MADE})

@pytest.mark.parametrize('mode',['missing','extra','damaged','mutate','symlink'])
def test_generated_files_do_not_authorize_other_effects(probe,tmp_path,mode):
    with pytest.raises(ValueError):execute(probe,tmp_path/'capture',mode=mode)

@pytest.mark.parametrize('mapping',[{}, {'../out':MADE},{'/out':MADE},{'a/../out':MADE},{'a//out':MADE},{'native-probe':MADE},{'home/out':MADE},{'prepared/out':{'bytes':True,'sha256':'a'*64}},{'prepared/out':{'bytes':4,'sha256':'invalid'}}])
def test_invalid_output_contract_rejects_before_execution(probe,tmp_path,mapping):
    with pytest.raises(ValueError):NativeJsonCapture(probe,tmp_path/'capture',repo=ROOT,prefix=PREFIX,generated_files=mapping)
    assert not(tmp_path/'capture').exists()

def test_generated_files_cannot_overlap_existing_inputs(probe,tmp_path):
    with NativeJsonCapture(probe,tmp_path/'capture',repo=ROOT,prefix=PREFIX,generated_files=OUTPUTS)as capture:
        path=capture.root/'prepared/out';path.parent.mkdir();path.write_bytes(b'made')
        with pytest.raises(ValueError):capture.run({'mode':'readonly'})
        assert path.read_bytes()==b'made'

@pytest.mark.parametrize('field',['timeout','generated','after','before'])
def test_resealed_generated_execution_rejects(probe,tmp_path,field):
    out=tmp_path/'capture';record=execute(probe,out)
    if field=='timeout':record['timeout_s']=60
    elif field=='generated':record['generated_files']={}
    elif field=='after':record['owned_after']['foreign']=MADE
    else:record['owned_before']['prepared/out']=MADE
    (out/'execution.json').write_text(json.dumps(record))
    assert verify_native_json(out,PREFIX,generated_files=OUTPUTS)
