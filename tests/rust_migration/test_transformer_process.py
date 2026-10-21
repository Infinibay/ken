"""Real native process failures are bounded and reaped."""
import os,subprocess,time
from pathlib import Path
import pytest
from tools.rust_migration.transformer_process import run_transformer

@pytest.fixture(scope='module')
def child(tmp_path_factory):
 root=tmp_path_factory.mktemp('transformer-child');source=root/'main.c';binary=root/'child'
 source.write_text(r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv){
 FILE *f=fopen(argv[1],"r"); char mode[128];fgets(mode,128,f);fclose(f);
 if(strstr(mode,"partial")){printf("{\"pid\":%ld",(long)getpid());fflush(stdout);sleep(10);}
 else if(strstr(mode,"sleep")){sleep(10);}
 else if(strstr(mode,"stdin")){char c;int n=read(0,&c,1);printf("{\"eof\":%s}\n",n==0?"true":"false");}
 else if(strstr(mode,"extra")){puts("{}\n{}");}
 else {puts("{\"passed\":true}");}
 return 0;}
''')
 subprocess.run(['cc',str(source),'-o',str(binary)],check=True,capture_output=True);return binary

@pytest.mark.parametrize('mode',['partial','sleep'])
def test_deadline_reaps_partial_frame_and_silent_process(child,tmp_path,mode):
 start=time.monotonic()
 with pytest.raises(TimeoutError,match='deadline'):
  run_transformer(child,{'mode':mode},tmp_path/'out',deadline_s=.15,audit=False)
 assert time.monotonic()-start<1.2
 assert not list((tmp_path/'out').glob('work-*'))

def test_stdin_is_eof_and_one_complete_frame_required(child,tmp_path):
 report=run_transformer(child,{'mode':'stdin'},tmp_path/'good',deadline_s=2,audit=False)
 assert report['actual']=={'eof':True} and report['receipt']['native_children']==[]
 with pytest.raises(ValueError,match='one JSON'):
  run_transformer(child,{'mode':'extra'},tmp_path/'bad',deadline_s=2,audit=False)

def test_explicit_regular_native_binary_and_finite_deadline_required(tmp_path,child):
 for deadline in [0,-1,float('nan'),float('inf')]:
  with pytest.raises(ValueError):run_transformer(child,{},tmp_path/str(deadline),deadline_s=deadline,audit=False)
 script=tmp_path/'python';script.write_text('#!/usr/bin/python\n');script.chmod(0o755)
 with pytest.raises(ValueError,match='native executable'):run_transformer(script,{},tmp_path/'script',deadline_s=1,audit=False)
