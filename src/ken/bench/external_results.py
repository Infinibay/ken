"""Normalize visible external snippets without consulting relevance references."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ken.bench.dataset import valid_path
from ken.retrieval.model import EntityKey, Passage, Span, merge_spans


class OwnerLookup:
    """Resolve an unambiguous owner from indexed source regions, never query labels."""
    def __init__(self, passages: Iterable[Passage]):
        regions: dict[EntityKey,list[Span]] = defaultdict(list)
        self.source_hashes: dict[str,str] = {}
        for passage in passages:
            path=passage.entity.path
            if self.source_hashes.get(path,passage.source_hash)!=passage.source_hash:
                raise ValueError('mixed source generations in owner index')
            self.source_hashes[path]=passage.source_hash
            if passage.entity.qualname is not None:
                regions[passage.entity].append(passage.span)
        self.by_path: dict[str,list[tuple[EntityKey,tuple[Span,...]]]] = defaultdict(list)
        for entity,spans in regions.items():
            self.by_path[entity.path].append((entity,merge_spans(spans)))

    def resolve(self, path: str, lines: list[int]) -> EntityKey | None:
        if not lines:
            return None
        matches=[entity for entity,regions in self.by_path.get(path,[]) if all(
            any(s.start_line<=line<=s.end_line for s in regions) for line in lines)]
        return matches[0] if len(matches)==1 else None


def normalize(native: dict[str,Any], root: Path, owners: OwnerLookup, *,
              max_chars: int = 12000) -> dict[str,Any]:
    """Keep native order and visible complete lines; only restore edge indentation."""
    if max_chars<=0:
        raise ValueError('positive output budget required')
    response: dict[str,Any] = {'query':native.get('query',''),'results':[],
        'profile_version':'external-native-visible-v2','warnings':[],
        'truncated':False,'omitted_count':0}
    if native.get('error'):
        response['error']=native['error']
        return response
    if len(native['results'])>10:
        raise ValueError('external producer exceeded requested result limit')
    for hit in native['results']:
        path=hit['file_path']
        result={'path':path,'entity':None,'source_hash':'','evidence':[],
            'ranking_score':hit['score'],'stale':False,'truncated':False}
        try:
            target=(root/path).resolve()
            if not valid_path(path) or not target.is_relative_to(root.resolve()):
                raise ValueError('external source path escapes repository')
            source=target.read_bytes();digest=hashlib.sha256(source).hexdigest()
            result['source_hash']=digest
            if owners.source_hashes.get(path,digest)!=digest:
                raise ValueError('source changed since canonical ownership indexing')
            lines=source.decode('utf-8').splitlines()
            start=hit['start_line'];shown=[]
            if type(start) is not int or not 1<=start<=len(lines):
                raise ValueError('external snippet starts outside source')
            native_lines=hit.get('content','').splitlines()[:40]
            visible_start=start
            for i,line in enumerate(native_lines):
                position=start+i-1
                if position>=len(lines):
                    raise ValueError('external snippet ends outside source')
                expected=lines[position]
                if line==expected or (i==0 and line.lstrip()==expected.lstrip()):
                    shown.append(expected)
                elif i==0 and expected.endswith(line):
                    # A byte chunk may also begin inside a declaration. Keep
                    # the following complete lines without inventing its head.
                    visible_start=start+1
                elif i==len(native_lines)-1 and expected.startswith(line):
                    # A byte chunk may stop mid-statement. Its missing suffix
                    # was never visible and cannot become acceptance evidence.
                    break
                else:
                    raise ValueError('external snippet does not match source')
            if shown:
                end=visible_start+len(shown)-1
                result['evidence']=[{'start_line':visible_start,'end_line':end,'content':'\n'.join(shown)}]
                substantive=[visible_start+i for i,line in enumerate(shown) if line.strip()]
                entity=owners.resolve(path,substantive)
                result['entity']=entity.to_dict() if entity else None
            result['truncated']=(len(shown)<len(hit.get('content','').splitlines()) or
                                 bool(shown and end<hit['end_line']))
        except (OSError,ValueError,UnicodeError) as exc:
            result.update(stale=True,evidence=[],entity=None)
            response['warnings'].append(f'{path}: {exc}')
        response['results'].append(result)
    def size():
        return len(json.dumps(response,ensure_ascii=False,separators=(',',':')))
    while response['results'] and size()>max_chars:
        result=response['results'][-1];evidence=result['evidence']
        if evidence and evidence[0]['start_line']<evidence[0]['end_line']:
            fragment=evidence[0]
            fragment['end_line']-=1
            fragment['content']='\n'.join(fragment['content'].split('\n')[:-1])
            result['truncated']=True
        else:
            response['results'].pop();response['omitted_count']+=1
        response['truncated']=True
    response['truncated'] |= any(r['truncated'] for r in response['results'])
    if size()>max_chars:
        raise ValueError('external response metadata exceeds output budget')
    return response
