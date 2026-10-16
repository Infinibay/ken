from pathlib import Path
from ken.retrieval.model import SearchRequest
from tests.retrieval.test_candidates import indexed


def test_exact_class_and_callable_need_no_models_or_retrieval_vectors(tmp_path):
    from ken.indexer import index_files
    from ken.retrieval.best_search import search_best
    with indexed(tmp_path) as conn:
        (tmp_path/'classy.py').write_text('class Reader:\n    def read(self):\n        return 1\n')
        index_files(conn,tmp_path,[Path('classy.py')])
        result=search_best(conn,tmp_path,SearchRequest('Reader')).results[0]
        assert result['piece_kind']=='class' and result['entity']['qualname']=='Reader'
        function=search_best(conn,tmp_path,SearchRequest('persist_state')).results[0]
        assert function['piece_kind']=='symbol' and function['entity']['qualname']=='persist_state'
        file=search_best(conn,tmp_path,SearchRequest('Reader',target='file')).results[0]
        assert file['piece_kind']=='file' and file['entity']['kind']=='file'
        # These calls run without shipped numeric models or downloaded HF assets.
        assert conn.execute('SELECT COUNT(*) FROM ci_passage_vectors').fetchone()[0]==0


def test_empty_source_returns_no_matches_without_loading_assets(tmp_path):
    from ken.db import connect,init_schema
    from ken.retrieval.best_search import search_best
    conn=connect(tmp_path/'empty.db');init_schema(conn)
    try:
        response=search_best(conn,tmp_path,SearchRequest('find the implementation'))
        assert response.results==[]
    finally:
        conn.close()
