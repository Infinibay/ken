"""Score evidence must retain margins, stable ties and candidate row identity."""
import numpy as np
import pytest
import score_calibration as calibration
from ken.retrieval.piece_ranking import PIECE_FEATURES

def packet():
    x=np.zeros((3,len(PIECE_FEATURES)))
    x[:,PIECE_FEATURES.index('native_score')]=[5.,4.9,-2.]
    x[:,PIECE_FEATURES.index('request_symbol')]=1.
    x[1,PIECE_FEATURES.index('test_path')]=1.
    return x

def build(x=None,order=(0,2,1),piece=(1.,.5,-1.),neural=(.1,8.,9.),exact=(0.,0.,0.)):
    return calibration.calibration_features(packet() if x is None else x,piece_order=order,piece_scores=piece,neural_scores=neural,exact=exact)

def test_preserves_raw_margins_in_native_candidate_coordinates():
    result=build()
    d=lambda n:result[:,calibration.CALIBRATION_FEATURES.index(n)]
    np.testing.assert_array_equal(d('neural_raw'),[.1,9.,8.])
    np.testing.assert_allclose(d('neural_to_max'),[-8.9,0.,-1.])
    np.testing.assert_allclose(d('piece_raw'),[1.,-1.,.5])
    np.testing.assert_allclose(d('native_to_max'),[0.,-.1,-7.])
    np.testing.assert_allclose(d('neural_reciprocal_rank'),[1/3,1.,.5])
    np.testing.assert_array_equal(d('request_symbol'),[1.,1.,1.])
    np.testing.assert_array_equal(d('test_path'),[0.,1.,0.])

def test_tied_neural_scores_retain_actual_piece_order():
    result=build(order=(2,0,1),neural=(2.,2.,2.))
    d=lambda n:result[:,calibration.CALIBRATION_FEATURES.index(n)]
    np.testing.assert_allclose(d('neural_reciprocal_rank'),[.5,1/3,1.])
    np.testing.assert_array_equal(d('neural_z'),[0.,0.,0.])
    assert np.isfinite(result).all()

def test_empty_pool_has_fixed_schema():
    result=calibration.calibration_features(np.empty((0,len(PIECE_FEATURES))),piece_order=(),piece_scores=(),neural_scores=(),exact=())
    assert result.shape==(0,len(calibration.CALIBRATION_FEATURES))

@pytest.mark.parametrize('kwargs',[
    {'order':(0,0,2)}, {'piece':(1.,2.)}, {'neural':(0.,float('nan'),1.)},
    {'exact':(0.,1.,2.)}, {'x':np.zeros((3,1))}, {'x':np.full((3,len(PIECE_FEATURES)),float('inf'))}])
def test_rejects_invalid_or_misaligned_evidence(kwargs):
    with pytest.raises(ValueError):build(**kwargs)

def test_full_schema_keeps_source_evidence_and_compact_schema_identical():
    x=packet();low=build(x=x)
    full=calibration.calibration_features(x,piece_order=(0,2,1),piece_scores=(1.,.5,-1.),neural_scores=(.1,8.,9.),exact=(0.,0.,0.),include_source=True)
    np.testing.assert_array_equal(full[:,:len(PIECE_FEATURES)],x)
    np.testing.assert_array_equal(full[:,len(PIECE_FEATURES):],low)
    assert len(set(calibration.FULL_FEATURES))==len(calibration.FULL_FEATURES)
