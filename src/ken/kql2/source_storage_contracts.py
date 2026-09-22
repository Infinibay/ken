"""Closed source inventories for declarations and callable-local binding writes."""
import json


def evaluate(semantics, bindings, role, property_name, expected):
    """Return True/False or None when the relevant source inventory is not closed."""
    subject = bindings[role]
    if property_name == 'initial':
        statuses = semantics.facts('FIELD_INITIAL_STATUS',subject)
        if not statuses or any(f.object != 'supported' for f in statuses):
            return None
        values = semantics.facts('FIELD_INITIAL_VALUE',subject)
        if len(values) != 1:
            return None
        expected_value = json.loads(expected.value)
        if expected_value is None:
            return values[0].object == 'NULL'
        return None
    if property_name == 'writes':
        binding = bindings['$'+expected.args[0].args[0].value]
        count = int(expected.args[1].args[0].value)
        statuses = semantics.facts('BINDING_WRITE_STATUS',subject)
        if statuses and all(f.object == 'supported' for f in statuses):
            counts = [f for f in semantics.facts('BINDING_WRITE_COUNT',subject)
                      if f.object == binding]
            if len(counts) != 1:
                return None
            return counts[0].attrs.get('count') == count
        # The callable-level inventory stays open when the *target* of a write is itself
        # an access (``pool[key] = local``), which is the shape an interning method
        # writes. The binding's own storage contract still closes that count, and that
        # count is exactly what the legacy ``STORAGE_WRITE_COUNT(local, n)`` clause read.
        storage = semantics.facts('STORAGE_WRITE_STATUS',binding)
        if not storage or any(f.object != 'supported' for f in storage):
            return None
        counts = semantics.facts('STORAGE_WRITE_COUNT',binding)
        if len(counts) != 1:
            return None
        value = counts[0].attrs.get('count', counts[0].object)
        try:
            return int(value) == count
        except (TypeError, ValueError):
            return None
    raise ValueError(property_name)
