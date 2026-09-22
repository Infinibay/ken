# Conteo verificable por patrón, variante, lenguaje y caso

Base `353fc1444823bded9e04b465e7ee64b3809bb043`, IR **1.76.0**. **412 celdas**, **2060 casos de matriz** y **252 casos dirigidos adicionales**. Cada celda tiene 5 familias mínimas; no son el techo de cobertura.

Las familias fijan el oráculo antes de consultar: `canonical` (positivo), `inert` (negativo claro), `noise-1` y `noise-20` (positivos válidos con instrucciones intercaladas, buscando FN), y `algorithm-removed` (negativo que conserva declaraciones pero elimina implementación, buscando FP). **TP/TN/FP/FN son resultados, no etiquetas que obliguen a conservar errores.**

La matriz incluye todas las variantes ready y sus lenguajes anunciados en los TOML. Los tres roots sin variantes y las variantes sin lista de lenguajes tienen un ámbito explícito en seeds.json. Las combinaciones no anunciadas y las variantes design se enumeran abajo; no se contabilizan como aprobadas. Las quince operaciones se auditaron y tienen checks ABI previos; no se cuentan como variantes con esta matriz mínima.

| Grupo | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| Matriz por variante/lenguaje | 1203 | 823 | 1 | 33 |
| Casos dirigidos adicionales | 155 | 37 | 51 | 9 |

**Celdas sin desacuerdos en el mínimo y sus casos dirigidos:** 359. **Con regresiones conocidas:** 53. **Celdas faltantes:** 0. **Resultados inesperados respecto del ledger:** 0.

“Ejercitada” no equivale a implementación correcta. Los negativos inertes se repiten entre variantes y las transformaciones se parecen entre sí: los totales no son muestras independientes ni precisión/recall de producción. El mínimo uniforme se complementa con los contraejemplos específicos del reporte, los tests idiomáticos existentes y nuevos casos que se agreguen por causa. Un stub es un contraste de implementación, no prueba exhaustiva contra casi-patrones.

## Cómo mantener el conteo

1. Añadir una fuente y su procedencia a `tests/structural/catalog_matrix/seeds.json` cuando se anuncie una variante/lenguaje. El test de inventario falla si un TOML añade una combinación sin la celda correspondiente.
2. Fijar expected y motivo antes de evaluar. Los casos dirigidos tienen fuente propia; no sustituirlos por variantes generadas del mismo ejemplo.
3. Ejecutar pytest y este reporte. Un fallo nuevo falla el test; un fallo conocido sólo produce xfail tras verificar parsing y ejecución completa. Si se corrige, se produce un fallo XPASS hasta retirar su entrada exacta del ledger.
4. Nunca registrar invalid/incomplete como TN ni generar el ledger automáticamente desde los resultados. Cada entrada tiene una causa revisada y propuesta de mejora.

```sh
.venv/bin/python -m pytest tests/structural/test_catalog_adversarial_matrix.py -q
PYTHONPATH=. .venv/bin/python -m examples.bench.audit_catalog_matrix \
  --output docs/structural-validation/catalog-adversarial-2026-09-14
```

Archivos: [fuentes y ámbito](../../../tests/structural/catalog_matrix/seeds.json), [regresiones y causas](../../../tests/structural/catalog_matrix/known_failures.json), [resultados por caso](matrix-results.json), [reporte de cada patrón](README.md).

## Cada celda

Las columnas C/I/N1/N20/A muestran canonical, inert, noise-1, noise-20 y algorithm-removed. Cada combinación de fila y columna tiene el ID `target/language/family` en matrix-results.json. Dirigidos suma los casos adicionales de esa variante/lenguaje en orden TP/TN/FP/FN; las causas incluyen ambas fuentes de evidencia. Los ensayos que seleccionan sólo una raíz se muestran aparte, sin atribuirlos a una variante arbitraria.

| Patrón / variante | Lenguaje | C | I | N1 | N20 | A | Dirigidos TP/TN/FP/FN | Causas pendientes |
|---|---|---|---|---|---|---|---|---|
| `abstract-factory#associated-products` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#nominal-families` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#nominal-families` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#nominal-families` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#nominal-families` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#structural-families` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#structural-families` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `abstract-factory#structural-families` | typescript | TP | TN | TP | TP | TN | 0/0/0/1 | structural-object-provider |
| `adapter#class-adapter` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#class-adapter` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#functional-adapter` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#functional-adapter` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#functional-adapter` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#functional-adapter` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#functional-adapter` | javascript | TP | TN | TP | TP | TN | 0/0/1/0 | adapter-request-join |
| `adapter#functional-adapter` | python | TP | TN | TP | TP | TN | 0/0/1/0 | adapter-request-join |
| `adapter#functional-adapter` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#functional-adapter` | typescript | TP | TN | TP | TP | TN | 0/0/1/0 | adapter-request-join |
| `adapter#object-adapter` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#object-adapter` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#object-adapter` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `adapter#object-adapter` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.adapted-continuation-wrapper` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.adapted-continuation-wrapper` | javascript | TP | TN | TP | TP | TN | 1/1/0/0 |  |
| `architecture.adapted-continuation-wrapper` | python | TP | TN | TP | TP | TN | 2/1/1/0 | adapter-discards-handler |
| `architecture.adapted-continuation-wrapper` | typescript | TP | TN | TP | TP | TN | 1/1/0/0 |  |
| `architecture.batch-work-queue#stored-batch` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.batch-work-queue#stored-batch` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.batch-work-queue#stored-batch` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.batch-work-queue#stored-batch` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.batch-work-queue#stored-batch` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.cache-aside#java-optional` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.cache-aside#null-miss` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.cache-aside#null-miss` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.cache-aside#null-miss` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.cache-aside#null-miss` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.cache-aside#null-miss` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.continuation-wrapper` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.continuation-wrapper` | javascript | TP | TN | TP | TP | TN | 1/1/0/0 |  |
| `architecture.continuation-wrapper` | python | TP | TN | TP | TP | TN | 2/1/1/0 | continuation-rebind |
| `architecture.continuation-wrapper` | typescript | TP | TN | TP | TP | TN | 1/1/0/0 |  |
| `architecture.dependency-injection#callable-input` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#callable-input` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#callable-input` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#callable-input` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#callable-input` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#callable-input` | rust | TP | TN | FN | FN | TN | 0/0/0/0 | rust-wildcard-summary |
| `architecture.dependency-injection#callable-input` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#object-assignment` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#object-assignment` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#object-assignment` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#object-assignment` | python | TP | TN | TP | TP | TN | 0/0/1/0 | di-historical-input |
| `architecture.dependency-injection#object-assignment` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#retained-object` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#retained-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#retained-object` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#retained-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dependency-injection#retained-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dispatch-table#adapted` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dispatch-table#adapted` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dispatch-table#adapted` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dispatch-table#direct` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dispatch-table#direct` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.dispatch-table#direct` | python | TP | TN | TP | TP | TN | 0/0/1/0 | dispatch-historical-value |
| `architecture.dispatch-table#direct` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.read-through-cache` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.read-through-cache` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.read-through-cache` | javascript | TP | TN | TP | TP | TN | 1/1/0/0 |  |
| `architecture.read-through-cache` | python | TP | TN | TP | TP | TN | 2/1/0/1 | cfg-adjacency |
| `architecture.read-through-cache` | typescript | TP | TN | TP | TP | TN | 1/1/0/0 |  |
| `architecture.subclass-factory#returned-subclass` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `architecture.subclass-factory#returned-subclass` | python | TP | TN | TP | TP | TN | 0/0/0/1 | base-alias |
| `architecture.subclass-factory#returned-subclass` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#generic-composition` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#generic-composition` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#generic-composition` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#generic-composition` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#generic-composition` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#generic-composition` | typescript | TP | TN | TP | TP | TN | 0/1/1/0 | generic-name-identity |
| `bridge#refined-composition` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#refined-composition` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#refined-composition` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#refined-composition` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#runtime-composition` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#runtime-composition` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `bridge#runtime-composition` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#consuming-typestate` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#consuming-typestate` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#consuming-typestate` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#director` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#immutable-product` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#immutable-product` | csharp | TP | TN | TP | TP | TN | 1/0/0/0 |  |
| `builder#immutable-product` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#immutable-product` | java | TP | TN | TP | TP | TN | 1/0/0/0 |  |
| `builder#immutable-product` | javascript | TP | TN | TP | TP | TN | 1/0/1/0 | builder-construction-join |
| `builder#immutable-product` | python | TP | TN | TP | TP | TN | 1/0/1/0 | builder-construction-join |
| `builder#immutable-product` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#immutable-product` | typescript | TP | TN | TP | TP | TN | 1/0/1/0 | builder-construction-join |
| `builder#mutable-product` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#mutable-product` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#mutable-product` | go | FN | TN | FN | FN | TN | 0/0/0/0 | named-construction-flow |
| `builder#mutable-product` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#mutable-product` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#mutable-product` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#mutable-product` | rust | FN | TN | FN | FN | TN | 0/0/0/0 | named-construction-flow |
| `builder#mutable-product` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#stored-product` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#stored-product` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#stored-product` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#stored-product` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `builder#stored-product` | rust | TP | TN | FN | FN | TN | 0/0/0/0 | rust-wildcard-summary |
| `builder#stored-product` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#linked-handlers` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#linked-handlers` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#linked-handlers` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `chain-of-responsibility#middleware-closures` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-closure` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-closure` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-closure` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-closure` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-closure` | javascript | TP | TN | TP | TP | TN | 1/0/1/0 | command-context-join |
| `command#command-closure` | python | TP | TN | TP | TP | TN | 1/0/1/0 | command-context-join |
| `command#command-closure` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-closure` | typescript | TP | TN | TP | TP | TN | 1/0/1/0 | command-context-join |
| `command#command-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#command-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#queued-object` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#queued-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#queued-object` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#queued-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#queued-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-contract` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-contract` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-contract` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-contract` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-contract` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-object` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#retained-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#stored-closure` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#stored-closure` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#stored-closure` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#stored-closure` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `command#stored-closure` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#algebraic-tree` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#algebraic-tree` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#algebraic-tree` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#algebraic-tree` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#algebraic-tree` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#algebraic-tree` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#higher-order-traversal` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-contract` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-contract` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-contract` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-nominal` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-nominal` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-nominal` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-nominal` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `composite#recursive-nominal` | typescript | FN | TN | FN | FN | TN | 0/0/0/0 | array-element-type |
| `decorator#callable-wrapper` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#callable-wrapper` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#callable-wrapper` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#callable-wrapper` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#callable-wrapper` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#callable-wrapper` | python | TP | TN | TP | TP | TN | 0/0/1/0 | decorator-identity |
| `decorator#callable-wrapper` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#callable-wrapper` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#object-wrapper` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#object-wrapper` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `decorator#object-wrapper` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `facade#module-surface` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `facade#module-surface` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `facade#module-surface` | python | TP | TN | TP | TP | TN | 0/0/1/0 | facade-composition |
| `facade#module-surface` | rust | TP | TN | FN | FN | TN | 0/0/0/0 | rust-wildcard-summary |
| `facade#module-surface` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `facade#object-surface` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `facade#object-surface` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `facade#object-surface` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `factory-method#contract-slot` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `factory-method#contract-slot` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `factory-method#virtual-slot` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `factory-method#virtual-slot` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `factory-method#virtual-slot` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `factory-method#virtual-slot` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `flyweight#entry-api` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `flyweight#entry-api` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `flyweight#entry-api` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `flyweight#entry-api` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `flyweight#explicit-interning` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `flyweight#explicit-interning` | python | TP | TN | TP | TP | TN | 0/0/1/0 | flyweight-replacement |
| `flyweight#explicit-interning` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-objects` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-objects` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-objects` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-objects` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-sum` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-sum` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-sum` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-sum` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-sum` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `interpreter#expression-sum` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#async-iterator` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#async-iterator` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#async-iterator` | python | TP | TN | TP | TP | TN | 0/0/0/1 | async-await-requirement |
| `iterator#async-iterator` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#callback-iterator` | go | TP | TN | TP | TP | TN | 1/0/1/0 | go-yield-polarity |
| `iterator#delegated-cursor` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#delegated-generator` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#delegated-generator` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#delegated-generator` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#explicit-cursor` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#external-cursor` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#generator` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#generator` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#generator` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#generator` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#paired-cursor` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `iterator#paired-cursor` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#direct-colleagues` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#direct-colleagues` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#direct-colleagues` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#message-coordination` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `mediator#tag-dispatch` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#accessor-snapshot` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#accessor-snapshot` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#accessor-snapshot` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#accessor-snapshot` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#accessor-snapshot` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#serialized-snapshot` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#serialized-snapshot` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#serialized-snapshot` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#serialized-snapshot` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#serialized-snapshot` | javascript | TP | TN | TP | TP | TN | 1/0/0/0 |  |
| `memento#serialized-snapshot` | python | TP | TN | TP | TP | TN | 1/0/1/0 | memento-return-join |
| `memento#serialized-snapshot` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#serialized-snapshot` | typescript | TP | TN | TP | TP | TN | 1/0/0/0 |  |
| `memento#snapshot-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#snapshot-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `memento#snapshot-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | python | TP | TN | TP | TP | TN | 1/0/1/0 | eventbus-payload-join |
| `observer#event-bus` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#event-bus` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#language-event` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#listener-registry` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#listener-registry` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#listener-registry` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#map-key-registry` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#snapshot-registry` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#snapshot-registry` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `observer#snapshot-registry` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `persistence.unit-of-work#keyed-change-set` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `persistence.unit-of-work#keyed-change-set` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `persistence.unit-of-work#keyed-change-set` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `persistence.unit-of-work#keyed-change-set` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `persistence.unit-of-work#keyed-change-set` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#derived-clone` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#explicit-copy` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#explicit-copy` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#explicit-copy` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#explicit-copy` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#explicit-copy` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#field-copy` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#field-copy` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#field-copy` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#field-copy` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#field-copy` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#language-copy` | cpp | TP | TN | TP | TP | FP | 0/0/0/0 | declaration-only-copy |
| `prototype#language-copy` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#language-copy` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `prototype#language-copy` | python | TP | TN | TP | TP | TN | 0/0/1/0 | copy-use-vs-return |
| `prototype#language-copy` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#guarded-access` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#guarded-access` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#guarded-access` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | python | TP | TN | TP | TP | TN | 1/0/1/0 | lazy-construction-join |
| `proxy#lazy-subject` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#lazy-subject` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `proxy#remote-subject` | cpp | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `proxy#remote-subject` | csharp | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `proxy#remote-subject` | go | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `proxy#remote-subject` | java | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `proxy#remote-subject` | javascript | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `proxy#remote-subject` | python | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `proxy#remote-subject` | rust | TP | TN | TP | TP | TN | 1/0/0/0 |  |
| `proxy#remote-subject` | typescript | TP | TN | TP | TP | TN | 1/0/1/0 | remote-response-join |
| `resilience.exception-retry#explicit-continue` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#explicit-continue` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#explicit-continue` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#explicit-continue` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#explicit-continue` | python | TP | TN | TP | TP | TN | 0/0/1/0 | finally-overrides-continue |
| `resilience.exception-retry#explicit-continue` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#handler-fallthrough` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#handler-fallthrough` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#handler-fallthrough` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#handler-fallthrough` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#handler-fallthrough` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `resilience.exception-retry#handler-fallthrough` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#eager-shared` | csharp | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#eager-shared` | java | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#eager-shared` | typescript | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#lazy-guarded` | csharp | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#lazy-guarded` | java | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#lazy-guarded` | javascript | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#lazy-guarded` | python | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#lazy-guarded` | typescript | TP | TN | FN | FN | TN | 0/0/0/0 | cfg-adjacency |
| `singleton#module-shared` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#module-shared` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#module-shared` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#module-shared` | python | TP | TN | TP | TP | TN | 1/0/1/0 | module-write-count |
| `singleton#module-shared` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#module-shared` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#once-primitive` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#once-primitive` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#once-primitive` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `singleton#once-primitive` | java | TP | TN | TP | TP | TN | 1/0/1/0 | once-api |
| `singleton#once-primitive` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#context-transition` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#context-transition` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#context-transition` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#context-transition` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#context-transition` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-enum` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `state#state-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#static-policy` | cpp | TP | TN | TP | TP | TN | 0/0/0/1 | static-policy-field |
| `strategy#static-policy` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-callable` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-callable` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-callable` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-callable` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-object` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-object` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-object` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-object` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `strategy#strategy-object` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | go | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | javascript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#composed-skeleton` | rust | TP | TN | FN | FN | TN | 0/0/0/0 | rust-wildcard-summary |
| `template-method#composed-skeleton` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#trait-default` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#virtual-skeleton` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#virtual-skeleton` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#virtual-skeleton` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `template-method#virtual-skeleton` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#generic-visitor` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#generic-visitor` | rust | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#named-dispatch` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#named-dispatch` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#named-dispatch` | python | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#named-dispatch` | typescript | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#overloaded-dispatch` | cpp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#overloaded-dispatch` | csharp | TP | TN | TP | TP | TN | 0/0/0/0 |  |
| `visitor#overloaded-dispatch` | java | TP | TN | TP | TP | TN | 0/0/0/0 |  |

## Ensayos dirigidos de raíz

Estas filas seleccionan la query raíz, por lo que un match puede provenir de distintas variantes. Los tres roots sin variantes aparecen también en sus celdas anteriores: esta vista no añade casos al total.

| Raíz | Lenguaje | TP | TN | FP | FN | Causas pendientes |
|---|---|---:|---:|---:|---:|---|
| `abstract-factory` | java | 1 | 0 | 0 | 0 |  |
| `abstract-factory` | python | 2 | 1 | 0 | 0 |  |
| `abstract-factory` | typescript | 1 | 0 | 0 | 0 |  |
| `adapter` | java | 1 | 0 | 0 | 0 |  |
| `adapter` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `adapter` | typescript | 1 | 0 | 0 | 0 |  |
| `architecture.adapted-continuation-wrapper` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.adapted-continuation-wrapper` | python | 2 | 1 | 1 | 0 | adapter-discards-handler |
| `architecture.adapted-continuation-wrapper` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.batch-work-queue` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.batch-work-queue` | python | 2 | 1 | 1 | 0 | queue-preclear |
| `architecture.batch-work-queue` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.cache-aside` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.cache-aside` | python | 2 | 1 | 0 | 1 | cfg-adjacency |
| `architecture.cache-aside` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.continuation-wrapper` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.continuation-wrapper` | python | 2 | 1 | 1 | 0 | continuation-rebind |
| `architecture.continuation-wrapper` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.dependency-injection` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.dependency-injection` | python | 2 | 1 | 0 | 0 |  |
| `architecture.dependency-injection` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.dispatch-table` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.dispatch-table` | python | 2 | 1 | 0 | 0 |  |
| `architecture.dispatch-table` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.read-through-cache` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.read-through-cache` | python | 2 | 1 | 0 | 1 | cfg-adjacency |
| `architecture.read-through-cache` | typescript | 1 | 1 | 0 | 0 |  |
| `architecture.subclass-factory` | javascript | 1 | 1 | 0 | 0 |  |
| `architecture.subclass-factory` | python | 2 | 1 | 0 | 0 |  |
| `architecture.subclass-factory` | typescript | 1 | 1 | 0 | 0 |  |
| `bridge` | java | 1 | 0 | 0 | 0 |  |
| `bridge` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `bridge` | typescript | 1 | 0 | 0 | 0 |  |
| `builder` | java | 1 | 0 | 0 | 0 |  |
| `builder` | python | 2 | 1 | 0 | 0 |  |
| `builder` | typescript | 1 | 0 | 0 | 0 |  |
| `chain-of-responsibility` | java | 1 | 0 | 0 | 0 |  |
| `chain-of-responsibility` | python | 2 | 0 | 1 | 1 | dead-implementation, early-exit-guard |
| `chain-of-responsibility` | typescript | 1 | 0 | 0 | 0 |  |
| `command` | java | 1 | 0 | 0 | 0 |  |
| `command` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `command` | typescript | 1 | 0 | 0 | 0 |  |
| `composite` | java | 1 | 0 | 0 | 0 |  |
| `composite` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `composite` | typescript | 1 | 0 | 0 | 0 |  |
| `decorator` | java | 1 | 0 | 0 | 0 |  |
| `decorator` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `decorator` | typescript | 1 | 0 | 0 | 0 |  |
| `facade` | java | 1 | 0 | 0 | 0 |  |
| `facade` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `facade` | typescript | 1 | 0 | 0 | 0 |  |
| `factory-method` | java | 1 | 0 | 0 | 0 |  |
| `factory-method` | python | 2 | 1 | 0 | 0 |  |
| `factory-method` | typescript | 1 | 0 | 0 | 0 |  |
| `flyweight` | java | 1 | 0 | 0 | 0 |  |
| `flyweight` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `flyweight` | typescript | 1 | 0 | 0 | 0 |  |
| `interpreter` | java | 1 | 0 | 0 | 0 |  |
| `interpreter` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `interpreter` | typescript | 1 | 0 | 0 | 0 |  |
| `iterator` | java | 1 | 0 | 0 | 0 |  |
| `iterator` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `iterator` | typescript | 1 | 0 | 0 | 0 |  |
| `mediator` | java | 1 | 0 | 0 | 0 |  |
| `mediator` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `mediator` | typescript | 1 | 0 | 0 | 0 |  |
| `memento` | java | 1 | 0 | 0 | 0 |  |
| `memento` | python | 2 | 1 | 0 | 0 |  |
| `memento` | typescript | 1 | 0 | 0 | 0 |  |
| `observer` | java | 1 | 0 | 0 | 0 |  |
| `observer` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `observer` | typescript | 1 | 0 | 0 | 0 |  |
| `persistence.unit-of-work` | javascript | 1 | 1 | 0 | 0 |  |
| `persistence.unit-of-work` | python | 2 | 1 | 1 | 0 | uow-preclear |
| `persistence.unit-of-work` | typescript | 1 | 1 | 0 | 0 |  |
| `prototype` | java | 1 | 0 | 0 | 0 |  |
| `prototype` | python | 2 | 1 | 0 | 0 |  |
| `prototype` | typescript | 1 | 0 | 0 | 0 |  |
| `proxy` | java | 1 | 0 | 0 | 0 |  |
| `proxy` | python | 2 | 0 | 1 | 1 | dead-implementation, early-exit-guard |
| `proxy` | typescript | 1 | 0 | 0 | 0 |  |
| `resilience.exception-retry` | javascript | 1 | 1 | 0 | 0 |  |
| `resilience.exception-retry` | python | 2 | 1 | 0 | 0 |  |
| `resilience.exception-retry` | typescript | 1 | 1 | 0 | 0 |  |
| `singleton` | java | 1 | 0 | 0 | 0 |  |
| `singleton` | python | 1 | 1 | 0 | 1 | cfg-adjacency |
| `singleton` | typescript | 1 | 0 | 0 | 0 |  |
| `state` | java | 1 | 0 | 0 | 0 |  |
| `state` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `state` | typescript | 1 | 0 | 0 | 0 |  |
| `strategy` | java | 1 | 0 | 0 | 0 |  |
| `strategy` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `strategy` | typescript | 1 | 0 | 0 | 0 |  |
| `template-method` | java | 1 | 0 | 0 | 0 |  |
| `template-method` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `template-method` | typescript | 1 | 0 | 0 | 0 |  |
| `visitor` | java | 1 | 0 | 0 | 0 |  |
| `visitor` | python | 2 | 0 | 1 | 0 | dead-implementation |
| `visitor` | typescript | 1 | 0 | 0 | 0 |  |

## Combinaciones que no se anuncian como soportadas

Esto distingue lenguajes del frontend de cobertura anunciada por patrón. Ruby está presente en el frontend y no tiene celdas anunciadas por estas queries. Estas ausencias quedan visibles; no prueban que el patrón sea imposible en el lenguaje.

| Patrón raíz | Lenguajes del frontend fuera del ámbito anunciado |
|---|---|
| `abstract-factory` | csharp, ruby |
| `adapter` | ruby |
| `architecture.adapted-continuation-wrapper` | cpp, csharp, java, ruby, rust |
| `architecture.batch-work-queue` | cpp, go, ruby, rust |
| `architecture.cache-aside` | cpp, go, ruby, rust |
| `architecture.continuation-wrapper` | cpp, csharp, java, ruby, rust |
| `architecture.dependency-injection` | ruby |
| `architecture.dispatch-table` | cpp, csharp, java, ruby, rust |
| `architecture.read-through-cache` | cpp, go, ruby, rust |
| `architecture.subclass-factory` | cpp, csharp, go, java, ruby, rust |
| `bridge` | javascript, ruby |
| `builder` | ruby |
| `chain-of-responsibility` | ruby |
| `command` | ruby |
| `composite` | ruby |
| `decorator` | ruby |
| `facade` | cpp, csharp, ruby |
| `factory-method` | csharp, javascript, ruby |
| `flyweight` | go, javascript, ruby |
| `interpreter` | javascript, ruby |
| `iterator` | ruby, rust |
| `mediator` | ruby |
| `memento` | ruby |
| `observer` | ruby |
| `persistence.unit-of-work` | cpp, go, ruby, rust |
| `prototype` | go, ruby |
| `proxy` | ruby |
| `resilience.exception-retry` | go, ruby, rust |
| `singleton` | ruby |
| `state` | ruby |
| `strategy` | ruby |
| `template-method` | ruby |
| `visitor` | go, javascript, ruby |

## No implementado

- `persistence.unit-of-work#transactional-change-set`: No executable query; not counted as a tested negative.

## Causas revisadas

**cfg-adjacency — Control tolerante a ruido (19 casos).** La query exige CFG_ENTRY o aristas adyacentes/caminos de longitud fija; una asignación independiente no cambia el algoritmo. Usar alcanzabilidad con efectos relevantes.

**named-construction-flow — Builder con campos de construcción Go/Rust (6 casos).** FINAL_MEMBER_INPUT existe y finish retorna el producto, pero faltan enlaces de valor/argumento para la construcción por campos. Extender RESULT/RETURNS_VALUE y binding de inicializadores nombrados.

**array-element-type — Composite TypeScript T[] (3 casos).** El campo conserva native_type Node[] y la llamada ITERATED_CALL, pero no se emite ELEMENT_TYPE. Normalizar arrays sufijados con el mismo modelo de elemento que Array<T>.

**rust-wildcard-summary — Ruido Rust con let _ (8 casos).** let _ = 1 + 2 marca BINDING_FLOW_STATUS unmodeled-write y RETURN_FLOW_STATUS nonlocal-or-nested-write. Descartar un valor puro no escribe un binding retenido; modelar wildcard explícito.

**declaration-only-copy — Firma de constructor de copia (1 casos).** La query language-copy acepta el constructor X(const X&) por declaración aunque el cuerpo sólo lance una excepción. Es límite de firma, no contradicción de su claim; falta variante de implementación.

**dead-implementation — Evidencia sintáctica inalcanzable (17 casos).** Los métodos retornan antes del algoritmo. Hechos históricos de llamadas/campos permanecen; una firma estructural puede aceptarlos. Separar firma de prueba de implementación alcanzable.

**remote-response-join — Remote Proxy desconectado (7 casos).** El resultado del transporte no se une al argumento del decoder. Unir origen por ocurrencia de llamada.

**adapter-request-join — Adapter input ajeno (3 casos).** Dos lecturas indexadas no se unen al parámetro request; índices de constantes satisfacen el claim de adaptación del input.

**builder-construction-join — Builder sucesor ajeno (3 casos).** HAS_CALL elige logging y RETURNS_NEW otra construcción; exigir argumentos de la construcción retornada.

**once-api — CAS no equivale a once (1 casos).** updateAndGet(prev -> new Config()) crea y publica cada vez. Resolver API/contrato de retención y diferenciar publicación de número de ejecuciones.

**memento-return-join — Snapshot descartado (1 casos).** HAS_CALL encode no exige devolver encode(state), ni conectar el argumento de decode al snapshot recibido. El claim actual es más débil que Memento completo.

**async-await-requirement — Async Iterator sin await (1 casos).** async def con yield implementa async generator sin await explícito. FN de variante; la raíz lo encuentra por generator.

**go-yield-polarity — Polaridad de yield Go (1 casos).** La salida al devolver true contradice el protocolo de range-function; el claim permite indebidamente ambas polaridades.

**generic-name-identity — Identidad genérica por string (1 casos).** Unrelated<T> cambia el conteo de Bridge por el spelling de un parámetro de ámbito ajeno. Requiere identidad scoped y relación real de variantes.

**facade-composition — Composición no prueba subsistemas (1 casos).** La firma acepta composición aritmética sin frontera de subsistemas. Mantener query base y evidencia adicional de Facade.

**decorator-identity — Wrapper transparente (1 casos).** Forwarding exacto no demuestra responsabilidad añadida; la firma débil describe un wrapper, no el algoritmo completo de Decorator.

**copy-use-vs-return — Copia descartada (1 casos).** Se observa copy(self) pero no una operación que entregue un clon; separar usage y retorno de copia.

**early-exit-guard — Guarda temprana equivalente (2 casos).** CONDITIONAL_DELEGATION requiere que la llamada esté dentro de if; no reconoce salida temprana equivalente. Usar control efectivo.

**structural-object-provider — Familia por literales de objeto (1 casos).** La variante structural-families exige CLASS para ambos proveedores; objetos con slots equivalentes no están representados.

**static-policy-field — Política estática sin campo (1 casos).** P::apply() elige algoritmo por tipo sin objeto/campo. La query actual exige composición mediante campo.

**base-alias — Alias de base de subclase (1 casos).** BASE_VALUE no sigue Alias=Base. Añadir origen de la expresión base con reaching definitions y estado supported.

**finally-overrides-continue — Finally anula retry (1 casos).** finally break impide el continue efectivo. El caveat de explicit-continue declara este límite léxico.

**di-historical-input — Dependencia sobrescrita (1 casos).** La raíz/variante object-assignment conserva asignación histórica; retained-object ofrece un contrato distinto más fuerte.

**dispatch-historical-value — Handler sobrescrito (1 casos).** La escritura original del handler persiste aunque table[key] se cambie a None antes de usarla. Falta versión de contenido.

**command-context-join — Contexto enviado a otra llamada (3 casos).** audit(context) completa la query aunque el comando iterado recibe 0. Unir la invocación de esa iteración con el argumento.

**eventbus-payload-join — Payload enviado a otro registro (1 casos).** La invocación con payload pertenece a otro loop/registro. Unir bucket, iteración, valor invocado y argumento.

**continuation-rebind — Continuación sustituida (1 casos).** La captura apunta al binding recibido, pero su valor ya fue reemplazado. Falta origen vigente del callable.

**adapter-discards-handler — Adaptador devuelve escalar (1 casos).** adapt(handler) devuelve 42 en el cuerpo visible. Pasar handler al adaptador no demuestra que lo retenga ni devuelva un callable.

**queue-preclear — Lote descartado antes de consumir (1 casos).** La colección se vacía antes de la iteración; clear después de ella sólo prueba orden léxico. Falta versión de lote.

**uow-preclear — Cambios descartados antes de commit (1 casos).** Commit reemplaza el mapa por lotes vacíos. No se conecta la versión registrada con la persistida.

**flyweight-replacement — Pool que siempre reemplaza (1 casos).** Lookup y write no prueban creación sólo en miss ni reutilización. Claim actual declara esta limitación.

**module-write-count — Claim written once no comprobado (1 casos).** Dos escrituras visibles matchean. La query no restringe el conteo de escrituras del slot compartido.

**lazy-construction-join — Construcción no publicada (1 casos).** La construcción se descarta y la escritura guardada almacena None. Falta ligar construcción a escritura y delegación.

Replay completo: 11.724 s dentro del runner. Incluye construcción/consulta de muchos grafos pequeños; no mide escala de repositorio, cache de proyecto ni compilación de los programas. CPython valida la sintaxis de los snippets Python; los otros lenguajes tienen parsing Tree-sitter, sin certificación de typechecking.
