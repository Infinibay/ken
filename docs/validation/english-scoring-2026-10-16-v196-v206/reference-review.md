# Revisión independiente de referencias inglesas v203

En las fuentes físicas indicadas encontré **una regresión completa en attrs**, **una en boltons** y **dos generadores completos e independientes en Ajv**. La tercera consulta admite varias respuestas bajo sus condiciones literales. No se cambió ninguna referencia ni consulta.

## 1. attrs

`tests/test_make.py::TestKeywordOnlyAttributes.test_ignores_kw_only_when_init_is_false` (1042–1055) satisface toda la consulta. Las líneas1049–1050 declaran `x = attr.ib(init=False, default=0, kw_only=True)` antes de `y = attr.ib()`; 1052 construye `C(1)` y 1054–1055 comprueban `x == 0`, `y == 1`.

La alternativa más próxima, `tests/test_dunders.py::TestAddInit.test_no_init_default` (784–805), mantiene defaults con `init=False` y permite `C(23)` para el campo posterior, pero no marca esos campos como keyword-only. Los tests de orden de keyword-only y no-init en 1088–1117/1190–1244 distribuyen las propiedades entre campos distintos o no pasan un argumento posicional. El JSON desglosa estos vecinos.

La búsqueda AST de los56 archivos Python (0 errores de parseo) encontró una sola llamada que combina literalmente `kw_only=True` e `init=False`: la línea1049. Esto apoya la unicidad encontrada; no prueba ausencia de toda posible construcción dinámica equivalente.

## 2. boltons

`tests/test_listutils.py::test_barrellist_slicing_matches_list` (209–222) satisface toda la consulta: tamaños `(0, 1, 8)` (213), referencia `list` y `BarrelList` (214–215), producto de bounds `(None,-20,-2,0,2,20)` y pasos `(None,-3,-1,1,2)` (216–219), comparación exacta con `reference[key]` (220) y `pytest.raises(ValueError)` para `value[::0]` (221–222).

Los tests de borrado entre barrels y hasta el final no cubren vacíos/strides/cero. `tests/test_setutils.py::test_iset_slice_agreement` (255–274) trata un `IndexedSet`, omite cero y sólo compara contra el builtin cuando el paso es positivo o None. No es otra respuesta completa.

Aquí «segmented-list» designa el tipo `BarrelList`, descrito como respaldado por sublistas en `boltons/listutils.py:60–65`. El test completo no fuerza múltiples barrels internos en tamaños tan pequeños; la pregunta tampoco exige cruzar fronteras entre barrels.

## 3. Ajv

| Generador completo | Cola | Marca y límite falso | Gate de validación extra |
|---|---|---|---|
| `lib/vocabularies/applicator/additionalItems.ts::validateAdditionalItems` (35–54) | Desde `items.length` (49) | `it.items = true` (37); `cxt.pass(len <= items.length)` (39–41) | Objeto y `!alwaysValidSchema` (42–44); `subschema` por índice (49–51) |
| `lib/vocabularies/unevaluated/unevaluatedItems.ts::def.code` (23–44) | Desde `it.items || 0` (25,38–40) | `cxt.fail(len > items)` (28–30); `it.items = true` (36) | Objeto y `!alwaysValidSchema` (31–34); `subschema` por índice (39–41) |

Ambos cumplen todas las condiciones. La consulta no fija el keyword, el origen de la posición inicial ni el orden de marcar evaluated. Por ello, esas diferencias no excluyen a `unevaluatedItems`. «No trivial» corresponde a `!alwaysValidSchema`: el helper también considera triviales objetos sin reglas reconocidas (`lib/compile/util.ts:14–19,31–37`), no sólo `{}`.

Además hay dos entradas locales con delegación explícita: `additionalItems.ts::def.code` (24–32) invoca el primer generador cuando `parentSchema.items` es arreglo; `items2020.ts::def.code` (26–33) lo invoca en la rama `prefixItems`. Son puntos de entrada a esa generación, no dos implementaciones independientes adicionales. En `items2020` la otra rama valida el arreglo entero. El JSON distingue esta coincidencia por delegación de las implementaciones directas.

Los helpers internos `validateItems` sólo contienen el bucle: marca, límite falso y gate pertenecen a la función exterior. `validateArray`, `validateTuple`, `contains.code` y `limitItems.code` son vecinos parciales; el JSON cita exactamente qué requisitos omiten.

## Procedencia y límites

El primer `ken_find` literal, aunque recibió la raíz absoluta attrs, devolvió siete snippets de dos reportes históricos de `docs/validation` del proyecto Ken en vez de limitarse a esa raíz. Expuso el nombre del test attrs y parte de su explicación. No abrí esos archivos; informé a root, dejé de usar Ken y basé toda evidencia posterior en las tres raíces físicas. **No afirmo descubrimiento ciego ni independencia absoluta para attrs**. Los paths exactos del incidente están en el JSON; ningún reporte/ranking se usa como evidencia de corrección. No se abrió ninguna reserva.

Las citas y hashes SHA256 de todos los archivos de evidencia se validaron contra los bytes físicos al cerrar. No ejecuté tests, benchmarks, modelos ni generadores; tampoco leí Gold/datasets/candidatos ni propuse cambios de implementación o política. La unicidad indicada significa única coincidencia completa encontrada en el snapshot y bajo el alcance de búsqueda documentado.

JSON SHA256: `d2433863ffbd57068116d2edfa0c2568a64a60e21c38e7e9d6fa605e1febc750`.
