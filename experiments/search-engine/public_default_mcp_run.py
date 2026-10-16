"""Exercise default search through real MCP; no reference reads or quality scoring."""
import argparse,asyncio,hashlib,json,os,platform,resource,subprocess,sys,time
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.public import render

def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def unit(result):
 kind=result['piece_kind'];entity=result['entity']
 return {'target_kind':kind,'path':result['path'],'entity':entity if kind in {'class','symbol'} else None,'module_name':result.get('module_name') if kind=='module' else None}

def main():
 p=argparse.ArgumentParser()
 for arg in ('lock','output'):p.add_argument('--'+arg,type=Path,required=True)
 p.add_argument('--repo');args=p.parse_args();lock=json.loads(args.lock.read_text());engine=Path(lock['engine_root'])
 if verify_frozen_source(engine)!=lock['source_receipt'] or sha(__file__)!=lock['producer_sha256']:raise ValueError('producer/engine changed')
 for path,digest in lock['input_pins'].items():
  if sha(path)!=digest:raise ValueError('public input changed')
 cases=[json.loads(line) for line in Path(lock['public_cases']).read_text().splitlines()]
 if len(cases)!=lock['queries'] or len({c['id'] for c in cases})!=len(cases) or any('acceptable_units' in c for c in cases):raise ValueError('invalid public cases')
 args.output.mkdir(parents=True,exist_ok=False)
 if args.repo is None:
  registration={'scope':lock['scope'],'lock_sha256':sha(args.lock),'variant':'production','variant_policy':lock['variant_policy'],'status':'registered before public calls','closed':{}}
  (args.output/'registration.json').write_text(json.dumps(registration,indent=2))
  for repo in sorted({c['repo_id'] for c in cases}):
   with (args.output/(repo+'.log')).open('w') as log:
    subprocess.run([sys.executable,__file__,'--lock',str(args.lock),'--output',str(args.output/repo),'--repo',repo],stdout=log,stderr=subprocess.STDOUT,check=True,env=os.environ)
   registration['closed'][repo]={name:sha(args.output/repo/name) for name in ('answers.jsonl','performance.json')}
   print(json.dumps({'repo':repo,'closed':True,'public_transport':'MCP stdio','default_engine':True}),flush=True)
  if verify_frozen_source(engine)!=lock['source_receipt']:raise ValueError('engine changed during public capture')
  registration['status']=lock['closed_status'];(args.output/'registration.json').write_text(json.dumps(registration,indent=2));return
 repo=args.repo;root=Path(lock['roots'][repo]);cases=[c for c in cases if c['repo_id']==repo]
 telemetry=args.output/'server-telemetry.json';timings=[];answers=[]
 async def run():
  params=StdioServerParameters(command=sys.executable,args=[lock['server_launcher'],str(root),str(telemetry)],env=lock['server_environment']|{'PYTHONPATH':str(engine/'src'),'PYTHONDONTWRITEBYTECODE':'1'})
  with (args.output/'mcp.log').open('w') as log:
   async with stdio_client(params,errlog=log) as (read,write):
    async with ClientSession(read,write) as session:
     await session.initialize()
     started=time.perf_counter()
     warm=await session.call_tool('ken_find',{'query':'find code that prepares a value','scope':'symbols','piece_kind':'symbol','output_format':'json'},read_timeout_seconds=120)
     if warm.is_error:raise ValueError('public warmup failed')
     warmup_ms=(time.perf_counter()-started)*1000
     for i,case in enumerate(cases):
      request={'query':case['query'],'scope':'files' if case['target_kind'] in {'file','module'} else 'symbols','piece_kind':case['target_kind'],'output_format':'json'}
      started=time.perf_counter();result=await session.call_tool('ken_find',request,read_timeout_seconds=120);ms=(time.perf_counter()-started)*1000
      if result.is_error:raise ValueError('actual public tool error: '+case['id'])
      data=json.loads('\n'.join(c.text for c in result.content if c.type=='text'))
      if data.get('ok') is False or any(r.get('stale') for r in data['results']):raise ValueError('unprepared/stale actual public response')
      units=[unit(r) for r in data['results']]
      if len(units)>10 or any(u['target_kind']!=case['target_kind'] for u in units):raise ValueError('wrong public requested unit')
      answer={'id':case['id'],'repo_id':repo,'target_kind':case['target_kind'],'units':units,'card':{'unit':units[0]} if units else None,'public_response':data}
      answers.append(answer);timings.append({'id':case['id'],'ms':ms,'cpu_ms':None,'target_kind':case['target_kind'],'cpu_note':'Per-query child CPU not exposed by MCP; complete process CPU measured in server telemetry'})
      if i==0:
       request.pop('output_format');compact=await session.call_tool('ken_find',request,read_timeout_seconds=120)
       if compact.is_error or '\n'.join(c.text for c in compact.content if c.type=='text')!=render(data):raise ValueError('default compact and native JSON return different public pieces')
       (args.output/'compact-example.txt').write_text('\n'.join(c.text for c in compact.content if c.type=='text'))
     return warmup_ms
 warmup_ms=asyncio.run(run());server=json.loads(telemetry.read_text())
 if server['providers']!=['CPUExecutionProvider'] or server['context_providers']!=['CPUExecutionProvider'] or server['heavy_imports']:raise ValueError('public CPU lightweight policy failed')
 (args.output/'answers.jsonl').write_text(''.join(json.dumps(a,ensure_ascii=False,sort_keys=True)+'\n' for a in answers))
 performance={'repo':repo,'source_receipt':lock['source_receipt'],'providers':server['providers'],'heavy_imports':server['heavy_imports'],'timings':timings,'warmup_ms':warmup_ms,'peak_rss_native':server['peak_rss_native'],'rss_unit':server['rss_unit'],'server_cpu_total_ms':server['cpu_total_ms'],'indexed_files':lock['indexed_files'][repo],'platform':platform.platform()}
 (args.output/'performance.json').write_text(json.dumps(performance,indent=2))
 if verify_frozen_source(engine)!=lock['source_receipt']:raise ValueError('source changed')

if __name__=='__main__':main()
