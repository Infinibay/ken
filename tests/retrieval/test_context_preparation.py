from dataclasses import replace
import numpy as np
import pytest
from tests.test_context_encoder import contextual_model
from tests.retrieval.test_piece_catalog import source_owners


def test_source_preparation_uses_real_model_and_reuses_verified_vectors(contextual_model,source_owners,tmp_path):
    from ken.embedder.contextual_onnx import ContextModel,ContextEncoder
    from ken.model_assets import ModelAssets
    from ken.retrieval.context_preparation import prepare_context,ContextVectorCache
    from ken.retrieval.piece_catalog import SourceCatalog
    root,owners,_=source_owners;modelroot,record=contextual_model
    model=ContextModel(ModelAssets.from_dict(record),'find ','full-source-test')
    encoder=ContextEncoder(model,snapshot=modelroot)
    catalog=SourceCatalog(root,owners);cache=tmp_path/'cache'
    prepared=prepare_context(catalog,7,encoder,cache)
    assert set(prepared.vectors.owners)==set(owners)
    assert prepared.vectors.generation==7
    assert prepared.source_views.generation==7
    assert prepared.source_views.model!=encoder.spec
    assert isinstance(prepared.source_views.matrix,np.memmap)
    assert np.allclose(np.linalg.norm(prepared.vectors.matrix,axis=1),1)
    assert prepared.source_views.matrix.flags.writeable is False
    # A fresh encoder cannot load the removed artifact. Reuse needs no session.
    (modelroot/'onnx/model.onnx').unlink()
    cached=prepare_context(catalog,8,ContextEncoder(model,snapshot=modelroot),cache)
    assert cached.vectors.generation==8
    np.testing.assert_array_equal(cached.vectors.matrix,prepared.vectors.matrix)
    assert cached.source_views.rows.keys()=={'contract','implementation'}
    with ContextVectorCache(cache,encoder.spec) as store:
        assert store.count()>0


def test_corrupt_published_context_is_rejected_before_use(contextual_model,source_owners,tmp_path):
    from ken.embedder.contextual_onnx import ContextModel,ContextEncoder
    from ken.model_assets import ModelAssets
    from ken.retrieval.context_preparation import prepare_context
    from ken.retrieval.piece_catalog import SourceCatalog
    root,owners,_=source_owners;modelroot,record=contextual_model
    encoder=ContextEncoder(ContextModel(ModelAssets.from_dict(record),'find ','test'),snapshot=modelroot)
    cache=tmp_path/'cache';catalog=SourceCatalog(root,owners)
    prepare_context(catalog,7,encoder,cache)
    artifact=next(cache.glob('snapshots/*/views.npy'))
    artifact.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='context artifact'):
        prepare_context(catalog,7,encoder,cache)
