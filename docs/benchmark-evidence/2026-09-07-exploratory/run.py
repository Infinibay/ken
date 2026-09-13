"""One sequential isolated cell; invoke A no-ken, A ken, A infinidev, B infinidev, B ken, B no-ken."""
import os,sys,json,subprocess,tempfile,pathlib,time,shutil,signal,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[3];OUT=pathlib.Path(__file__).resolve().parent
condition,task=sys.argv[1:3];suffix=sys.argv[3] if len(sys.argv)>3 else '';assert condition in ('codex-no-ken','codex-ken','infinidev') and task in ('A','B')
assert not suffix or suffix in ('no-timeout','autoapprove')
dest=OUT/(task+'--'+condition+('--'+suffix if suffix else ''));dest.mkdir()
work=pathlib.Path(tempfile.mkdtemp(prefix='ken-explore-'))
env={k:v for k,v in os.environ.items() if not k.startswith(('INFINIDEV_','KEN_','OPENAI_','ANTHROPIC_'))}
files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0');manifest={}
for f in files:
 if not f or any(p in {'.infinidev','.git','.env','.ken','.codex','.claude'} for p in pathlib.Path(f).parts) or f in ('.mcp.json','opencode.json') or f.startswith('docs/benchmark-evidence/') or f=='docs/codex-ken-benchmark-2026-09-07.md':continue
 src=ROOT/f
 if src.is_file():
  (work/f).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,work/f);manifest[f]=hashlib.sha256(src.read_bytes()).hexdigest()
# Neutralize stale instructions only in isolated benchmark copies; record exact effective schema.
for p in work.rglob('AGENTS.md'):p.unlink()
if condition!='codex-no-ken':
 catalog=json.loads((OUT.parent/'2026-09-07-mcp-index-diagnosis/mcp-catalog.json').read_text())['tools']
 guidance='Use Ken to locate relevant code before reading, where available. Follow the installed schemas below (query, not task). Read actual source and verify conclusions; fall back to shell if necessary.\n'
 guidance+='\n'.join(t['name']+' '+json.dumps(t['input_schema']) for t in catalog)
 (work/'AGENTS.md').write_text(guidance);(dest/'AGENTS.effective.md').write_text(guidance)
(dest/'snapshot.sha256.json').write_text(json.dumps(manifest,indent=2))
subprocess.run(['git','init','-q',str(work)],check=True);subprocess.run(['git','add','.'],cwd=work,check=True)
def run(cmd,label,limit):
 start=time.monotonic()
 with (dest/(label+'.stdout')).open('w') as o,(dest/(label+'.stderr')).open('w') as e:
  p=subprocess.Popen(cmd,cwd=work,env=env,stdout=o,stderr=e,start_new_session=True);expired=False
  try:code=p.wait(timeout=limit)
  except subprocess.TimeoutExpired:
   expired=True;os.killpg(p.pid,signal.SIGTERM)
   try:code=p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);code=p.wait()
 data={'command':cmd,'cwd':str(work),'exit_code':code,'elapsed_seconds':round(time.monotonic()-start,3),'timeout':expired,'timeout_seconds':limit}
 (dest/(label+'.metadata.json')).write_text(json.dumps(data,indent=2));print(json.dumps(data),flush=True)
 return code
if condition!='codex-no-ken':
 if run(['ken','install','--no-wire','--embed',str(work)],'setup',90):raise SystemExit('Ken setup failed; no model launched')
prompt=json.loads((OUT/'prompts.json').read_text())[task]+' Trabaja solo en este repositorio. No hagas commits. Entrega tu respuesta final en español.'
if condition=='infinidev' and suffix=='autoapprove':
 settings={k:'auto_approve' for k in ('EXECUTE_COMMANDS_PERMISSION','FILE_OPERATIONS_PERMISSION','TOOL_EFFECTS_PERMISSION','MCP_PERMISSION')}
 (work/'.infinidev').mkdir(exist_ok=True)
 (work/'.infinidev'/'settings.json').write_text(json.dumps(settings,indent=2))
 (dest/'settings.effective.json').write_text(json.dumps(settings,indent=2))
 check="import json; from infinidev.config.settings import settings; keys="+repr(list(settings))+"; print(json.dumps({k:getattr(settings,k) for k in keys})); assert all(getattr(settings,k)=='auto_approve' for k in keys)"
 if run(['/Users/andres/.local/share/uv/tools/infinidev/bin/python3','-c',check],'permissions-check',None):raise SystemExit('Local permissions check failed; no model launched')
if condition=='infinidev':cmd=['infinidev','--no-tui','--provider','openai_subscription','--model','gpt-6-astra','-p',prompt]
else:
 cmd=['codex','exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check','--sandbox','workspace-write','--model','gpt-6-astra','--json','-C',str(work)]
 if condition=='codex-ken':
  names=[t['name'] for t in catalog]
  cmd+=['-c','mcp_servers.ken.command="ken"','-c','mcp_servers.ken.args='+json.dumps(['mcp',str(work)]),'-c','mcp_servers.ken.default_tools_approval_mode="approve"','-c','mcp_servers.ken.enabled_tools='+json.dumps(names)]
 cmd+=[prompt]
run(cmd,'run',None)
(dest/'changes.diff').write_bytes(subprocess.check_output(['git','diff'],cwd=work));(dest/'status.txt').write_bytes(subprocess.check_output(['git','status','--short'],cwd=work))
db=work/'.infinidev'/'infinidev.db'
if db.exists():
 import sqlite3
 with sqlite3.connect(db) as s,sqlite3.connect(dest/'session.db') as t:s.backup(t)
