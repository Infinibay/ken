"""Snapshot-derived resources shared by a batch of independent queries."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from .model import FactIndex

if TYPE_CHECKING:
    from ken.kql2.source_execution import SourceView


class ExecutionResources:
    """Share indexes, never bindings, evidence, match caches or budget state.

    Lifetime is explicit: the caller owns one resource set for one FactIndex.
    Lazy construction also avoids building BODY views for cached/graph-only rules.
    """

    def __init__(self, index: FactIndex):
        self.index = index

    @cached_property
    def source_view(self) -> SourceView:
        from ken.kql2.source_execution import SourceView

        factory = getattr(self.index, 'source_view', None)
        return factory() if factory is not None else SourceView(self.index)

    @cached_property
    def body_units(self):
        from ken.kql2.cache import ArtifactCache

        return ArtifactCache(8_000_000)

    @cached_property
    def body_contexts(self):
        from ken.kql2.cache import ArtifactCache

        return ArtifactCache(8_000_000)

    @cached_property
    def property_postings(self):
        from ken.kql2.cache import ArtifactCache

        return ArtifactCache(4_000_000)
