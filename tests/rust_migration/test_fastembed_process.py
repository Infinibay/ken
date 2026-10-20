"""Protocol framing is independent from numerical acceptance."""
import pytest
from tools.rust_migration.fastembed_process import decode_frames


def test_frames_reject_ambiguous_nonfinite_and_oversized_json():
    assert decode_frames('{"id":"one"}\n{"id":"two"}\n')==[{'id':'one'},{'id':'two'}]
    for raw in ['{"id":"a","id":"b"}\n','{"x":NaN}\n','[]\n','\n','{"x":1}\ntrash\n',' '* (16*1024*1024+1)]:
        with pytest.raises(ValueError):decode_frames(raw)


@pytest.fixture(scope='module')
def protocol_child(tmp_path_factory):
    """A native misbehaving executable exercises the real controller lifecycle."""
    import subprocess
    root=tmp_path_factory.mktemp('native-protocol-child');source=root/'child.c';binary=root/'child'
    source.write_text(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv) {
    const char *mode=argv[argc-1];
    char request[128]; if (!fgets(request,sizeof(request),stdin)) return 2;
    fputs("{\"id\":\"ready\"}\n",stdout);fflush(stdout);
    if (!strcmp(mode,"no-read")) { usleep(1500000); return 0; }
    if (!fgets(request,sizeof(request),stdin)) return 2;
    if (!strcmp(mode,"partial")) { printf("{\"pid\":%ld",(long)getpid()); fflush(stdout); usleep(1500000); }
    else if (!strcmp(mode,"oversized")) { for(int i=0;i<131072;i++) putchar('x'); fflush(stdout); usleep(1500000); }
    else { fputs("{\"id\":\"one\"}\n",stdout);fflush(stdout);while(getchar()!=EOF) {} }
    return 0;
}
''')
    subprocess.run(['cc',str(source),'-o',str(binary)],check=True,capture_output=True)
    return binary


@pytest.mark.parametrize('mode',['partial','no-read'])
def test_deadline_bounds_partial_response_and_blocked_request(tmp_path,protocol_child,monkeypatch,mode):
    import os,time
    from tools.rust_migration import fastembed_process as module
    monkeypatch.setattr(module,'MODEL_TIMEOUT',5)
    registry=tmp_path/'registry';registry.write_text('{}');core=tmp_path/'core';core.write_bytes(b'core')
    process=module.NativeProbeProcess(protocol_child,registry,tmp_path,core,mode,tmp_path/'out')
    with pytest.raises(TimeoutError,match='deadline'):
        with process:
            assert process.send({'id':'ready'})=={'id':'ready'}
            started=time.monotonic();process.deadline=started+0.15
            process.send({'id':'one','data':'x'*(1024*1024) if mode=='no-read' else ''})
    assert time.monotonic()-started<1.1
    assert process.process.poll() is not None
    assert not process.root.exists()
    with pytest.raises(ProcessLookupError):os.kill(process.process.pid,0)
    if mode=='partial':
        import re
        pid=int(re.search(rb'"pid":(\d+)',process.stdout.read_bytes())[1])
        with pytest.raises(ProcessLookupError):os.kill(pid,0)


def test_oversized_response_reaps_child_immediately(tmp_path,protocol_child,monkeypatch):
    import time
    from tools.rust_migration import fastembed_process as module
    monkeypatch.setattr(module,'RAW_LIMIT',65536)
    registry=tmp_path/'registry';registry.write_text('{}');core=tmp_path/'core';core.write_bytes(b'core')
    process=module.NativeProbeProcess(protocol_child,registry,tmp_path,core,'oversized',tmp_path/'out')
    with pytest.raises(ValueError,match='oversized'):
        with process:
            process.send({'id':'ready'});started=time.monotonic();process.send({'id':'one'})
    assert time.monotonic()-started<1.1
    assert process.process.poll() is not None and not process.root.exists()


def test_normal_exchange_and_eof_preserve_exact_frames(tmp_path,protocol_child):
    from tools.rust_migration.fastembed_process import NativeProbeProcess
    registry=tmp_path/'registry';registry.write_text('{}');core=tmp_path/'core';core.write_bytes(b'core')
    with NativeProbeProcess(protocol_child,registry,tmp_path,core,'valid',tmp_path/'out')as process:
        assert process.send({'id':'ready'})=={'id':'ready'}
        assert process.send({'id':'one'})=={'id':'one'}
    assert process.stdout.read_bytes()==b'{"id":"ready"}\n{"id":"one"}\n'
    assert process.report['native_exit']==0


def test_parent_suite_deadline_bounds_and_reaps_the_native_execution(tmp_path,protocol_child,monkeypatch):
    import os,re,time
    from tools.rust_migration import fastembed_process as module
    monkeypatch.setattr(module,'MODEL_TIMEOUT',5)
    monkeypatch.setenv('KEN_FASTEMBED_VALIDATION_DEADLINE',str(time.monotonic()+0.5))
    registry=tmp_path/'registry';registry.write_text('{}');core=tmp_path/'core';core.write_bytes(b'core')
    process=module.NativeProbeProcess(protocol_child,registry,tmp_path,core,'partial',tmp_path/'out')
    started=time.monotonic()
    with pytest.raises(TimeoutError,match='deadline'):
        with process:
            process.send({'id':'ready'});process.send({'id':'one'})
    assert time.monotonic()-started<1.1
    pid=int(re.search(rb'"pid":(\d+)',process.stdout.read_bytes())[1])
    with pytest.raises(ProcessLookupError):os.kill(pid,0)
    assert process.process.poll()is not None and not process.root.exists()
