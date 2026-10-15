import pytest
from query_actions import extract_actions


def test_actions_keep_original_order_and_inflection_without_topic_nouns():
    tokens=['Where','are','values','sorted','before','returning','items','?']
    tags=['WRB','VBP','NNS','VBN','IN','VBG','NNS','.']
    result=extract_actions('input',tokenize=lambda _:tokens,tag=lambda ws:list(zip(ws,tags)))
    assert result.actions==('sorted','returning') and result.tokens==tuple(tokens)
    tokens[3]='changed'
    assert result.actions==('sorted','returning') and result.tokens[3]=='sorted'


def test_auxiliaries_are_case_insensitive_and_repeated_actions_are_preserved():
    tokens=['Has','run','and','run']
    result=extract_actions('input',tokenize=lambda _:tokens,tag=lambda ws:list(zip(ws,['VBZ','VBN','CC','VB'])))
    assert result.actions==('run','run')


def test_no_verb_is_not_guessed_from_nouns_or_adjectives():
    result=extract_actions('input',tokenize=lambda _:['sorted','list'],tag=lambda ws:[('sorted','JJ'),('list','NN')])
    assert result.actions==()


@pytest.mark.parametrize('tagged', [[('other','VB')],[],[('run','')],[('run',None)]])
def test_misaligned_or_invalid_tagger_output_is_explicit_failure(tagged):
    with pytest.raises(ValueError):extract_actions('input',tokenize=lambda _:['run'],tag=lambda _:tagged)
