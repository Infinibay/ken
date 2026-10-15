from ken.retrieval.tokenization import code_tokens
import pytest


def test_identifier_tokens_keep_order_repetitions_and_unicode_normalization():
    assert code_tokens('HTTPServer.get_status HTTPServer.get_status') == [
        'get', 'http', 'httpserver', 'httpserver.get_status', 'server', 'status',
        'get', 'http', 'httpserver', 'httpserver.get_status', 'server', 'status',
    ]
    assert code_tokens('the The THE é É _ __ parseXML2JSON') == [
        'é', 'é', '2', 'json', 'parse', 'parsexml2json', 'xm',
    ]


def test_repeated_identifiers_reuse_their_bounded_lexical_decomposition(monkeypatch):
    import ken.retrieval.tokenization as module

    calls = []
    original = module.split_camel

    def counted(word):
        calls.append(word)
        return original(word)

    monkeypatch.setattr(module, 'split_camel', counted)
    text = 'ProfileCacheUnique.read_state ' * 100
    first = code_tokens(text)
    assert code_tokens(text) == first
    assert calls == ['ProfileCacheUnique', 'read', 'state']


def test_large_identifier_is_not_retained_in_the_reuse_cache():
    import ken.retrieval.tokenization as module

    module._identifier_tokens.cache_clear()
    long_word = 'longIdentifier' * 1000
    assert code_tokens(long_word)
    assert module._identifier_tokens.cache_info().currsize == 0
    assert module._identifier_tokens.cache_info().maxsize == 16384


@pytest.mark.parametrize('limit', [None, 0, 1, 3, 128, 4096])
def test_code_terms_are_exactly_the_first_distinct_occurrence_tokens(limit):
    from ken.retrieval.tokenization import code_terms

    text = 'HTTPServer.get_status get_status café Ｃａｃｈｅ HTTPServer.get_status ' * 50
    expected = list(dict.fromkeys(code_tokens(text)))
    assert code_terms(text, limit=limit) == (expected if limit is None else expected[:limit])


def test_code_terms_skip_repeated_raw_words_before_decomposition(monkeypatch):
    import ken.retrieval.tokenization as module

    calls = []
    original = module._identifier_tokens

    def counted(raw):
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr(module, '_identifier_tokens', counted)
    assert module.code_terms('TermsProfile.first TermsProfile.first otherValue ' * 100)
    assert calls == ['TermsProfile.first', 'otherValue']


def test_code_terms_rejects_negative_limits():
    from ken.retrieval.tokenization import code_terms

    with pytest.raises(ValueError, match='nonnegative'):
        code_terms('read', limit=-1)
