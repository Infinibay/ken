"""Normal Ken MCP entrypoint, with process-only telemetry after shutdown."""
import json,os,resource,signal,sys
from pathlib import Path
from ken.cli import main

def report():
 from ken.retrieval.best_resources import default_resources
 usage=resource.getrusage(resource.RUSAGE_SELF)
 if default_resources.cache_info().currsize:
  models=default_resources();providers=list(models.neural.providers);context=list(models.context.providers)
 else:providers=context=[]
 Path(sys.argv[2]).write_text(json.dumps({'providers':providers,'context_providers':context,'peak_rss_native':usage.ru_maxrss,'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','cpu_total_ms':(usage.ru_utime+usage.ru_stime)*1000,'heavy_imports':[m for m in ('torch','transformers','sentence_transformers') if m in sys.modules]}))
def terminate(*args):
 report();raise SystemExit(0)
signal.signal(signal.SIGTERM,terminate)
try:main(['mcp',sys.argv[1]])
finally:report()
