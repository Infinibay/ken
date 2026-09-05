"""Ranking upgrades preserve the user's index, model and historical records."""

from ken.db import init_schema
from ken.embedder import vec_to_blob
from ken.ranker import rank
from ken.ranker.channels import predictive_scores, similar_past_sessions


def test_legacy_inline_database_upgrades_without_rewriting_user_data(
    conn, make_file, make_symbol, make_session, make_prompt, fake_emb
):
    # Model the pre-mmap layout, before the existing additive migrations.
    for table in ("ci_files", "ci_symbols", "ci_intent_sources"):
        conn.execute(f"ALTER TABLE {table} DROP COLUMN vec_slot")
    conn.execute("ALTER TABLE ci_imports DROP COLUMN resolution")
    fid = make_file("src/auth.py", days_old=30)
    make_symbol(fid, name="authenticate")
    sess = make_session("legacy")
    make_prompt(sess, "fix auth")
    conn.execute("INSERT INTO meta(key,value) VALUES ('embed_model','existing-custom-model')")
    conn.execute("INSERT INTO meta(key,value) VALUES ('embed_probe_vec','preserve-this-probe')")
    conn.execute(
        "INSERT INTO cr_session_scores(session_id,target_kind,target_path,score,pattern,created_at) "
        "VALUES (?, 'file', 'src/auth.py', 0.2, 'neutral', 0)", (sess,),
    )
    conn.execute(
        "INSERT INTO cr_findings(topic,content,tags,embedding,created_at,updated_at) "
        "VALUES ('important', 'do not lose this', '[]', ?, 1, 1)", (vec_to_blob(fake_emb("note")),),
    )
    preserved = ["meta", "cr_sessions", "cr_contexts", "cr_interactions", "cr_session_scores", "cr_findings"]
    before = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in preserved}
    file_before = tuple(conn.execute("SELECT id,path,content_hash,embedding FROM ci_files").fetchone())
    symbol_before = tuple(conn.execute("SELECT id,file_id,name,embedding FROM ci_symbols").fetchone())
    init_schema(conn)
    init_schema(conn)
    assert {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in preserved} == before
    assert tuple(conn.execute("SELECT id,path,content_hash,embedding FROM ci_files").fetchone()) == file_before
    assert tuple(conn.execute("SELECT id,file_id,name,embedding FROM ci_symbols").fetchone()) == symbol_before
    assert conn.execute("SELECT vec_slot FROM ci_files").fetchone()[0] is None
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert list(conn.execute("PRAGMA foreign_key_check")) == []

    # A rank reads old vectors and snapshots without implicit migration/writes.
    conn.execute("PRAGMA query_only = ON")
    matches = similar_past_sessions(conn, fake_emb("fix auth"))
    assert [it.target for it in predictive_scores(conn, matches)] == ["src/auth.py"]
    result = rank(conn, agent_id="new", current_iteration=0,
                  prompt="src/auth.py", prompt_embedding=fake_emb("fix auth"))
    assert result.files[0].target == "src/auth.py"
