from ken.retrieval.model import CodeMatch
from tests.retrieval.test_piece_catalog import source_owners


def test_requested_pieces_keep_native_order_and_all_lexical_members(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_candidates import assemble_pieces
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners)
    keys=[k['Outer.Inner.run'],k['Outer.read'],k['helper'],k['Outer']]
    matches=[CodeMatch(key,4-i,list(owners[key]),owners[key][0].source_hash) for i,key in enumerate(keys)]
    cache={}
    pieces=assemble_pieces(matches,'class',catalog,cache)
    assert [p.entity.qualname for p in pieces]==['Outer.Inner','Outer']
    assert {m.entity.qualname for m in pieces[0].members}=={'Outer.Inner','Outer.Inner.run'}
    assert {m.entity.qualname for m in pieces[1].members}=={'Outer','Outer.Inner','Outer.read'}
    assert [m.entity.qualname for m in pieces[1].matches]==['Outer.read','Outer']
    assert pieces[1].declaration.entity==k['Outer']
    previous=pieces[1].members[0]
    assert assemble_pieces(matches,'class',catalog,cache)[1].members[0] is previous
    assert len(assemble_pieces(matches,'class',catalog,cache,limit=1))==1


def test_file_module_and_symbol_units_have_their_own_identity(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_candidates import assemble_pieces
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners)
    keys=[k['helper'],k['Outer.Inner.run']]
    matches=[CodeMatch(key,2-i,list(owners[key]),owners[key][0].source_hash) for i,key in enumerate(keys)]
    for kind in ('file','module'):
        pieces=assemble_pieces(matches,kind,catalog,{})
        assert len(pieces)==1 and pieces[0].entity is None
        assert {m.entity for m in pieces[0].members}==set(owners)
        assert pieces[0].matches==tuple(matches)
    pieces=assemble_pieces(matches,'symbol',catalog,{})
    assert [p.entity for p in pieces]==keys
    assert all(len(p.members)==1 for p in pieces)


def test_cpp_constructors_and_destructors_compete_as_native_symbol_pieces(tmp_path):
    from collections import defaultdict
    from ken.parsers.cpp import parse_cpp_file
    from ken.retrieval.passages import extract_passages
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_candidates import assemble_pieces
    source = b"class Reader {\npublic:\n  Reader() {}\n  ~Reader() {}\n  int read() { return 1; }\n};\n"
    path = "reader.hpp"
    (tmp_path / path).write_bytes(source)
    owners = defaultdict(list)
    for passage in extract_passages(source, parse_cpp_file(source, path), path=path, language="cpp"):
        owners[passage.entity].append(passage)
    catalog = SourceCatalog(tmp_path, owners)
    keys = [key for key in owners if key.kind in {"constructor", "destructor", "method"}]
    matches = [CodeMatch(key, 3-i, owners[key], owners[key][0].source_hash) for i, key in enumerate(keys)]
    pieces = assemble_pieces(matches, "symbol", catalog, {})
    assert {piece.entity.kind for piece in pieces} == {"constructor", "destructor", "method"}
    assert [piece.entity for piece in pieces] == keys
