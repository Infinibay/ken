from ken.retrieval.tokenization import code_tokens


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
