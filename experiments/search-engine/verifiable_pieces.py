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
        self._extents={};self._scopes={}
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
                candidates=[k for k in classes if self.encloses(k,key)]
                if candidates:
                    candidates.sort(key=lambda k:(self.extent(k)[1]-self.extent(k)[0],entity_id(k)))
                    if len(candidates)>1 and self.extent(candidates[0])==self.extent(candidates[1]):
                        raise ValueError('ambiguous enclosing class')
                    self.classes[key]=candidates[0]

    def extent(self,key):
        if key not in self._extents:
            self._extents[key]=(min(p.entity_span.start_line for p in self.owners[key]),
                                max(p.entity_span.end_line for p in self.owners[key]))
        return self._extents[key]

    def encloses(self,outer,inner):
        return bool(outer!=inner and outer.path==inner.path and outer.qualname and inner.qualname
            and inner.qualname.startswith(outer.qualname+'.')
            and self.extent(outer)[0]<=self.extent(inner)[0]<=self.extent(inner)[1]<=self.extent(outer)[1])

    def scope_members(self,key):
        """Known descendants that account for every nonblank line in the scope."""
        if key not in self._scopes:
            descendants=tuple(sorted((k for k in self.by_path[key.path] if self.encloses(key,k)),key=entity_id))
            covered={n for member in (key,*descendants)
                     for a,b in self.owned_ranges(member) for n in range(a,b+1)}
            a,b=self.extent(key)
            self._scopes[key]=(descendants if all(n in covered or not self.lines[key.path][n-1].strip()
                               for n in range(a,b+1)) else None)
        return self._scopes[key]

    def enclosing_callable(self,key):
        candidates=[k for k in self.by_path[key.path] if k.kind in {'function','method'} and self.encloses(k,key)]
        order=lambda k:(self.extent(k)[1]-self.extent(k)[0],-len(k.qualname or ''))
        candidates.sort(key=lambda k:(order(k),entity_id(k)))
        if not candidates or len(candidates)>1 and order(candidates[0])==order(candidates[1]):return None
        return candidates[0]

    def owned_ranges(self,key,*,implementation=False):
        """Contiguous owned source, independent of retrieval fragment boundaries."""
        intervals=[]
        for p in self.owners[key]:
            start=p.span.start_line
            if implementation and p.implementation_start_line:
                start=max(start,p.implementation_start_line)
            if start<=p.span.end_line:
                intervals.append((start,p.span.end_line))
        merged=[]
        for start,end in sorted(intervals):
            if merged and start<=merged[-1][1]+1:
                merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else: merged.append((start,end))
        return merged

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
    for start,end in catalog.owned_ranges(key,implementation=implementation):
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


def _complete_owned_card(primary,card,catalog):
    ranges=catalog.owned_ranges(primary)
    if (not ranges or len(ranges)>MAX_EXCERPTS
            or sum(end-start+1 for start,end in ranges)>MAX_LINES):
        return None
    excerpts=[{'role':'definition','path':primary.path,'start_line':start,'end_line':end,
        'source_hash':catalog.hashes[primary.path],'entity':primary.to_dict(),
        'content':'\n'.join(catalog.lines[primary.path][start-1:end])} for start,end in ranges]
    complete={**card,'excerpts':excerpts,'truncated':ranges!=[catalog.extent(primary)]}
    if len(canonical(complete))>MAX_CHARS: return None
    validate_card(complete,catalog,check_disk=False)
    return complete


def _complete_scope_card(primary,card,catalog):
    if primary.kind not in {'class','function','method'}:return None
    a,b=catalog.extent(primary)
    if b-a+1>MAX_LINES:return None
    members=catalog.scope_members(primary)
    if not members:return None
    excerpt={'role':'definition','path':primary.path,'start_line':a,'end_line':b,
        'source_hash':catalog.hashes[primary.path],'entity':primary.to_dict(),
        'scope':'lexical_container','included_entities':[key.to_dict() for key in members],
        'content':'\n'.join(catalog.lines[primary.path][a-1:b])}
    truncated=card['unit']['target_kind'] in {'file','module'} and (a,b)!=(1,len(catalog.lines[primary.path]))
    complete={**card,'excerpts':[excerpt],'truncated':truncated}
    if len(canonical(complete))>MAX_CHARS:return None
    validate_card(complete,catalog,check_disk=False)
    return complete


def excerpt_owners(excerpt):
    entities=[excerpt['entity']] if excerpt['entity'] is not None else []
    if excerpt.get('scope')=='lexical_container':entities+=excerpt['included_entities']
    return tuple(EntityKey(path=excerpt['path'],**entity) for entity in entities)


class EvidenceCardBuilder:
    """Pack literal owned source under the shared response budget."""
    def __init__(self,card,catalog):
        self.card=card
        self.catalog=catalog
        self.used={(e['path'],n) for e in card['excerpts']
                   for n in range(e['start_line'],e['end_line']+1)}

    @property
    def remaining_lines(self):
        return MAX_LINES-sum(e['end_line']-e['start_line']+1 for e in self.card['excerpts'])

    @property
    def remaining_excerpts(self): return MAX_EXCERPTS-len(self.card['excerpts'])

    def add(self,role,proposal,*,dependency=None):
        if proposal is None: return
        key,a,b=proposal
        runs=[];run=None
        for line in range(a,b+1):
            if (key.path,line) in self.used:
                if run: runs.append(run);run=None
            elif run: run[1]=line
            else: run=[line,line]
        if run:runs.append(run)
        for a,b in runs:
            if not self.remaining_lines or not self.remaining_excerpts:
                self.card['truncated']=True;break
            b=min(b,a+self.remaining_lines-1)
            excerpt={'role':role,'path':key.path,'start_line':a,'end_line':b,
                'source_hash':self.catalog.hashes[key.path],'entity':key.to_dict(),
                'content':'\n'.join(self.catalog.lines[key.path][a-1:b])}
            if dependency is not None:excerpt['dependency']=dependency
            self.card['excerpts'].append(excerpt)
            while len(canonical(self.card))>MAX_CHARS and excerpt['end_line']>=a:
                excerpt['end_line']-=1;self.card['truncated']=True
                excerpt['content']='\n'.join(self.catalog.lines[key.path][a-1:excerpt['end_line']])
            if excerpt['end_line']<a:
                self.card['excerpts'].pop();continue
            self.used.update((key.path,n) for n in range(a,excerpt['end_line']+1))

    def definition(self,key,query,*,dependency=None):
        """Prefer complete ownership; spend remaining capacity on a long body."""
        ranges=self.catalog.owned_ranges(key)
        needed=sum((key.path,n) not in self.used for a,b in ranges for n in range(a,b+1))
        if needed<=self.remaining_lines and len(ranges)<=self.remaining_excerpts:
            for a,b in ranges:self.add('definition',(key,a,b),dependency=dependency)
            return
        self.card['truncated']=True
        if not self.remaining_lines or not self.remaining_excerpts:return
        first=min(self.catalog.owners[key],key=lambda p:p.span.start_line)
        a=first.span.start_line;b=min(first.span.end_line,a+11)
        if first.implementation_start_line and first.implementation_start_line>a:
            b=min(b,first.implementation_start_line-1)
        if self.remaining_excerpts>1:self.add('declaration',(key,a,b),dependency=dependency)
        if self.remaining_lines and self.remaining_excerpts:
            self.add('implementation',_window(self.catalog,key,query,self.remaining_lines,
                                               implementation=True),dependency=dependency)


def _card(primary,kind,supporting,query,catalog):
    path=primary.path if isinstance(primary,EntityKey) else primary
    entity=primary.to_dict() if isinstance(primary,EntityKey) else None
    card={'unit':{'target_kind':kind,'path':path,'entity':entity,
                  'module_name':module_name(path) if kind=='module' else None},
          'source_hash':catalog.hashes[path],'excerpts':[],'truncated':False}
    if isinstance(primary,EntityKey):
        complete=_complete_scope_card(primary,card,catalog)
        if complete is not None:return complete
    if kind=='symbol':
        complete=_complete_owned_card(primary,card,catalog)
        if complete is not None: return complete
    if isinstance(primary,EntityKey):
        members=[k for k in catalog.by_path[path] if k==primary or
                 (kind=='class' and catalog.classes.get(k)==primary)]
    else: members=catalog.by_path[path]
    # Existing top-ranked support first; other source owners break ties by source fit.
    preferred=list(dict.fromkeys([k for k in supporting if k in members]))
    rest=sorted((k for k in members if k not in preferred),
                key=lambda k:(-_source_fit(catalog,k,query),entity_id(k)))
    ranked=preferred+rest
    if kind in {'module','file'} and ranked:
        enclosing=catalog.enclosing_callable(ranked[0])
        for candidate in (enclosing,ranked[0]):
            if candidate is not None:
                complete=_complete_scope_card(candidate,card,catalog)
                if complete is not None:return complete
    builder=EvidenceCardBuilder(card,catalog)
    if isinstance(primary,EntityKey):
        first=min(catalog.owners[primary],key=lambda p:p.span.start_line)
        a=first.span.start_line;b=min(first.span.end_line,a+11)
        if first.implementation_start_line and first.implementation_start_line>a:
            b=min(b,first.implementation_start_line-1)
        builder.add('declaration',(primary,a,b))
    selected=[]
    for key in ranked:
        # Primary declaration already shown; child implementation has independent provenance.
        if kind=='class' and key==primary and len(ranked)>1: continue
        selected.append(key)
        if len(selected)==2: break
    for key in selected:builder.definition(key,query)
    if isinstance(primary,EntityKey):
        a,b=catalog.extent(primary)
        expected={(path,n) for n in range(a,b+1)}
    else: expected={(path,n) for n in range(1,len(catalog.lines[path])+1)}
    card['truncated'] |= not expected<=builder.used
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


def validate_card(card,catalog,*,check_disk=True,dependencies=None):
    if dependencies is not None and dependencies.catalog is not catalog:
        raise ValueError('dependency resolver uses a different source catalog')
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
        if 'dependency' in e:
            if dependencies is None:raise ValueError('dependency resolver required')
            dependencies.validate(card,e,key)
        elif kind in {'class','symbol'} and key!=primary and not (
                kind=='class' and catalog.classes.get(key)==primary):
            raise ValueError('unrelated owner cannot support primary piece')
        if e.get('scope')=='lexical_container':
            members=catalog.scope_members(key)
            if (not members or (a,b)!=catalog.extent(key)
                    or e.get('included_entities')!=[k.to_dict() for k in members]):
                raise ValueError('invalid lexical scope attribution')
        elif 'scope' in e or 'included_entities' in e:
            raise ValueError('invalid lexical scope mode')
        else:
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
