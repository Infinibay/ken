import os,sys,json,subprocess,tempfile,pathlib,time,shutil,signal
ROOT=pathlib.Path(__file__).resolve().parents[3]; OUT=pathlib.Path(__file__).resolve().parent
condition=sys.argv[1]; task=sys.argv[2]; dest=OUT/(task+'--'+condition);dest.mkdir()
work=pathlib.Path(tempfile.mkdtemp(prefix='ken-bench-'))
env={k:v for k,v in os.environ.items() if not k.startswith(('INFINIDEV_','KEN_','OPENAI_','ANTHROPIC_'))}
files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
for f in files:
 if not f or any(p in {'.infinidev','.git','.env','.ken','.codex','.claude'} for p in pathlib.Path(f).parts) or f in ('.mcp.json','opencode.json'):continue
 src=ROOT/f
 if src.is_file(): (work/f).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,work/f)
if condition=='codex-no-ken':
 for p in work.rglob('AGENTS.md'):p.unlink()
subprocess.run(['git','init','-q',str(work)],check=True);subprocess.run(['git','add','.'],cwd=work,check=True)
prompts={'socket':'Add socket_path(project_root: Path) -> Path in src/ken/_paths.py alongside canonical path helpers, using SOCKET_FILENAME. Add focused tests for absolute and relative roots without creating directories or sockets. Preserve existing behavior.', 'must-exist':'Extend resolve_project_path in src/ken/_paths.py with keyword-only must_exist: bool = False. Keep existing behavior when false. When true require resolved in-project target to exist, otherwise raise FileNotFoundError. Reject escapes with ValueError before checking existence. Add focused tests for existing files/directories, missing paths with default and true, and missing escaping paths with true.'}
prompt=prompts[task]+' Work only inside this repository. Run focused tests. Do not commit. Finish with a brief summary.'
def run(cmd,label,timeout=90,customenv=None):
 start=time.monotonic()
 with (dest/(label+'.stdout')).open('w') as out,(dest/(label+'.stderr')).open('w') as err:
  p=subprocess.Popen(cmd,cwd=work,env=customenv or env,stdout=out,stderr=err,start_new_session=True);expired=False
  try:code=p.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   expired=True;os.killpg(p.pid,signal.SIGTERM)
   try:code=p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);code=p.wait()
 data={'command':cmd,'cwd':str(work),'exit_code':code,'elapsed_seconds':round(time.monotonic()-start,3),'timeout':expired,'timeout_seconds':timeout}
 (dest/(label+'.metadata.json')).write_text(json.dumps(data,indent=2));print(json.dumps(data),flush=True)
if condition=='infinidev':cmd=['infinidev','--no-tui','--provider','openai_subscription','--model','gpt-6-astra','-p',prompt]
else:
 cmd=['codex','exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check','--sandbox','workspace-write','--model','gpt-6-astra','--json','-C',str(work)]
 if condition=='codex-ken':
  run(['ken','install','--no-wire',str(work)],'setup',90)
  cmd+=['-c','mcp_servers.ken.command="ken"','-c','mcp_servers.ken.args='+json.dumps(['mcp',str(work)])]
 cmd+=[prompt]
run(cmd,'run')
(dest/'changes.diff').write_bytes(subprocess.check_output(['git','diff'],cwd=work));(dest/'status.txt').write_bytes(subprocess.check_output(['git','status','--short'],cwd=work))
checks={'socket':"from pathlib import Path\nfrom ken._paths import socket_path\nfor r in (Path('/tmp/benchmark-nonexistent'),Path('relative')): assert socket_path(r)==r/'.ken'/'daemon.sock'",'must-exist':"import pathlib,tempfile,inspect\nfrom ken._paths import resolve_project_path as f\nassert inspect.signature(f).parameters['must_exist'].kind==inspect.Parameter.KEYWORD_ONLY\nwith tempfile.TemporaryDirectory() as d:\n r=pathlib.Path(d);(r/'f').touch();(r/'dir').mkdir()\n for x in ('f','dir'): assert f(r,x,must_exist=True)==r/x\n assert f(r,'missing')==r/'missing'\n try:f(r,'missing',must_exist=True)\n except FileNotFoundError:pass\n else:raise AssertionError('missing accepted')\n try:f(r,'../escape-nonexistent',must_exist=True)\n except ValueError:pass\n else:raise AssertionError('escape accepted')"}
e=env.copy();e['PYTHONPATH']=str(work/'src');run([sys.executable,'-c',checks[task]],'verify',15,e)
db=work/'.infinidev'/'infinidev.db'
if db.exists():
 import sqlite3
 with sqlite3.connect(db) as s,sqlite3.connect(dest/'session.db') as t:s.backup(t)
