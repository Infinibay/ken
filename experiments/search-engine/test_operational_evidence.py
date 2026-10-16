import numpy as np

def test_critical_references_keep_code_operators_and_names_not_prose_capitals():
    from operational_evidence import critical_references,reference_coverage
    refs=critical_references('Which helper builds AND nodes and raises ValueError?')
    assert set(refs)=={'AND','ValueError'}
    assert reference_coverage(refs,'return ast.And()','',qualname='and_expr')[0]==.5
    assert reference_coverage(['AND'],'return and_expr(scanner)','',qualname='expr')[0]==0.


def test_qualified_code_reference_matches_the_canonical_entity_name():
    from operational_evidence import critical_references,reference_coverage
    refs=critical_references('Localiza la definición de `tests.store::Reader.load_item`.')
    assert refs==['Reader.load_item']
    _,identity=reference_coverage(refs,'return value','',qualname='Reader.load_item')
    assert identity==1.


def test_test_entrypoint_is_distinct_from_a_nested_helper_in_a_test_file():
    from operational_evidence import test_entrypoint
    assert test_entrypoint('test_transform','',file_test=True,nested_callable=False)
    assert not test_entrypoint('test_inner','',file_test=True,nested_callable=True)
    assert not test_entrypoint('test_connection','',file_test=False,nested_callable=False)
    assert test_entrypoint('checksEmpty','@ParameterizedTest\nvoid checksEmpty() {',file_test=True,nested_callable=False)


def test_requested_mutation_matches_direct_effect_not_a_delegating_wrapper():
    from operational_evidence import operation_alignment
    direct=operation_alignment('Append the result and return the buffer.','buffer.append(result)\nreturn buffer','buffer.append',test_query=False)
    wrapper=operation_alignment('Append the result and return the buffer.','return helper(buffer)','helper',test_query=False)
    assert np.sum(direct)>np.sum(wrapper)


def test_literal_coverage_distinguishes_exception_type_from_a_similar_name():
    from operational_evidence import reference_coverage
    assert reference_coverage(['KeyError'],'with collector.collect(KeyError): pass','',qualname='test_case')[0]==1.
    assert reference_coverage(['KeyError'],'raise NotKeyError()','',qualname='test_case')[0]==0.
