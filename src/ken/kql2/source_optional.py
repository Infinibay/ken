"""Optional-protocol call properties (catalog-extensions.md F6)."""
from ken.structural_store import Node
from .values import Unknown

OPTIONAL_ROLES = {'wraps': 'OPTIONAL_VALUE', 'empty': 'OPTIONAL_OR',
                  'present': 'OPTIONAL_PRESENT', 'fallback': 'OPTIONAL_FALLBACK'}


def optional_row(constraint, call, current, updated, rows, value_node):
    """``wraps:/empty:/present:/fallback:`` against the Optional model's rows."""
    operand = constraint.expressions[0]
    facts = rows(OPTIONAL_ROLES[constraint.name], call.id)
    if not facts:
        return False
    if operand.kind == 'role':
        bound = current.get(operand.value)
        if isinstance(bound, Node):
            return any(f.object == bound.local_id for f in facts)
        if operand.value in current:
            return Unknown('optional_handler_unknown')
        updated[operand.value] = value_node(facts[0].object)
        return True
    text = str(operand.value).strip('"')
    return any(str(f.object).upper() == text.upper() for f in facts)
