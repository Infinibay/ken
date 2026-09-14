# `abstract-factory#associated-products` (Rust) — cerrada

Estado: **cerrada**. La variante es `ready` en su único lenguaje declarado.
Fecha: 2026-09-13. Base: `22937e8`.

## La ficha pedía algo que el IR no da — y el contrato se pudo expresar igual

La ficha dice «Sustituir tipos asociados por familia». Eso **no** está modelado:

- `type Reader;` (declaración en el trait) no produce ningún hecho.
- `type Reader = FileReader;` (sustitución en el impl) tampoco.
- `RETURN_TYPE_REF` es textual: el `Self::Reader` del trait y el de **ambos**
  impls comparten el mismo hash, así que no distingue `FileReader` de
  `MemoryReader`.

Pero el IR **sí** registra el producto realmente devuelto por cada slot:

```text
RETURNS  CALLABLE:reader@297  ->  CLASS:FileReader     # FileFactory::reader
RETURNS  CALLABLE:writer@349  ->  CLASS:FileWriter     # FileFactory::writer
```

Y ya tenía la estructura de la familia:

```text
INTERFACE:Factory HAS_METHOD reader, writer
CLASS:FileFactory   SUBTYPE_OF INTERFACE:Factory
CLASS:FileFactory::reader OVERRIDES INTERFACE:Factory::reader
```

Con eso el contrato se expresa **sobre los productos devueltos**, que es lo que
el algoritmo realmente exige, en lugar de sobre una sustitución de tipo que el
analizador no calcula.

## Contrato publicado

```kenql
query abstract_factory {
 require $unit SUBTYPE_OF $contract;
 require $other SUBTYPE_OF $contract;
 different $unit $other;
 require $contract HAS_METHOD $first_slot;
 require $contract HAS_METHOD $second_slot;
 different $first_slot $second_slot;
 require $first_reader OVERRIDES $first_slot;
 require $first_reader IN_TYPE $unit;
 require $first_reader RETURNS $first_product;
 require $first_product IS CLASS;
 ... (idéntico para el segundo slot y para la segunda familia) ...
 different $first_product $second_product;    # dentro de la familia
 different $first_product $third_product;     # el mismo slot entre familias
 different $second_product $fourth_product;
 emit $unit, $contract;
}
```

El rol `unit` es **la fábrica concreta**, igual que en `nominal-families`; el
trait queda en `contract`. La raíz `abstract-factory` une las dos variantes y
emite `$unit`, así que el rol compartido no cambia de dominio.

**Lo que no prueba** (declarado en `query_claim`): no sustituye tipos asociados
—no se modelan—, no prueba instanciación ni que el cliente use la familia.

## Positivo y negativos

Positivo: **2 matches**, uno por fábrica concreta (`FileFactory`,
`MemoryFactory`), ambas bajo `INTERFACE:Factory`.

| Negativo | Por qué no hay match |
|---|---|
| Un producto compartido entre familias (`MemoryFactory::writer` devuelve `FileWriter`) | `different $second_product $fourth_product` falla |
| Una sola familia | `different $unit $other` no tiene segunda fábrica |
| Productos colapsados dentro de una familia (ambos slots devuelven `FileReader`) | `different $first_product $second_product` falla |
| Un tipo que implementa **otro** trait | no hay `SUBTYPE_OF $contract` |
| Trait con un solo slot | falta `$second_slot` |

Más un positivo con trait y productos renombrados (`Assembler`/`DiskSource`/…).

## Archivos

- `src/ken/structural/patterns/abstract-factory.toml`: variante `ready` con
  query; raíz con unión.
- `tests/structural/test_abstract_factory_associated_products.py`: 8 tests.

Sin cambios en `src/ken/structural/*.py` y sin subir `IR_VERSION`.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_abstract_factory_associated_products.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
```

- Matriz nueva + catálogo: **274 passed**.
- Suite estructural completa: **6.671 passed, 146 xfailed**, sin fallos
  (baseline previo: 6.662 / 146; el delta son los tests nuevos).
- `mypy src/ken`: 108 archivos, sin errores (no se tocó código fuente).

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/patterns/abstract-factory.toml` | `36ac83746de24ae984f8b1da9cd6976a38745294ce5c3a095ead454582383755` |
| `tests/structural/test_abstract_factory_associated_products.py` | `b0be51147603a3a9114069d71b71413296fa6e2c98088c7a340725b315368fe0` |

## Inventario

**48 ready / 29 design** (antes 47 / 30).

## Siguiente paso

Queda pendiente modelar los tipos asociados de Rust si alguna variante futura los
necesita de verdad (por ahora ninguna: esta se expresó sin ellos). La lección de
la variante anterior se confirma: **dos de las cuatro variantes cerradas no
necesitaron capacidad nueva**, solo escribir el contrato. Conviene probar la
query antes de asumir que una fila `design` requiere análisis nuevo.

Candidatos siguientes sin C++: `abstract-factory#structural-families` (JS/TS/Go),
`factory-method#contract-slot` (Go/Rust), `iterator#callback-iterator` (Go) e
`iterator#async-iterator` (Python/JS/TS/C#).
