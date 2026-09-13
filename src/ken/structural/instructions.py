"""Instruction IR: values, mutable places, regions, effects and source provenance."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


SCHEMA = 'ken-instructions/1'
OPCODES = frozenset({'const', 'slot.declare', 'slot.load', 'slot.store', 'field.addr', 'index.addr',
                     'memory.load', 'memory.store', 'call', 'construct', 'binary',
                     'unary', 'compare', 'if', 'loop', 'return', 'break', 'continue',
                     'throw', 'yield', 'yield.delegate', 'await', 'native',
                     'choose', 'short_circuit', 'iterate', 'iteration.value'})


@dataclass
class Operand:
    kind: str
    ref: str
    role: str = ''


@dataclass
class Instruction:
    id: str
    opcode: str
    operands: list[Operand]
    result: str | None
    source: dict[str, Any]
    effects: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
    regions: list[Region] = field(default_factory=list)
    result_type: dict[str, Any] = field(default_factory=lambda: {'kind': 'unknown', 'native': ''})


@dataclass
class Region:
    id: str
    kind: str
    instructions: list[Instruction] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class Function:
    id: str
    name: str
    language: str
    parameters: list[str]
    places: dict[str, dict[str, Any]]
    body: Region
    status: str = 'partial'
    reasons: list[str] = field(default_factory=list)


@dataclass
class Program:
    source_version: str
    functions: list[Function]
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Program:
        if data['schema'] != SCHEMA:
            raise ValueError('incompatible instruction schema')
        def region(value):
            return Region(value['id'], value['kind'], [Instruction(
                i['id'], i['opcode'], [Operand(**o) for o in i['operands']],
                i['result'], i['source'], i['effects'], i['attrs'],
                [region(r) for r in i['regions']], i['result_type']) for i in value['instructions']], value['outputs'])
        result = cls(data['source_version'], [Function(**{**f, 'body': region(f['body'])}) for f in data['functions']])
        result.verify()
        return result

    def verify(self) -> None:
        """Check structural well-formedness and region-scoped value definitions."""
        if self.schema != SCHEMA:
            raise ValueError('incompatible instruction schema')
        functions = set()
        for function in self.functions:
            if function.id in functions:
                raise ValueError('duplicate function')
            functions.add(function.id)
            if any(p not in function.places for p in function.parameters):
                raise ValueError('parameter has no place')
            ids: set[str] = set()
            definitions: set[str] = set()
            def check(region: Region, incoming: set[str], depth: int = 0, iteration_body: bool = False):
                if depth > 128 or region.id in ids:
                    raise ValueError('invalid or duplicate region')
                ids.add(region.id)
                visible = set(incoming)
                for instruction in region.instructions:
                    if instruction.id in ids or instruction.opcode not in OPCODES:
                        raise ValueError('invalid or duplicate instruction')
                    ids.add(instruction.id)
                    signatures = {'slot.declare': ['place'], 'slot.load': ['place'], 'slot.store': ['place', 'value'],
                                  'field.addr': ['value'], 'index.addr': ['value', 'value'],
                                  'memory.load': ['value'], 'memory.store': ['value', 'value'],
                                  'if': ['value'], 'loop': [], 'const': [], 'choose': ['value'],
                                  'short_circuit': ['value'], 'iterate': ['value'], 'iteration.value': []}
                    expected = signatures.get(instruction.opcode)
                    if expected is not None and [o.kind for o in instruction.operands] != expected:
                        raise ValueError('invalid instruction operands')
                    if not isinstance(instruction.result_type, dict) or not isinstance(instruction.result_type.get('kind'), str):
                        raise ValueError('invalid result type')
                    void = {'slot.declare', 'slot.store', 'memory.store', 'if', 'loop', 'return', 'break', 'continue', 'throw', 'iterate'}
                    if (instruction.opcode in void) != (instruction.result is None):
                        raise ValueError('invalid instruction result')
                    for operand in instruction.operands:
                        if operand.kind == 'value' and operand.ref not in visible:
                            raise ValueError('value used before definition or outside its region')
                        if operand.kind == 'place' and operand.ref not in function.places:
                            raise ValueError('unknown place')
                        if operand.kind not in {'value', 'place', 'symbol'}:
                            raise ValueError('invalid operand kind')
                    layout = [r.kind for r in instruction.regions]
                    if layout and instruction.opcode not in {'if','loop','choose','short_circuit','iterate'}:
                        raise ValueError('regions on a non-control instruction')
                    if instruction.opcode == 'choose':
                        if layout != ['consequence','alternative'] or any(len(r.outputs) != 1 for r in instruction.regions):
                            raise ValueError('choose requires two single-result arms')
                    elif instruction.opcode == 'short_circuit':
                        if layout != ['rhs'] or len(instruction.regions[0].outputs) != 1 or instruction.attrs.get('operator') not in {'and','or','&&','||','??'}:
                            raise ValueError('invalid short circuit region')
                        if instruction.attrs.get('result_policy') not in {'selected-operand','boolean'}:
                            raise ValueError('invalid short circuit result policy')
                    elif instruction.opcode == 'if':
                        if layout not in [['consequence'],['consequence','alternative']] or any(r.outputs for r in instruction.regions):
                            raise ValueError('invalid if regions')
                    elif instruction.opcode == 'loop':
                        expected_layout = {'while':['test','body'], 'do':['body','test'], 'for':['init','test','body','update']}.get(instruction.attrs.get('form', ''))
                        if layout != expected_layout or any(len(r.outputs) != (1 if r.kind == 'test' else 0) for r in instruction.regions):
                            raise ValueError('invalid loop regions')
                    elif instruction.opcode == 'iterate':
                        if layout != ['body'] or instruction.regions[0].outputs:
                            raise ValueError('iterate requires one body without outputs')
                        body = instruction.regions[0].instructions
                        if not body or body[0].opcode != 'iteration.value' or sum(i.opcode == 'iteration.value' for i in body) != 1:
                            raise ValueError('iterate requires one leading element definition')
                    elif instruction.opcode == 'iteration.value' and (not iteration_body or instruction is not region.instructions[0]):
                        raise ValueError('element outside iteration body')
                    for nested in instruction.regions:
                        check(nested, visible, depth + 1, instruction.opcode == 'iterate')
                    if instruction.result is not None:
                        if instruction.result in definitions:
                            raise ValueError('duplicate value definition')
                        definitions.add(instruction.result)
                        visible.add(instruction.result)
                if any(output not in visible for output in region.outputs):
                    raise ValueError('region output is undefined')
            check(function.body, set())

    def format(self) -> str:
        """Readable instruction assembly; JSON remains the interchange format."""
        self.verify()
        lines = [self.schema + ' source=' + self.source_version]
        for function in self.functions:
            places = {pid: '@p' + str(i) for i, pid in enumerate(function.places)}
            names: dict[str, str] = {}
            def value(ref):
                return names.setdefault(ref, '%' + str(len(names)))
            lines.append(f'func {json.dumps(function.name, ensure_ascii=False)} [{function.language}, {function.status}] {{')
            for pid, place in function.places.items():
                lines.append(f'  slot {places[pid]} {json.dumps(place["name"])} : {place["type"]["kind"]}')
            def render(region, level):
                pad = '  ' * level
                lines.append(pad + region.kind + ' {')
                for i in region.instructions:
                    operands = ', '.join((o.role + '=' if o.role else '') +
                        (value(o.ref) if o.kind == 'value' else places[o.ref] if o.kind == 'place' else json.dumps(o.ref)) for o in i.operands)
                    result = value(i.result) + ' : ' + i.result_type['kind'] + ' = ' if i.result is not None else ''
                    attrs = ' ' + json.dumps(i.attrs, ensure_ascii=False, sort_keys=True) if i.attrs else ''
                    effects = ' effects=' + json.dumps(i.effects) if i.effects else ''
                    lines.append(pad + '  ' + result + i.opcode + ' ' + operands + attrs + effects)
                    for nested in i.regions:
                        render(nested, level + 2)
                if region.outputs:
                    lines.append(pad + '  outputs ' + ', '.join(value(x) for x in region.outputs))
                lines.append(pad + '}')
            render(function.body, 1)
            if function.reasons:
                lines.append('  partial: ' + json.dumps(function.reasons))
            lines.append('}')
        return '\n'.join(lines) + '\n'
