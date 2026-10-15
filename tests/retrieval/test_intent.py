import pytest

from ken.retrieval.intent import interpret
from ken.retrieval.model import SearchRequest


def test_explicit_identity_instruction_is_distinct_from_behavior():
    for query in ("Show the Version class declaration.", "Mostrame la definición de la clase Marker.",
                  "Find the padStart utility definition."):
        assert interpret(SearchRequest(query)).identity
    assert not interpret(SearchRequest("Where are version strings normalized?")).identity


def test_tests_are_selected_only_from_explicit_query_or_public_purpose():
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


@pytest.mark.parametrize("query", ["Find the test preserving trailing zeros.",
    "Show a unit test for redirects.", "Locate tests covering invalid dates.",
    "Buscá la prueba de credenciales.", "Encuentra el test que cubre fechas inválidas."])
def test_explicit_test_requests_are_interpreted_in_both_languages(query):
    assert interpret(SearchRequest(query)).purpose == "tests"


def test_behavior_mentioning_a_test_does_not_automatically_request_test_source():
    assert interpret(SearchRequest("Where does the runner test the exit status?")).purpose == "implementation"
    assert interpret(SearchRequest("Which test covers dates?", purpose="implementation")).purpose == "implementation"


@pytest.mark.parametrize("query", ["Where is `Client.redirect` defined?",
    "¿Dónde está definido `Client.redirect`?", "¿Qué archivo fuente declara `Client.redirect`?",
    "Where is Client.redirect declared?"])
def test_qualified_identity_in_natural_definition_requests(query):
    intent = interpret(SearchRequest(query))
    assert intent.identity
    assert intent.identifiers == ("Client.redirect",)


def test_quoted_name_in_a_usage_question_does_not_force_definition_lookup():
    assert not interpret(SearchRequest("Where is `Client.redirect` called?")).identity


@pytest.mark.parametrize('query', [
    'Find the function that tests whether a request is valid.',
    'Show the class responsible for matching redirects.',
    'Locate the helper that raises Error after invalid input.',
    'Buscá la función que convierte nombres y evita colisiones.',
])
def test_descriptive_requests_do_not_treat_prose_words_as_exact_symbol_names(query):
    intent = interpret(SearchRequest(query))
    assert not intent.identity
    assert intent.identifiers == ()


@pytest.mark.parametrize('query', [
    'Show the definition of function normalize_names.',
    'Show the normalize_names function.',
    '¿Dónde está definida la función normalize_names?',
])
def test_single_named_definition_request_preserves_exact_authority(query):
    intent = interpret(SearchRequest(query))
    assert intent.identity
    assert intent.identifiers == ('normalize_names',)


@pytest.mark.parametrize('query,name,kind', [
    ('Show the Payload struct declaration.', 'Payload', 'struct'),
    ('Find the GridBuffer workspace type declaration.', 'GridBuffer', None),
    ('Show the Descriptor metadata class declaration.', 'Descriptor', 'class'),
    ('Mostrame la definición del struct Cursor.', 'Cursor', 'struct'),
    ('Mostrame la declaración del iterador EntryStream.', 'EntryStream', None),
    ('Find the CaptureSet struct declaration for string matches.', 'CaptureSet', 'struct'),
])
def test_explicit_named_declarations_allow_kind_and_descriptive_modifiers(query,name,kind):
    intent = interpret(SearchRequest(query))
    assert intent.identity
    assert intent.identifiers == (name,)
    assert intent.kind == kind


def test_multiple_named_declarations_do_not_gain_single_target_authority():
    assert not interpret(SearchRequest('Show the Node class declaration and Edge class declaration.')).identity


@pytest.mark.parametrize('query', [
    'Find the authentication timeout test covering exhausted retries.',
    'Show a parameterized integration test for malformed responses.',
    'Locate the command-line quoting test.',
    'What integration test covers an empty response?',
    'Buscá el test de integración que cubre respuestas vacías.',
])
def test_requested_test_noun_can_have_descriptive_modifiers(query):
    assert interpret(SearchRequest(query)).purpose == 'tests'


@pytest.mark.parametrize('query', [
    'Find the function that tests whether a request is valid.',
    'Show the handler used in test environments.',
    'Locate the class responsible for test discovery.',
    'Which function tests a connection?',
    'Find a way to test input values.',
])
def test_modifier_recognition_does_not_turn_test_mentions_into_test_requests(query):
    assert interpret(SearchRequest(query)).purpose == 'implementation'
