"""Syntactic body ranges, independent of control-flow exits and scope ownership."""

from dataclasses import dataclass

from .model import Program


@dataclass(frozen=True, slots=True)
class BodyRange:
    owner: int
    relation: str
    root: int
    subtree_end: int

    @property
    def final_node(self) -> int:
        return self.subtree_end - 1


def body_ranges(program: Program):
    """Keep each branch separate; roots include empty blocks and expression bodies."""
    roots = set()
    for node in program.nodes:
        if node.parent is not None and node.role in (
            "body",
            "then",
            "else",
            "handler",
            "finalizer",
        ):
            roots.add(
                (node.parent, "body" if node.role == "then" else node.role, node.id)
            )
    for link in program.links:
        if link.relation in ("body", "else"):
            roots.add((link.source, link.relation, link.target))
    explicit = {owner for owner, relation, _ in roots if relation == "body"}
    for node in program.nodes:
        if node.kind in ("module", "block") and node.id not in explicit:
            roots.add((node.id, "body", node.id))
    for owner, relation, root in sorted(roots):
        yield BodyRange(owner, relation, root, program.nodes[root].subtree_end)
