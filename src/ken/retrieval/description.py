"""Separate the source information contributed by one canonical owner."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ken.retrieval.model import EntityKey, Passage

DESCRIPTION_VERSION = 1
_COMMENT = re.compile(r'^\s*(?:#|//|/\*|\*|--)')
_CALL = re.compile(r'[\w$.]+(?=\s*\()')
_RETURN = re.compile(r'\b(?:return|throw|raise|yield)\b')


@dataclass(frozen=True)
class OwnerDescription:
    entity: EntityKey
    source_hash: str
    fields: dict[str, str]
    owned_lines: int
    implementation_lines: int
    executable_lines: int
    comment_lines: int
    regions: int


def describe_owner(passages: Sequence[Passage]) -> OwnerDescription:
    """Use every owned region once; never fill gaps with another owner's text.

    The executable/comment split is a lexical projection for ranking. Canonical
    source ranges and the evidence renderer continue to use the original bytes.
    """
    if not passages:
        raise ValueError('owner description requires passages')
    first = passages[0]
    if any(p.entity != first.entity for p in passages):
        raise ValueError('mixed owner identities in description')
    if any(p.source_hash != first.source_hash for p in passages):
        raise ValueError('mixed source versions in description')
    unique = {p.span: p for p in passages}
    ordered = sorted(unique.values(), key=lambda p: p.span.start_line)
    fields = {name: '\n'.join(dict.fromkeys(p.fields.get(name, '') for p in ordered))
              for name in ('identity', 'signature', 'documentation', 'body', 'path')}
    implementation: list[str] = []
    for passage in ordered:
        offset = max(0, (passage.implementation_start_line or passage.span.start_line)
                     - passage.span.start_line)
        implementation.extend(passage.fields['body'].split('\n')[offset:])
    comments = [line for line in implementation if _COMMENT.match(line)]
    executable = [line for line in implementation if line.strip() and not _COMMENT.match(line)]
    fields.update(implementation='\n'.join(implementation), comments='\n'.join(comments),
                  executable='\n'.join(executable),
                  calls='\n'.join(_CALL.findall('\n'.join(executable))),
                  returns='\n'.join(line for line in executable if _RETURN.search(line)))
    return OwnerDescription(first.entity, first.source_hash, fields,
        sum(p.span.end_line - p.span.start_line + 1 for p in ordered), len(implementation),
        len(executable), len(comments), len(ordered))
