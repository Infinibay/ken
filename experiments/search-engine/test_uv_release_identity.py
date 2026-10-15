"""A native result keeps its position and must identify the actual entity."""
import pytest
import hashlib
from pathlib import Path


def inventory():
    return [
        {'path':'cache.py','entity':{'kind':'class','qualname':'Cache','owner':None,
         'definition_ordinal':0},'extent':[1,50]},
        {'path':'cache.py','entity':{'kind':'method','qualname':'Cache.get','owner':'Cache',
         'definition_ordinal':0},'extent':[5,10]},
        {'path':'cache.py','entity':{'kind':'method','qualname':'Cache.get','owner':'Cache',
         'definition_ordinal':1},'extent':[30,40]},
    ]


def test_method_does_not_receive_credit_for_its_enclosing_class():
    from uv_release_identity import native_units
    raw=[{'file':'cache.py','qualname':'Cache.get','kind':'method','line':5}]
    assert native_units(raw,'class',inventory()) == [None]


def test_duplicate_names_resolve_to_the_definition_actually_returned():
    from uv_release_identity import native_units
    raw=[{'file':'cache.py','qualname':'Cache.get','kind':'method','line':30}]
    result=native_units(raw,'symbol',inventory())
    assert result[0]['unit']['entity']['definition_ordinal'] == 1
    assert result[0]['unit']['path'] == 'cache.py'


def test_invalid_result_does_not_promote_the_second_candidate_to_top1():
    from uv_release_identity import native_units
    raw=[{'file':'cache.py','qualname':'Cache.get','kind':'method','line':5},
         {'file':'cache.py','qualname':'Cache','kind':'class','line':1}]
    result=native_units(raw,'class',inventory())
    assert len(result)==2
    assert result[0] is None
    assert result[1]['unit']['entity']['qualname']=='Cache'


def test_same_symbol_name_in_another_file_is_not_a_canonical_match():
    from uv_release_identity import native_units
    raw=[{'file':'other.py','qualname':'Cache','kind':'class','line':1}]
    assert native_units(raw,'class',inventory()) == [None]


@pytest.mark.parametrize('kind',['module','file'])
def test_file_results_preserve_native_paths_and_positions(kind):
    from uv_release_identity import native_units
    raw=[{'path':'wrong.py'},{'path':'cache.py'}]
    result=native_units(raw,kind,inventory())
    assert [r['unit']['path'] for r in result] == ['wrong.py','cache.py']
    assert all(r['unit']['target_kind']==kind for r in result)


def test_duplicate_name_without_location_is_unresolved():
    from uv_release_identity import native_units
    raw=[{'file':'cache.py','qualname':'Cache.get','kind':'method'}]
    assert native_units(raw,'symbol',inventory()) == [None]


def test_native_install_metadata_does_not_change_the_benchmark_snapshot(tmp_path):
    from uv_release_capture import restore_source_snapshot
    source=tmp_path/'source';copy=tmp_path/'copy'
    source.mkdir();copy.mkdir()
    original=b'__pycache__/\n'
    (source/'.gitignore').write_bytes(original)
    (copy/'.gitignore').write_bytes(original+b'.ken/\n')
    rows=[{'path':'.gitignore','source_hash':hashlib.sha256(original).hexdigest()}]
    assert restore_source_snapshot(copy,source,rows)==[Path('.gitignore')]
    assert (copy/'.gitignore').read_bytes()==original
    assert (source/'.gitignore').read_bytes()==original


def test_unexpected_source_mutation_is_preserved_and_rejected(tmp_path):
    from uv_release_capture import restore_source_snapshot
    source=tmp_path/'source';copy=tmp_path/'copy'
    source.mkdir();copy.mkdir()
    (source/'code.py').write_bytes(b'x=1\n');(copy/'code.py').write_bytes(b'x=2\n')
    rows=[{'path':'code.py','source_hash':hashlib.sha256(b'x=1\n').hexdigest()}]
    with pytest.raises(ValueError,match='unexpected'):
        restore_source_snapshot(copy,source,rows)
    assert (copy/'code.py').read_bytes()==b'x=2\n'
