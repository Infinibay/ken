# `template-method#trait-default` (Rust) — cerrada

Estado: **cerrada**. La variante es `ready` en su único lenguaje declarado.
Fecha: 2026-09-13. Base: `3dac5ec`.

## Resultado inesperado: no hizo falta capacidad nueva

A diferencia de las dos variantes anteriores, esta se cerró **solo con query y
tests**. El IR ya resolvía todo lo que el contrato pide:

| Necesidad | Evidencia ya existente |
|---|---|
| Método default del trait | `INTERFACE:Pipeline HAS_METHOD CALLABLE:run` con cuerpo |
| Slots que llama | `run HAS_CALL CALL:...` + `CALL TARGET CALLABLE:prepare` |
| Slots declarados por el trait | `INTERFACE:Pipeline HAS_METHOD CALLABLE:prepare` |
| Ligadura impl→trait | `CLASS:Alpha SUBTYPE_OF INTERFACE:Pipeline` |
| Ligadura hook→implementación | `CALLABLE:Alpha.prepare OVERRIDES CALLABLE:Pipeline.prepare` |
| Tipo concreto del override | `CALLABLE:Alpha.prepare IN_TYPE CLASS:Alpha` |

`OVERRIDES` ya unía el método de la implementación con el slot del trait, y
`SUBTYPE_OF` ya unía el tipo con el trait. La variante estaba bloqueada por
inventario, no por análisis: nunca se había escrito su query.

Es el primer caso del inventario donde el trabajo faltante era **expresar** el
contrato, no construirlo.

## Contrato publicado

```kenql
query template_method {
 require $unit HAS_METHOD $algorithm;
 require $algorithm HAS_CALL $hook_call;
 require $hook_call TARGET $hook;
 require $unit HAS_METHOD $hook;
 different $algorithm $hook;
 count distinct $concrete >= 2 {
   require $implementation OVERRIDES $hook;
   require $implementation IN_TYPE $concrete;
   require $concrete SUBTYPE_OF $unit;
 };
 emit $unit, $algorithm, $hook;
}
```

El bloque `count distinct $concrete >= 2` es lo que exige que el hook esté
**implementado por dos tipos**, no por uno. El rol compartido de la raíz sigue
siendo `unit`: en `virtual-skeleton` es la clase con el esqueleto, y aquí el
trait.

**Lo que no prueba** (declarado en `query_claim`): instanciación de los tipos
concretos, dispatch dinámico en ejecución, ni el orden real de las llamadas.

## Positivo y negativos

Positivo: **2 matches** (uno por hook del algoritmo, cada uno con dos
implementaciones registradas).

| Negativo | Por qué no hay match |
|---|---|
| Trait sin método default | no hay `HAS_CALL` que analizar |
| Default que no llama al hook (devuelve constante) | falta `TARGET` al slot |
| Hook nunca sobrescrito | falta `OVERRIDES` |
| Default que llama a una función libre | el `TARGET` no es un método del trait |
| Hook implementado por **un solo** tipo | `count distinct $concrete >= 2` falla |

Más un positivo con trait y hooks renombrados (`Conveyor`/`alpha`/`beta`/`gamma`).

## Archivos

- `src/ken/structural/patterns/template-method.toml`: variante `ready` con query;
  raíz con unión.
- `tests/structural/test_template_method_trait_default.py`: 8 tests.

Sin cambios en `src/ken/structural/*.py` y sin subir `IR_VERSION`: el grafo
persistido no cambia.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_template_method_trait_default.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
```

- Matriz nueva + catálogo: **273 passed**.
- Suite estructural completa: **6.662 passed, 146 xfailed**, sin fallos
  (baseline previo: 6.653 / 146; el delta son los tests nuevos).
- `mypy src/ken`: 108 archivos, sin errores (no se tocó código fuente).

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/patterns/template-method.toml` | `780a4a069fe30b7c9b42a4c4054d4be3720298fc0c03d50c124cb2e7a84cdbae` |
| `tests/structural/test_template_method_trait_default.py` | `6a3d93b5b075f36bae027b6acd0057eae02d213b0c109f86de9938dd7a99306b` |

## Inventario

**47 ready / 30 design** (antes 46 / 31).

## Lección para las variantes restantes

Antes de asumir que una variante `design` necesita una capacidad nueva, conviene
**escribir su query y correrla**. Tres de las cuatro variantes cerradas en este
trabajo necesitaban capacidad real, pero esta no: el IR ya estaba listo y el
trabajo pendiente era de expresión del contrato. La ficha decía
`fixtures_status = "documented-not-validated"` y `missing_capability = "unknown"`,
que es exactamente el estado que oculta este caso.

## Siguiente paso

Repetir el ejercicio con **`abstract-factory#associated-products`** (solo Rust):
tipos asociados de trait sustituidos por cada impl. El IR ya liga impl→trait con
`SUBTYPE_OF` y `OVERRIDES`; falta comprobar si el tipo asociado `Output` se
sustituye o queda como `Self::Output` irresuelto (el sondeo previo sugiere que
los `RETURN_TYPE_REF` del trait y del impl ya coinciden para el caso de Rust).
