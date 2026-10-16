import io
import tarfile

import pytest
from native_sources_v235 import extract_revision, group_requests


def make_archive(tmp_path, name, kind=tarfile.REGTYPE):
    archive=tmp_path/'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as stream:
        entry=tarfile.TarInfo(name)
        entry.type=kind
        body=b'original\r\nbytes\x00'
        entry.size=len(body) if kind==tarfile.REGTYPE else 0
        stream.addfile(entry, io.BytesIO(body) if entry.size else None)
    return archive


def test_source_projection_preserves_original_names_and_bytes(tmp_path):
    archive=make_archive(tmp_path,'repo-commit/pkg/a.py')
    root=tmp_path/'snapshot'
    pins=extract_revision(archive, root, 'repo-commit')
    assert set(pins)=={'pkg/a.py'}
    assert (root/'pkg/a.py').read_bytes()==b'original\r\nbytes\x00'


@pytest.mark.parametrize('name,kind', [
    ('repo-commit/../outside.py',tarfile.REGTYPE),
    ('/repo-commit/a.py',tarfile.REGTYPE),
    ('other-root/a.py',tarfile.REGTYPE),
    ('repo-commit/a.py',tarfile.SYMTYPE),
])
def test_rejects_unsafe_or_nonregular_archives(tmp_path,name,kind):
    with pytest.raises(ValueError):
        extract_revision(make_archive(tmp_path,name,kind),tmp_path/'snapshot','repo-commit')


def test_same_query_levels_share_one_native_measurement_without_dropping_cases():
    sources={'a':{'public_query_id':'issue-1','level':'LEVEL-2'},
             'b':{'public_query_id':'issue-1','level':'LEVEL-3'}}
    requests=[{'id':'A','repo_id':'a','query':'same original\nquery'},
              {'id':'B','repo_id':'b','query':'same original\nquery'}]
    grouped=group_requests(requests,sources,[{'instance_id':'issue-1','base_commit':'abc'}])
    assert len(grouped)==1
    assert grouped[0]['query']=='same original\nquery'
    assert grouped[0]['cases']==[{'id':'A','level':'LEVEL-2'},{'id':'B','level':'LEVEL-3'}]


def test_different_query_texts_cannot_be_silently_merged():
    sources={'a':{'public_query_id':'issue-1','level':'LEVEL-2'},
             'b':{'public_query_id':'issue-1','level':'LEVEL-3'}}
    requests=[{'id':'A','repo_id':'a','query':'original'},
              {'id':'B','repo_id':'b','query':'rewritten'}]
    with pytest.raises(ValueError):
        group_requests(requests,sources,[{'instance_id':'issue-1'}])
