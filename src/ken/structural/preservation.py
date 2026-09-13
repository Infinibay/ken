"""Interval checks on instruction IR; explicit writes and unknown effects differ."""
from dataclasses import dataclass, field

from .instructions import Function, Region


@dataclass
class Preservation:
    status: str
    basis: str
    witnesses: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def preserve_binding(function: Function, place: str, *, after: str, through: str,
                     mode: str = 'strict') -> Preservation:
    """Check (after, through] in one ordered region; never guess across branches.

    explicit-writes is a source inventory, not a proof against hidden effects.
    strict additionally requires the interval's effects to be known.
    """
    if mode not in {'strict', 'explicit-writes'}:
        raise ValueError('invalid preservation mode')
    if place not in function.places:
        raise ValueError('unknown protected place')
    regions: list[Region] = [function.body]
    locations = {}
    for region in regions:
        for position, instruction in enumerate(region.instructions):
            locations[instruction.id] = (region, position)
            regions.extend(instruction.regions)
    if after not in locations or through not in locations:
        raise ValueError('unknown interval boundary')
    first, start = locations[after]
    last, end = locations[through]
    basis = 'instruction-effects' if mode == 'strict' else 'explicit-binding-writes'
    if first is not last or end <= start:
        return Preservation('unknown', basis, reasons=['interval-is-not-one-forward-region'])
    unknown: list[str] = []
    for instruction in first.instructions[start + 1:end + 1]:
        if instruction.opcode in {'return','throw','break','continue'} and instruction.id != through:
            return Preservation('unknown', basis, [instruction.id], ['interval-crosses-control-exit'])
        if instruction.regions or instruction.opcode == 'native':
            return Preservation('unknown', basis, [instruction.id], ['unmodeled-control'])
        if instruction.opcode == 'slot.store' and instruction.operands[0].ref == place:
            if unknown:
                return Preservation('unknown', basis, sorted(set(unknown)), ['preceding-unknown-effects'])
            return Preservation('violated', basis, [instruction.id], ['binding-written'])
        if instruction.opcode == 'slot.declare' and instruction.operands[0].ref == place:
            unknown.append(instruction.id)
        if mode == 'strict' and ('unknown' in instruction.effects or 'suspend' in instruction.effects):
            unknown.append(instruction.id)
    if unknown:
        return Preservation('unknown', basis, sorted(set(unknown)), ['unmodeled-effect-or-control'])
    return Preservation('preserved', basis)
