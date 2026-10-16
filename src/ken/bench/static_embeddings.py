"""Backward-compatible experimental name for the production static encoder."""
from ken.embedder.model2vec_backend import RegisteredStaticEncoder as StaticEmbeddingControl

__all__ = ["StaticEmbeddingControl"]
