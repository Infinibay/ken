import numpy as np
import pytest


def test_shared_file_topic_leaves_opposite_owner_details_distinguishable():
    from file_contrast import FileContrast

    context = FileContrast(['same.py', 'same.py', 'alone.py'],
                           np.array([[1., 0.], [0., 1.], [-1., 0.]]))
    values = context.score(np.array([1., 0.]), [0, 1, 2])
    np.testing.assert_allclose(values[:2], [[1., 1.], [-1., -1.]], atol=1e-12)
    np.testing.assert_array_equal(values[2], [0., 0.])
    assert context.commonness([0, 1, 2]).shape == (3, 5)


def test_formulas_match_direct_centering_and_projection_for_random_files():
    from file_contrast import FileContrast

    rng = np.random.default_rng(71)
    vectors = rng.normal(size=(40, 7))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    paths = [f'file{i//4}.py' for i in range(40)]
    query = rng.normal(size=7)
    query /= np.linalg.norm(query)
    context = FileContrast(paths, vectors)
    expected = []
    for i, vector in enumerate(vectors):
        mean = vectors[np.array(paths) == paths[i]].mean(axis=0)
        topic = mean/np.linalg.norm(mean)
        a, b = query-mean, vector-mean
        c, d = query-(query@topic)*topic, vector-(vector@topic)*topic
        expected.append([a@b/(np.linalg.norm(a)*np.linalg.norm(b)),
                         c@d/(np.linalg.norm(c)*np.linalg.norm(d))])
    np.testing.assert_allclose(context.score(query, list(range(40))), expected, atol=1e-12)


def test_zero_background_and_identical_source_vectors_never_create_nan_evidence():
    from file_contrast import FileContrast

    context = FileContrast(['symmetric', 'symmetric', 'identical', 'identical'],
                           np.array([[1., 0.], [-1., 0.], [0., 1.], [0., 1.]]))
    values = context.score(np.array([1., 0.]), [0, 1, 2, 3])
    np.testing.assert_allclose(values[:, 0], [1., -1., 0., 0.], atol=1e-12)
    np.testing.assert_array_equal(values[:, 1], [0., 0., 0., 0.])
    assert np.isfinite(context.commonness([0, 1, 2, 3])).all()


def test_invalid_dimensions_nonunit_vectors_and_wrong_owner_rows_fail_loudly():
    from file_contrast import FileContrast

    with pytest.raises(ValueError):
        FileContrast(['one'], np.eye(2))
    with pytest.raises(ValueError):
        FileContrast(['one'], np.ones((1, 2)))
    context = FileContrast(['one', 'two'], np.eye(2))
    for query, ids in [(np.ones(3), [0]), (np.array([np.nan, 0.]), [0]),
                       (np.array([1., 0.]), [-1]), (np.array([1., 0.]), [2])]:
        with pytest.raises(ValueError):
            context.score(query, ids)


def test_identical_arbitrary_directions_do_not_invent_information_from_roundoff():
    from file_contrast import FileContrast

    rng = np.random.default_rng(71)
    for _ in range(20):
        vector = rng.normal(size=64)
        vector /= np.linalg.norm(vector)
        context = FileContrast(['same']*3, np.tile(vector, (3, 1)))
        query = rng.normal(size=64)
        query /= np.linalg.norm(query)
        np.testing.assert_array_equal(context.score(query, [0, 1, 2]), np.zeros((3, 2)))
