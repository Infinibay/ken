# `factory-method#contract-slot` (Go/Rust) — cerrada (IR 1.53)

Estado: **cerrada**. La variante es `ready` en sus dos lenguajes declarados.
Fecha: 2026-09-13. Base: `fbe3b83`.

## Qué pide la ficha

> Resolver el contrato de creación suministrado al algoritmo cliente y la llamada
> de ese cliente al slot. Vincular la implementación concreta con el producto
> devuelto compatible. Positivo: method set Go o trait Rust sin herencia de clases.

Los contraejemplos de la ficha: constructor ajeno, producto fijo que evita el
slot, creación descartada y tipo de producto incompatible. Y una instrucción
explícita: «no sintetizar `SUBTYPE_OF` ficticio para compensar contratos
estructurales».

## Dos capacidades nuevas, elegidas para respetar el diseño existente

### 1. Go: `method_elem` como firma de método

`FUNCTIONS` ya incluía las firmas de interfaz de Java (`method_signature`),
TypeScript (`abstract_method_signature`) y C#; Go declara las suyas como
`method_elem` y **no estaba**. Sin él, `type Creator interface { Create() Product }`
no producía ninguna entidad, así que la interfaz no tenía operaciones y el cliente
no podía resolver su llamada.

Agregar `method_elem` a `FUNCTIONS` bastó: la interfaz declara `HAS_METHOD` y la
resolución de llamadas existente resuelve `c.Create()` a `Creator.Create`.

### 2. Go: satisfacción estructural como `IMPLEMENTS`, no `SUBTYPE_OF`

Go no tiene `implements`: un tipo satisface una interfaz cuando su method set
cubre todas las operaciones requeridas. La ficha prohíbe expresamente sintetizar
`SUBTYPE_OF` para eso, así que la relación es **`IMPLEMENTS`**, con
`basis='method-set'`, y además se emite `OVERRIDES` por método (consistente con
Java/TS/C#/C++).

El enlace exige **cobertura exacta**: nombre y aridad de cada operación requerida.
Un tipo que cubre solo parte de la interfaz no produce ningún hecho, nunca uno
parcial.

### 3. Rust: `&dyn Trait` resuelve a `Trait`

`creator.create()` sobre un parámetro `&dyn Creator` no llegaba al slot del trait
porque el nombre de tipo quedaba como `dyn Creator` y no resolvía. La corrección
es una normalización en `resolve`: `dyn X` e `impl X` nombran la misma declaración
que `X` para buscar miembros y slots.

## Una regresión que valió la pena: el diseño `DECLARED_TARGET`

La primera versión de la resolución nominal emitía `TARGET` para **todo** acceso a
miembro con receptor de tipo nominal. Eso rompió
`test_declared_dispatch.py::test_declared_slot_does_not_erase_concrete_ambiguity`,
que documenta un diseño anterior y más cuidadoso:

| Hecho | Cuándo |
|---|---|
| `DECLARED_TARGET` | el receptor tiene anotación nominal y el contrato declara un único slot |
| `MAY_TARGET` | hay varios destinos concretos posibles |
| `TARGET` | hay exactamente un destino concreto |

Es decir: el IR **ya separaba** «el slot declarado» de «el destino concreto
resuelto», y mi pase borraba esa distinción justo en el caso ambiguo. La versión
final no emite `TARGET`: solo aporta `MEMBER_DECLARATION` (campos) e `IMPLEMENTS`.
Que el test existiera y fallara fue lo que evitó publicar un hecho que habría
hecho pasar por resuelto un dispatch ambiguo.

## Contrato publicado

```kenql
query factory_contract_slot {
 require $client HAS_PARAMETER $supplied;
 parameter(receiver: false) as $supplied;
 require $client HAS_CALL $creation;
 require $creation RECEIVER $supplied;
 require $creation TARGET $slot;
 callable(constructor: false) as $slot;
 require $contract HAS_METHOD $slot;
 require $implementation OVERRIDES $slot;
 different $implementation $slot;
 require $implementation IN_TYPE $concrete;
 any { require $concrete SUBTYPE_OF $contract; }
 or { require $concrete IMPLEMENTS $contract; }
 require $implementation RETURNS_NEW $product;
 emit $concrete, $slot, $client, $contract, unit=$concrete, creator=$concrete,
      factory=$slot, product=$product;
}
```

`any { SUBTYPE_OF } or { IMPLEMENTS }` es explícito y no un sinónimo: Rust liga el
trait con `SUBTYPE_OF` nominal y Go con `IMPLEMENTS` estructural. El rol compartido
`unit` es el creador concreto, igual que en `virtual-slot`.

**Lo que no prueba** (declarado en `query_claim`): dispatch dinámico en ejecución,
que el cliente reciba realmente esa implementación, y la compatibilidad de tipos
del producto más allá de que sea una construcción nueva.

## Positivo y negativos

Positivo: **1 match** por lenguaje.

| Negativo | Por qué no hay match |
|---|---|
| Go: la interfaz pide una operación que el tipo no provee | cobertura no exacta |
| Go: el cliente no llama al slot | falta `TARGET` al slot del contrato |
| Go: el cliente llama al slot de **otro** contrato | el `TARGET` no es del contrato que la implementación satisface |
| Rust: el cliente ignora el slot y devuelve una constante | falta el `TARGET` sobre el parámetro |
| Rust: el trait lo implementa un tipo sin jerarquía de clases | **positivo**: el contrato es el trait, no una clase base |

## Archivos

- `src/ken/structural/frontend.py`: `method_elem` en `FUNCTIONS`.
- `src/ken/structural/semantic.py`: normalización `dyn`/`impl` en `resolve`.
- `src/ken/structural/structural_contracts.py`: pase nuevo (`MEMBER_DECLARATION`
  general, `IMPLEMENTS` + `OVERRIDES` estructurales de Go).
- `src/ken/structural/events.py`: consume `MEMBER_DECLARATION` en vez de
  recalcularlo (se quitó la resolución duplicada).
- `src/ken/structural/model.py`: `IR_VERSION` 1.52.0 → 1.53.0.
- `src/ken/structural/patterns/factory-method.toml`: variante `ready` con query;
  raíz con unión.
- `tests/structural/test_factory_method_contract_slot.py`: 8 tests.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_factory_method_contract_slot.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz nueva + catálogo: **276 passed**.
- Suite estructural completa: **6.709 passed, 143 xfailed**, sin fallos
  (baseline previo: 6.700 / 143; el delta son los tests nuevos).
- `mypy src/ken`: 109 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/frontend.py` | `6da9448e0e9e95a528ec71418fb931840fb6ad19dfcb8802ab1b155649bea589` |
| `src/ken/structural/semantic.py` | `046b727dc241ac65ab440f0d2471e7660eb56a5cfa50b2b5c6f9d009caf9652f` |
| `src/ken/structural/structural_contracts.py` | `498d8fc8227011cda15b48c5fc46ec00ce0326f219d85c8846c7c6ba649745b3` |
| `src/ken/structural/events.py` | `96ba714e63a04735fa57bc54234e2458076ce3f9db59b4e0ded714c441011648` |
| `src/ken/structural/model.py` | `9441b5b8986e43e6375a7986eb81fe4f9ecdcf93557b196f7ace9a510031d2cc` |
| `src/ken/structural/patterns/factory-method.toml` | `25193ae938fe6ec37fe749cfab92b1a058a7337ddc344991b6dbe6e36969853d` |
| `tests/structural/test_factory_method_contract_slot.py` | `a2b880fa4b68f2753095d404a7179e2be6ff1059cfab0534740181e33272d1e8` |

## Inventario

**50 ready / 27 design** (antes 49 / 28).

## Siguiente paso

`IMPLEMENTS` estructural ya existe: sirve directamente a
`abstract-factory#structural-families` (javascript, typescript, go), que pide
«relacionar objetos/structs con el mismo conjunto de operaciones de creación sin
exigir herencia». Es el candidato inmediato.
