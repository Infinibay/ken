"""Source-authenticated requested-piece cards and the fixed neural input projection.

Display formatting is separate: changing CLI/MCP compact output must not alter
these measured model inputs. No ranking model or benchmark labels enter here.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence, Mapping
from typing import Any

from ken.retrieval.model import CodeMatch, EntityKey
from ken.retrieval.piece_catalog import SourceCatalog, entity_id, module_name

MAX_LINES, MAX_EXCERPTS, MAX_CHARS = 64, 4, 12000
CARD_PROJECTION = 'requested-piece-card-v102'

def canonical(value: Any) -> str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def terms(text: str) -> set[str]:
    text=re.sub(r'([a-z])([A-Z])',r'\1 \2',text)
    return set(re.findall(r'[^\W_]{3,}',text.casefold()))-{
        'the','and','with','that','this','from','which','what','where','class',
        'file','module','symbol','function','clase','archivo','modulo','módulo',
        'simbolo','símbolo','función','para','que','una','los','las','del','con'}

def _window(catalog: SourceCatalog, key: EntityKey, query: str, n: int, *, implementation: bool = False) -> tuple[EntityKey, int, int] | None:
    q=terms(query); options=[]
    for p in catalog.owners[key]:
        start=p.span.start_line
        if implementation and p.implementation_start_line:
            start=max(start,p.implementation_start_line)
        end=p.span.end_line
        if start>end: continue
        lines=catalog.lines[key.path]
        # Source-only, query-conditioned window. No expected facets or ranker score.
        width=min(n,end-start+1)
        for a in range(start,end-width+2):
            content='\n'.join(lines[a-1:a+width-1])
            overlap=len(q & terms(content))
            options.append((overlap,-a,a,a+width-1))
    if not options: return None
    _,_,a,b=max(options)
    return key,a,b

def _source_fit(catalog: SourceCatalog, key: EntityKey, query: str) -> int:
    q=terms(query)
    return max((len(q&terms(p.fields.get('body','')+' '+p.fields.get('documentation','')
              +' '+(key.qualname or ''))) for p in catalog.owners[key]),default=0)

def build_card(primary: EntityKey | str, kind: str, supporting: Sequence[EntityKey], query: str, catalog: SourceCatalog) -> dict[str, Any]:
    path=primary.path if isinstance(primary,EntityKey) else primary
    entity=primary.to_dict() if isinstance(primary,EntityKey) else None
    card: dict[str, Any]={'unit':{'target_kind':kind,'path':path,'entity':entity,
                  'module_name':module_name(path) if kind=='module' else None},
          'source_hash':catalog.hashes[path],'excerpts':[],'truncated':False}
    if isinstance(primary,EntityKey):
        members=[k for k in catalog.by_path[path] if k==primary or
                 (kind=='class' and catalog.classes.get(k)==primary)]
    else: members=catalog.by_path[path]
    # Existing top-ranked support first; other source owners break ties by source fit.
    preferred=list(dict.fromkeys([k for k in supporting if k in members]))
    rest=sorted((k for k in members if k not in preferred),
                key=lambda k:(-_source_fit(catalog,k,query),entity_id(k)))
    ranked=preferred+rest
    proposals: list[tuple[str, tuple[EntityKey, int, int] | None]]=[]
    if isinstance(primary,EntityKey):
        first=min(catalog.owners[primary],key=lambda p:p.span.start_line)
        a=first.span.start_line;b=min(first.span.end_line,a+11)
        if first.implementation_start_line and first.implementation_start_line>a:
            b=min(b,first.implementation_start_line-1)
        proposals.append(('declaration',(primary,a,b)))
    else:
        module=next((k for k in members if k.kind=='module' and k.qualname is None),None)
        if module:
            proposals.append(('documentation',_window(catalog,module,query,12)))
    selected=[]
    for key in ranked:
        # Primary declaration already shown; child implementation has independent provenance.
        if kind=='class' and key==primary and len(ranked)>1: continue
        selected.append(key)
        if len(selected)==2: break
    for n,key in enumerate(selected):
        proposals.append(('implementation',_window(catalog,key,query,36 if n==0 else 16,
                                                     implementation=True)))
    # A separate source documentation passage when implementation starts after a docstring.
    if len(proposals)<MAX_EXCERPTS and selected:
        key=selected[0]
        docs=[p for p in catalog.owners[key] if p.fields.get('documentation','').strip()]
        if docs:
            p=max(docs,key=lambda p:len(terms(query)&terms(p.fields['documentation'])))
            b=min(p.span.end_line,p.span.start_line+11)
            if p.implementation_start_line and p.implementation_start_line>p.span.start_line:
                b=min(b,p.implementation_start_line-1)
            proposals.append(('documentation',(key,p.span.start_line,b)))
    used: set[int]=set(); count=0
    for role,proposal in proposals:
        if proposal is None or len(card['excerpts'])>=MAX_EXCERPTS: continue
        key,a,b=proposal
        # Only contiguous, genuinely new physical lines; no fabricated ellipsis.
        runs: list[list[int]]=[]
        run: list[int] | None=None
        for line in range(a,b+1):
            if line in used:
                if run: runs.append(run);run=None
            elif run: run[1]=line
            else: run=[line,line]
        if run:runs.append(run)
        for a,b in runs:
            if count>=MAX_LINES or len(card['excerpts'])>=MAX_EXCERPTS:
                card['truncated']=True;break
            b=min(b,a+MAX_LINES-count-1)
            e: dict[str, Any]={'role':role,'path':path,'start_line':a,'end_line':b,
               'source_hash':catalog.hashes[path],'entity':key.to_dict(),
               'content':'\n'.join(catalog.lines[path][a-1:b])}
            card['excerpts'].append(e)
            while len(canonical(card))>MAX_CHARS and e['end_line']>=e['start_line']:
                e['end_line']-=1;card['truncated']=True
                e['content']='\n'.join(catalog.lines[path][a-1:e['end_line']])
            if e['end_line']<a:
                card['excerpts'].pop();continue
            used.update(range(a,e['end_line']+1));count+=e['end_line']-a+1
    if isinstance(primary,EntityKey):
        a,b=catalog.extent(primary)
        expected=set(range(a,b+1))
    else: expected=set(range(1,len(catalog.lines[path])+1))
    card['truncated'] |= not expected<=used
    # Setting truncated can only shorten false -> true by one character.
    validate_card(card,catalog,check_disk=False)
    return card

def build_piece_cards(matches: Sequence[CodeMatch], kind: str, query: str, catalog: SourceCatalog, limit: int = 20) -> list[dict[str, Any]]:
    groups: dict[EntityKey | str, list[EntityKey]]={}
    for match in matches:
        primary=catalog.primary(match.entity,kind)
        if primary is None: continue
        groups.setdefault(primary,[]).append(match.entity)
    return [build_card(primary,kind,supporting,query,catalog)
            for primary,supporting in list(groups.items())[:limit]]

def validate_card(card: Mapping[str, Any], catalog: SourceCatalog, *, check_disk: bool = True) -> None:
    unit=card['unit'];path=unit['path'];kind=unit['target_kind']
    if path not in catalog.hashes or card['source_hash']!=catalog.hashes[path]:
        raise ValueError('unknown/stale card source')
    if check_disk:
        source = (catalog.root/path).resolve()
        if not source.is_relative_to(catalog.root):
            raise ValueError('source moved outside project root')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=card['source_hash']:
            raise ValueError('source changed since catalog')
    if kind in {'class','symbol'}:
        key=EntityKey(path=path,**unit['entity'])
        if key not in catalog.owners or catalog.primary(key,kind)!=key:
            raise ValueError('wrong canonical piece type')
        primary=key
    elif kind not in {'file','module'} or unit['entity'] is not None or (
            kind=='module' and module_name(path) is None):
        raise ValueError('wrong physical/import unit')
    count=0
    for e in card['excerpts']:
        a,b=e['start_line'],e['end_line']
        if e['entity'] is None and kind in {'module','file'}:
            key=EntityKey(e['path'],'module',None)
        elif isinstance(e['entity'],dict):key=EntityKey(path=e['path'],**e['entity'])
        else:raise ValueError('missing excerpt owner')
        if (e['path']!=path or e['source_hash']!=card['source_hash'] or key not in catalog.owners
                or not 1<=a<=b<=len(catalog.lines[path])):
            raise ValueError('invalid excerpt provenance')
        if kind in {'class','symbol'} and key!=primary and not (
                kind=='class' and catalog.classes.get(key)==primary):
            raise ValueError('unrelated owner cannot support primary piece')
        owned={n for p in catalog.owners[key] for n in range(p.span.start_line,p.span.end_line+1)}
        if not set(range(a,b+1))<=owned: raise ValueError('excerpt crosses source ownership')
        if e['content']!='\n'.join(catalog.lines[path][a-1:b]): raise ValueError('fabricated excerpt')
        count+=b-a+1
    if count>MAX_LINES or len(card['excerpts'])>MAX_EXCERPTS or len(canonical(card))>MAX_CHARS:
        raise ValueError('card budget exceeded')

def card_text(card: Mapping[str, Any]) -> str:
    unit=card['unit'];entity=unit['entity'] or {}
    header=f"{unit['target_kind']} {unit['path']} {entity.get('qualname') or unit.get('module_name') or ''}"
    body=[]
    for e in card['excerpts']:
        owner=(e['entity'] or {}).get('qualname') or e['path']
        body.append(f"{e['role']} {owner} lines {e['start_line']}-{e['end_line']}:\n{e['content']}")
    return header+'\n'+'\n'.join(body)
