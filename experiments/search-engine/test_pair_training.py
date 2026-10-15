import numpy as np
import pytest


def inputs():
    return dict(qids=np.array(['train']*6+['held']*2),
        repos=np.array(['r1']*6+['r2']*2), labels=np.array([0, 1, 0, 0, 0, 0, 1, 0]),
        indexes=np.array([0, 1, 2, 3, 4, 5, 0, 1]),
        pair_scores=np.array([0., 10., 3., 4., 5., 6., 8., 9.]))


def test_training_groups_exclude_the_entire_held_repository_and_keep_source_row_ids():
    from pair_training import training_groups

    groups = training_groups(**inputs(), held_out='r2')
    assert len(groups) == 1
    assert groups[0].qid == 'train' and groups[0].repo == 'r1'
    assert groups[0].positive == 1
    assert groups[0].negatives == (0, 5, 4, 3)


def test_changing_held_labels_and_scores_cannot_change_training_selection():
    from pair_training import training_groups

    values = inputs()
    expected = training_groups(**values, held_out='r2')
    values['labels'][-2:] = [0, 1]
    values['pair_scores'][-2:] = [-500., 500.]
    assert training_groups(**values, held_out='r2') == expected


def test_exact_or_source_ineligible_requests_are_skipped_only_in_training():
    from pair_training import training_groups

    assert not training_groups(**inputs(), held_out='r2', exact_ids={'train'})
    values = inputs()
    values['labels'][:6] = 0
    assert not training_groups(**values, held_out='r2')


@pytest.mark.parametrize('corruption', ['positions', 'mixed_repo', 'nonfinite', 'nonbinary'])
def test_bad_row_bindings_cannot_silently_create_training_pairs(corruption):
    from pair_training import training_groups

    values = inputs()
    if corruption == 'positions':
        values['indexes'][0] = 1
    elif corruption == 'mixed_repo':
        values['repos'][0] = 'r2'
    elif corruption == 'nonfinite':
        values['pair_scores'][0] = np.nan
    else:
        values['labels'][0] = 2
    with pytest.raises(ValueError):
        training_groups(**values, held_out='r2')
