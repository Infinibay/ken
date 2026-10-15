"""Typed, source-authenticated answer cards, independent of ranking models/Gold."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from ken.retrieval.model import EntityKey

SYMBOL_KINDS = frozenset({'function','method','const','constant'})
MAX_LINES, MAX_EXCERPTS, MAX_CHARS = 64, 4, 12000


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def entity_id(key):
    return canonical({'path':key.path,**key.to_dict()})


def terms(text):
    text=re.sub(r'([a-z])([A-Z])',r'\1 \2',text)
    return set(re.findall(r'[^\W_]{3,}',text.casefold()))-{
        'the','and','with','that','this','from','which','what','where','class',
        'file','module','symbol','function','clase','archivo','modulo','módulo',
        'simbolo','símbolo','función','para','que','una','los','las','del','con'}


def module_name(path):
    p=Path(path)
    if p.suffix not in {'.py','.pyi','.js','.jsx','.mjs','.cjs','.ts','.tsx','.mts','.cts'}:
        return None
    if any(part.startswith('.') or part in {'node_modules','vendor'} for part in p.parts[:-1]):
        return None
    parts=list(p.with_suffix('').parts)
    if parts[-1]=='__init__': parts.pop()
    if parts and parts[0]=='src': parts.pop(0)
    if p.suffix in {'.py','.pyi'} and not all(x.isidentifier() for x in parts):
        return None
    return '.'.join(parts) if p.suffix in {'.py','.pyi'} else '/'.join(parts)


class SourceCatalog:
    """Canonical source owners, physical lines and lexical class containment."""
    def __init__(self,root,owners):
        self.root=Path(root).resolve()
        self.owners=dict(owners)
        self.by_path=defaultdict(list)
        self.lines={}; self.hashes={}
        for key,passages in owners.items():
            if not passages: raise ValueError('empty owner')
            path=(self.root/key.path).resolve()
            if not path.is_relative_to(self.root): raise ValueError('source outside root')
            if key.path not in self.lines:
                data=path.read_bytes();self.lines[key.path]=data.decode('utf-8').splitlines()
                self.hashes[key.path]=hashlib.sha256(data).hexdigest()
            if any(p.source_hash!=self.hashes[key.path] for p in passages):
                raise ValueError('stale source catalog: '+key.path)
            self.by_path[key.path].append(key)
        self.classes={}
        for path,keys in self.by_path.items():
            classes=[k for k in keys if k.kind=='class']
            for key in keys:
                own=self.extent(key)
                candidates=[k for k in classes if k!=key and self.extent(k)[0]<=own[0]
                    and own[1]<=self.extent(k)[1] and key.qualname and k.qualname
                    and key.qualname.startswith(k.qualname+'.')]
                if candidates:
                    candidates.sort(key=lambda k:(self.extent(k)[1]-self.extent(k)[0],entity_id(k)))
                    if len(candidates)>1 and self.extent(candidates[0])==self.extent(candidates[1]):
                        raise ValueError('ambiguous enclosing class')
                    self.classes[key]=candidates[0]

    def extent(self,key):
        return (min(p.entity_span.start_line for p in self.owners[key]),
                max(p.entity_span.end_line for p in self.owners[key]))

    def source_inventory(self):
        return [{'path':k.path,'entity':k.to_dict(),'source_hash':self.hashes[k.path],
            'extent':self.extent(k),'owned_ranges':[[p.span.start_line,p.span.end_line]
                for p in self.owners[k]],'enclosing_class':self.classes[k].to_dict()
                if k in self.classes else None} for k in sorted(self.owners,key=entity_id)]

    def primary(self,key,kind):
        if kind=='class': return key if key.kind=='class' else self.classes.get(key)
        if kind=='symbol': return key if key.kind in SYMBOL_KINDS else None
        if kind=='module': return key.path if module_name(key.path) is not None else None
        if kind=='file': return key.path
        raise ValueError('unknown piece kind')


def _window(catalog,key,query,n,*,implementation=False):
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


def _source_fit(catalog,key,query):
    q=terms(query)
    return max((len(q&terms(p.fields.get('body','')+' '+p.fields.get('documentation','')
              +' '+(key.qualname or ''))) for p in catalog.owners[key]),default=0)


def _card(primary,kind,supporting,query,catalog):
    path=primary.path if isinstance(primary,EntityKey) else primary
    entity=primary.to_dict() if isinstance(primary,EntityKey) else None
    card={'unit':{'target_kind':kind,'path':path,'entity':entity,
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
    proposals=[]
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
    used=set(); count=0
    for role,proposal in proposals:
        if proposal is None or len(card['excerpts'])>=MAX_EXCERPTS: continue
        key,a,b=proposal
        # Only contiguous, genuinely new physical lines; no fabricated ellipsis.
        runs=[];run=None
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
            e={'role':role,'path':path,'start_line':a,'end_line':b,
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


def piece_pool(matches,kind,query,catalog,limit=20):
    groups={}
    for match in matches:
        primary=catalog.primary(match.entity,kind)
        if primary is None: continue
        groups.setdefault(primary,[]).append(match.entity)
    return [_card(primary,kind,supporting,query,catalog)
            for primary,supporting in list(groups.items())[:limit]]


def validate_card(card,catalog,*,check_disk=True):
    unit=card['unit'];path=unit['path'];kind=unit['target_kind']
    if path not in catalog.hashes or card['source_hash']!=catalog.hashes[path]:
        raise ValueError('unknown/stale card source')
    if check_disk and hashlib.sha256((catalog.root/path).read_bytes()).hexdigest()!=card['source_hash']:
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


def card_text(card):
    unit=card['unit'];entity=unit['entity'] or {}
    header=f"{unit['target_kind']} {unit['path']} {entity.get('qualname') or unit.get('module_name') or ''}"
    body=[]
    for e in card['excerpts']:
        owner=(e['entity'] or {}).get('qualname') or e['path']
        body.append(f"{e['role']} {owner} lines {e['start_line']}-{e['end_line']}:\n{e['content']}")
    return header+'\n'+'\n'.join(body)
