"""Authenticate archived source bytes before importing their replay implementation."""
from pathlib import Path
import hashlib,json,sys,tarfile,tempfile
sys.dont_write_bytecode=True
proof=Path(__file__).resolve().parent
index=json.loads((proof/'INDEX.json').read_bytes())
expected={**{'native-sources/'+p:v for p,v in {**index['sources'],**index['parser_sources']}.items()},**{'validation-sources/'+p:v for p,v in index['tooling'].items()}}
with tempfile.TemporaryDirectory(prefix='ken-import-snapshot-')as temporary:
    snapshot=Path(temporary)
    with tarfile.open(proof/'sources.tar.gz')as archive:
        members=archive.getmembers()
        assert len(members)==len(expected)and{m.name for m in members}==set(expected),'source archive membership differs'
        for member in members:
            assert member.isfile()and not Path(member.name).is_absolute()and'..'not in Path(member.name).parts,'unsafe source archive member'
            raw=archive.extractfile(member).read()
            assert expected[member.name]==dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()),'source archive bytes differ'
        archive.extractall(snapshot,filter='data')
    sys.path.insert(0,str(snapshot/'validation-sources'))
    from tools.rust_migration.import_evidence import aggregate_import_matrix
    result=aggregate_import_matrix(proof,Path.cwd(),snapshot=snapshot,current='--current'in sys.argv)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
