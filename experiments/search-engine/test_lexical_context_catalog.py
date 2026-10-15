"""The quote/feature consumers receive only pinned catalog bytes and generation."""
from dataclasses import asdict
import hashlib
import json
import sqlite3

import pytest

from test_lexical_context_evidence import fixture


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(tmp_path):
    source, context = fixture()
    index = tmp_path/'index.db'
    db = sqlite3.connect(index);db.execute('CREATE TABLE meta(key TEXT,value TEXT)')
    db.execute("INSERT INTO meta VALUES ('retrieval_generation','7')");db.commit();db.close()
    from dataclasses import replace
    context = replace(context, generation=f'{sha(index)}:g7')
    catalog = tmp_path/'sample-contexts.jsonl';catalog.write_text(json.dumps(asdict(context))+'\n')
    inventory = tmp_path/'sample-source-inventory.json';inventory.write_text(json.dumps([
        {'path':'sample.py','source_hash':hashlib.sha256(source).hexdigest(),'contexts':1}]))
    registration = tmp_path/'registration.json';registration.write_text(json.dumps({
        'complete':True,'engine_receipt':'f'*64,'context_version':1,'extractor_version':7,
        'repos':{'sample':{'contexts_sha256':sha(catalog),'inventory_sha256':sha(inventory),
            'source_index_sha256':sha(index),'generation':7,'counts':{'contexts':1}}}}))
    return {'folder':tmp_path,'registration_sha256':sha(registration),'engine_receipt':'f'*64,
            'repo':'sample','index':index},source,context


def test_pinned_catalog_yields_exact_context_and_checks_active_generation(tmp_path):
    from lexical_context_catalog import load_context_catalog
    args, source, context = files(tmp_path)
    catalog = load_context_catalog(**args)
    actual = catalog.get(context.primary, source_hash=context.source_hash, source_generation=7)
    assert actual == context
    assert actual.text.encode() == source.rstrip(b'\n')
    with pytest.raises(ValueError, match='generation'):
        catalog.get(context.primary, source_hash=context.source_hash, source_generation=8)
    with pytest.raises(ValueError, match='source'):
        catalog.get(context.primary, source_hash='0'*64, source_generation=7)
    with pytest.raises(TypeError):
        catalog.contexts[context.primary] = context


@pytest.mark.parametrize('fault', ['catalog', 'registration', 'index', 'inventory'])
def test_modified_artifacts_cannot_supply_context_even_with_fresh_source_hash(tmp_path, fault):
    from lexical_context_catalog import load_context_catalog
    args, _, _ = files(tmp_path)
    name = {'catalog':'sample-contexts.jsonl','registration':'registration.json',
            'index':'index.db','inventory':'sample-source-inventory.json'}[fault]
    with (tmp_path/name).open('ab') as stream:stream.write(b' ')
    with pytest.raises(ValueError):
        load_context_catalog(**args)
