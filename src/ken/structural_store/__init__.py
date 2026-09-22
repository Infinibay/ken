"""Dedicated, versioned KQL 2 structural storage."""
from .store import Node, Store
from .migrations import StoreFormatError

__all__ = ["Node", "Store", "StoreFormatError"]
