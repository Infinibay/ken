import pytest


def test_exported_numeric_ranker_preserves_trained_scores_without_double_shrinkage():
    import numpy as np
    from ken.bench.numeric_export import export_numeric_ranker

    dump = {'num_class': 1, 'average_output': False, 'feature_names': ['Column_0'],
            'tree_info': [{'shrinkage': .1, 'tree_structure': {
                'split_feature': 0, 'threshold': .5, 'decision_type': '<=', 'missing_type': 'NaN',
                'left_child': {'leaf_value': -.25}, 'right_child': {'leaf_value': .75}}}]}
    ranker = export_numeric_ranker(dump, features=['coverage'])
    assert ranker.predict(np.array([[0.], [1.]])).tolist() == [-.25, .75]


@pytest.mark.parametrize('extra', [
    {'decision_type': '=='}, {'missing_type': 'Zero'},
])
def test_export_refuses_split_semantics_the_runtime_cannot_preserve(extra):
    from ken.bench.numeric_export import export_numeric_ranker

    split = {'split_feature': 0, 'threshold': .5, 'decision_type': '<=', 'missing_type': 'None',
             'left_child': {'leaf_value': 0.}, 'right_child': {'leaf_value': 1.}, **extra}
    dump = {'num_class': 1, 'average_output': False, 'feature_names': ['Column_0'],
            'tree_info': [{'tree_structure': split}]}
    with pytest.raises(ValueError, match='split'):
        export_numeric_ranker(dump, features=['coverage'])
