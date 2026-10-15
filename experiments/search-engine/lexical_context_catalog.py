"""Load pinned context artifacts and expose them for one active source generation."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType

from ken.retrieval.model import EntityKey, Span
from ken.retrieval.storage import generation
from lexical_context import ContextPart, LexicalContext, SyntaxScope


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _payload(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'context artifact differs from registered bytes: {path}')
    return data


@dataclass(frozen=True)
class RegisteredContexts:
    contexts: Mapping[EntityKey, LexicalContext]
    source_generation: int
    generation_id: str
    receipts: Mapping[str, str]

    def get(self, entity: EntityKey, *, source_hash: str,
            source_generation: int) -> LexicalContext | None:
        if source_generation != self.source_generation:
            raise ValueError('context catalog source generation changed')
        context = self.contexts.get(entity)
        if context is not None and context.source_hash != source_hash:
            raise ValueError('context catalog owner source changed')
        return context


def load_context_catalog(*, folder: Path, registration_sha256: str, engine_receipt: str,
                         repo: str, index: Path) -> RegisteredContexts:
    """Authenticate artifacts against trusted profile pins, not a search request.

    The expected hashes/producer receipt must come from an independently reviewed
    source registration. This does not certify an arbitrary manifest supplied by
    a user. Query consumers must pass the current index generation and owner
    source hash; visible quoting additionally checks the physical source bytes.
    """
    if Path(repo).name != repo or repo in {'.', '..'}:
        raise ValueError('context repository must be a registered simple name')
    registration = folder/'registration.json'
    manifest = json.loads(_payload(registration, registration_sha256))
    if (not manifest['complete'] or manifest['engine_receipt'] != engine_receipt
            or manifest['context_version'] != 1 or manifest['extractor_version'] != 7):
        raise ValueError('context source registration has a different version or producer')
    meta = manifest['repos'][repo]
    catalog_path = folder/f'{repo}-contexts.jsonl'
    inventory_path = folder/f'{repo}-source-inventory.json'
    encoded = _payload(catalog_path, meta['contexts_sha256'])
    inventory = json.loads(_payload(inventory_path, meta['inventory_sha256']))
    sources = {row['path']: row['source_hash'] for row in inventory}
    if len(sources) != len(inventory):
        raise ValueError('duplicate context source inventory paths')
    if _sha(index) != meta['source_index_sha256']:
        raise ValueError('context source index changed')
    with closing(sqlite3.connect(index.resolve().as_uri()+'?mode=ro', uri=True)) as connection:
        current = generation(connection)
    if current != meta['generation']:
        raise ValueError('context source generation differs from registration')
    generation_id = f"{meta['source_index_sha256']}:g{current}"
    contexts: dict[EntityKey, LexicalContext] = {}
    for line in encoded.splitlines():
        row = json.loads(line)
        context = LexicalContext(EntityKey(**row['primary']), row['source_hash'], row['generation'],
            Span(**row['extent']), row['start_byte'], row['end_byte'],
            tuple(ContextPart(EntityKey(**part['owner']) if part['owner'] is not None else None,
                Span(**part['span']), part['start_byte'], part['end_byte'], part['text']) for part in row['parts']),
            tuple(SyntaxScope(**scope) for scope in row['scopes']), row['relation'])
        if (context.primary in contexts or context.generation != generation_id
                or context.source_hash != sources.get(context.primary.path)
                or context.relation != 'lexically_contains'):
            raise ValueError('context rows differ from their registered identity/source')
        contexts[context.primary] = context
    if len(contexts) != meta['counts']['contexts']:
        raise ValueError('context rows are incomplete')
    if _sha(index) != meta['source_index_sha256']:
        raise ValueError('context source index changed while loading')
    receipts = {str(registration): registration_sha256, str(catalog_path): meta['contexts_sha256'],
                str(inventory_path): meta['inventory_sha256'], str(index): meta['source_index_sha256']}
    return RegisteredContexts(MappingProxyType(contexts), current, generation_id, MappingProxyType(receipts))
