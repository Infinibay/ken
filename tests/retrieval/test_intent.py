from ken.retrieval.model import SearchRequest


def test_explicit_identity_instruction_is_distinct_from_behavior():
    from ken.retrieval.intent import interpret
    for query in ("Show the Version class declaration.", "Mostrame la definición de la clase Marker.",
                  "Find the padStart utility definition."):
        assert interpret(SearchRequest(query)).identity
    assert not interpret(SearchRequest("Where are version strings normalized?")).identity


def test_tests_are_selected_only_from_explicit_query_or_public_purpose():
    from ken.retrieval.intent import interpret
    assert interpret(SearchRequest("¿Qué prueba comprueba valores vacíos?")).purpose == "tests"
    assert interpret(SearchRequest("Which test checks invalid dates?")).purpose == "tests"
    assert interpret(SearchRequest("Where does validation test the input type?")).purpose == "implementation"
    assert interpret(SearchRequest("clear authorization", purpose="tests")).purpose == "tests"


def test_natural_identity_lookup_needs_no_dense_index(tmp_path):
    from ken.retrieval.service import search
    from tests.retrieval.test_candidates import indexed
    with indexed(tmp_path) as conn:
        response = search(conn, tmp_path, SearchRequest("Show the persist_state function definition."))
    assert response.results[0]["entity"]["qualname"] == "persist_state"
