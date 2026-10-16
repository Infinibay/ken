import pytest
from ken.db import connect,init_schema


def test_persistent_search_reuses_connection_and_reads_new_commits(tmp_path):
    from ken.retrieval.connections import project_connection
    root=tmp_path/'one';(root/'.ken').mkdir(parents=True)
    path=root/'.ken/ken.db'
    with connect(path) as conn:init_schema(conn)
    with project_connection(root) as first:
        assert first.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0]==0
    with connect(path) as writer:
        writer.execute("INSERT INTO meta VALUES ('new-value','visible')")
    with project_connection(root) as again:
        assert again is first
        assert again.execute("SELECT value FROM meta WHERE key='new-value'").fetchone()[0]=='visible'
