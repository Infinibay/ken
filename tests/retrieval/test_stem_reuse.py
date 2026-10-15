from concurrent.futures import ThreadPoolExecutor
import importlib
import snowballstemmer


def test_word_stems_match_fresh_batch_results_including_unicode_and_order():
    from ken.retrieval.owner_ranking import EvidenceReranker
    words = ['running', 'cats', 'running', '', 'CAFÉ', 'café', 'relational', 'HTTPServer', '字词', 'x'*129]
    expected = snowballstemmer.stemmer('english').stemWords(words)
    assert EvidenceReranker.stem_words(words) == expected


def test_stem_reuse_is_bounded_and_does_not_share_mutable_buffers(monkeypatch):
    import ken.retrieval.owner_ranking as module
    module._stem_word.cache_clear()
    original = importlib.import_module
    stems = []
    library = original('snowballstemmer')
    class Counted:
        @staticmethod
        def stemmer(language):
            stemmer = library.stemmer(language)
            class Instance:
                @staticmethod
                def stemWords(words):
                    stems.extend(words)
                    return stemmer.stemWords(words)
            return Instance()
    def counted(name):
        if name != 'snowballstemmer':
            return original(name)
        return Counted()
    monkeypatch.setattr(module, 'import_module', counted)
    first = module.EvidenceReranker.stem_words(['running', 'running', 'cats'])
    first[0] = 'mutated'
    assert module.EvidenceReranker.stem_words(['running', 'cats']) == ['run', 'cat']
    assert stems == ['running', 'cats']
    assert module._stem_word.cache_info().maxsize == 32768


def test_large_words_bypass_the_retained_stem_cache():
    import ken.retrieval.owner_ranking as module
    module._stem_word.cache_clear()
    word = 'z'*129
    assert module.EvidenceReranker.stem_words([word]) == snowballstemmer.stemmer('english').stemWords([word])
    assert module._stem_word.cache_info().currsize == 0


def test_concurrent_stemming_uses_independent_mutable_stemmer_state():
    from ken.retrieval.owner_ranking import EvidenceReranker
    groups = [['running', 'relational', str(i)+'berries', 'café', 'hopefulness'] for i in range(200)]
    expected = [snowballstemmer.stemmer('english').stemWords(words) for words in groups]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(EvidenceReranker.stem_words, groups)) == expected


def test_replacing_the_stemmer_factory_cannot_reuse_another_implementations_cache(monkeypatch):
    from types import SimpleNamespace
    import ken.retrieval.owner_ranking as module
    module._stem_word.cache_clear()
    words = ['transformationprobe']
    original = module.EvidenceReranker.stem_words(words)
    replacement = SimpleNamespace(stemmer=lambda language: SimpleNamespace(
        stemWords=lambda values: ['replacement:'+value for value in values],
        stemWord=lambda value: 'replacement:'+value))
    with monkeypatch.context() as context:
        context.setattr(module, 'import_module', lambda name: replacement)
        assert module.EvidenceReranker.stem_words(words) == ['replacement:transformationprobe']
    assert module.EvidenceReranker.stem_words(words) == original
