"""Pinned Semble black-box producer. Input contains public queries and roots only."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import resource
import subprocess
import time
from importlib.metadata import version
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('requests',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--model-path',type=Path,required=True)
    parser.add_argument('--tool-root',type=Path,required=True)
    parser.add_argument('--grammar-cache',type=Path,required=True)
    args=parser.parse_args()
    expected='75cf7a6c2171b230ad19b1e7d8e0b1aee86da5a02af8e7cacedd9921d227623c'
    if hashlib.sha256((args.model_path/'model.safetensors').read_bytes()).hexdigest()!=expected:
        raise ValueError('registered Potion artifact required')
    args.output.mkdir(parents=True,exist_ok=False)
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['XDG_CACHE_HOME']=str(args.grammar_cache.resolve())
    os.environ['SEMBLE_CACHE_LOCATION']=str((args.output/'cache').resolve())
    os.environ['SEMBLE_INDEX_WORKERS']='4'
    from semble import SembleIndex
    from semble.utils import format_results
    from semble.version import __version__
    rows=[json.loads(l) for l in args.requests.read_text().splitlines()]
    allowed={'id','repo_id','repo_commit','root','query'}
    if any(set(r)!=allowed for r in rows) or len({r['id'] for r in rows})!=len(rows):
        raise ValueError('unique public-input request records required')
    files={p.relative_to(args.tool_root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((args.tool_root/'src').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    provenance={'version':__version__,'tool_commit':subprocess.check_output(['git','-C',str(args.tool_root),'rev-parse','HEAD'],text=True).strip(),
        'tool_files':files,'model_sha256':expected,'model_path':str(args.model_path.resolve()),
        'requests_sha256':hashlib.sha256(args.requests.read_bytes()).hexdigest(),
        'producer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'runtime':{p:version(p) for p in ('semble','model2vec','numpy','tokenizers','vicinity','semble-grammars')},
        'planned_ids':[r['id'] for r in rows],'top_k':10,'max_snippet_lines':40,
        'settings':'native defaults: alpha auto; rerank auto; unmodified tool and ignore policy',
        'timing_scope':'public library search plus native formatting+JSON; other CPU index jobs may coexist; no final performance certificate',
        'repos':{}}
    (args.output/'provenance.json').write_text(json.dumps(provenance,indent=2))
    for repo in sorted({r['repo_id'] for r in rows}):
        group=[r for r in rows if r['repo_id']==repo];root=Path(group[0]['root'])
        if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=group[0]['repo_commit']:
            raise ValueError('repository revision changed')
        print(json.dumps({'starting':repo}),flush=True)
        started=time.perf_counter();index=SembleIndex.from_path(root,model_path=str(args.model_path.resolve()))
        provenance['repos'][repo]={'index_seconds':time.perf_counter()-started,'stats':dataclasses.asdict(index.stats),
            'loaded_from_disk':index.loaded_from_disk}
        (args.output/'provenance.json').write_text(json.dumps(provenance,indent=2))
        index.search('prepare code search',top_k=10,max_snippet_lines=40)
        for row in group:
            started=time.perf_counter()
            try:
                hits=index.search(row['query'],top_k=10,max_snippet_lines=40)
                native=format_results(row['query'],hits,40)
                json.dumps(native,ensure_ascii=False)
                result={'id':row['id'],'repo_id':repo,'native':native,'ms':(time.perf_counter()-started)*1000,
                    'full_results':[dataclasses.asdict(h) for h in hits]}
            except Exception as exc:
                result={'id':row['id'],'repo_id':repo,'native':{'query':row['query'],'error':f'{type(exc).__name__}: {exc}','results':[]},
                        'ms':(time.perf_counter()-started)*1000}
            with (args.output/'raw-responses.jsonl').open('a') as out:
                out.write(json.dumps(result,ensure_ascii=False)+'\n')
        print(json.dumps({'completed':repo,'queries':len(group)}),flush=True)
        del index
    provenance['peak_rss_native']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    (args.output/'provenance.json').write_text(json.dumps(provenance,indent=2))


if __name__=='__main__':main()
