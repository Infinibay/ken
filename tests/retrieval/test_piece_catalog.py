"""Source identity and containment are independent of retrieval/model scores."""
import hashlib
from pathlib import Path

import pytest
from ken.retrieval.model import EntityKey,Passage,Span


@pytest.fixture
def source_owners(tmp_path):
    path='src/pkg/engine.py';p=tmp_path/path;p.parent.mkdir(parents=True)
    p.write_text('class Outer:\n    value = 1\n    class Inner:\n        def run(self):\n            return 1\n    def read(self):\n        return self.value\ndef helper():\n    return 2\n')
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    def owner(kind,name,start,end,extent_end=None):
        key=EntityKey(path,kind,name,name.rpartition('.')[0] or None)
        return key,[Passage(key,Span(start,end),{'body':'','identity':name,'signature':'','documentation':'','path':path},digest,Span(start,extent_end or end))]
    values=[owner('class','Outer',1,2,7),owner('class','Outer.Inner',3,3,5),
        owner('method','Outer.Inner.run',4,5),owner('method','Outer.read',6,7),owner('function','helper',8,9)]
    return tmp_path,dict(values),{k.qualname:k for k,_ in values}


def test_nearest_class_and_scope_members_preserve_actual_owner_identity(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners)
    assert catalog.primary(k['Outer.Inner.run'],'class')==k['Outer.Inner']
    assert catalog.primary(k['Outer.read'],'class')==k['Outer']
    assert catalog.primary(k['Outer.Inner'],'class')==k['Outer.Inner']
    assert catalog.primary(k['helper'],'class') is None
    assert set(catalog.scope_members(k['Outer']))=={k['Outer.Inner'],k['Outer.Inner.run'],k['Outer.read']}
    assert catalog.extent(k['Outer'])==(1,7)
    assert catalog.owned_ranges(k['Outer.Inner.run'])==[(4,5)]


def test_module_and_file_are_named_at_the_requested_granularity(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog,module_name
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners)
    assert module_name('src/pkg/engine.py')=='pkg.engine'
    assert module_name('src/pkg/__init__.py')=='pkg'
    assert module_name('src/Settings.java') is None
    assert catalog.primary(k['Outer.read'],'file')=='src/pkg/engine.py'
    assert catalog.primary(k['Outer.read'],'module')=='src/pkg/engine.py'
    assert catalog.primary(k['Outer.read'],'symbol')==k['Outer.read']


def test_catalog_rejects_changed_source_before_proposing_pieces(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    root,owners,_=source_owners;(root/'src/pkg/engine.py').write_text('changed\n')
    with pytest.raises(ValueError,match='stale'):
        SourceCatalog(root,owners)


def test_catalog_refuses_source_outside_project_root(tmp_path):
    from ken.retrieval.piece_catalog import SourceCatalog
    root=tmp_path/'project';root.mkdir();outside=tmp_path/'outside.py';outside.write_text('secret = 1\n')
    key=EntityKey('../outside.py','constant','secret')
    p=Passage(key,Span(1,1),{},hashlib.sha256(outside.read_bytes()).hexdigest(),Span(1,1))
    with pytest.raises(ValueError,match='outside'):
        SourceCatalog(root,{key:[p]})
