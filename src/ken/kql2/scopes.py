"""Give existential witnesses private identities before relational lowering."""

from dataclasses import replace

from .syntax import Clause, Expr, SourceExpr


def private_witnesses(
    clauses: tuple[Clause, ...], bound: set[str], scope: int
) -> tuple[Clause, ...]:
    """Correlate incoming roles; prevent later aliases from capturing witnesses."""

    def role(name: str) -> str:
        return name if not name or name in bound else f"@scope{scope}:{name}"

    def expression(value: Expr | SourceExpr):
        return replace(
            value,
            value=role(value.value) if value.kind in {"role", "from"} else value.value,
            args=tuple(expression(arg) for arg in value.args),
        )

    def block(items):
        return tuple(
            replace(
                item,
                role=role(item.role),
                alias=role(item.alias),
                name=role(item.name) if item.kind == "source_usages" else item.name,
                expressions=tuple(expression(expr) for expr in item.expressions),
                blocks=tuple(block(child) for child in item.blocks),
            )
            for item in items
        )

    return block(clauses)
