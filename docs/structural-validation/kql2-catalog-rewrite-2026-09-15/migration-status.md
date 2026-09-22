# Estado de migración del catálogo

Generado por `examples/bench/catalog_authoring_inventory.py`. Las cifras cuentan consultas raíz, variantes y operaciones por separado.

Revisada significa revisión conductual acotada, no ausencia de FP/FN. Composición requiere revisar también sus dependencias. La columna legado indica `legacy_query` fuera de las consultas actuales.

| Patrón | Con edge/walk | Sin query | Fuente por revisar | Composición | Revisadas | Legado |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| abstract-factory | 0 | 0 | 1 | 1 | 2 | no |
| adapter | 0 | 0 | 4 | 1 | 1 | sí |
| bridge | 0 | 0 | 3 | 1 | 2 | sí |
| builder | 0 | 0 | 3 | 2 | 3 | sí |
| chain-of-responsibility | 0 | 0 | 3 | 1 | 0 | sí |
| command | 0 | 0 | 8 | 1 | 0 | no |
| composite | 0 | 0 | 3 | 1 | 2 | sí |
| decorator | 0 | 0 | 0 | 1 | 6 | no |
| facade | 0 | 0 | 0 | 1 | 2 | no |
| factory-method | 0 | 0 | 0 | 1 | 3 | no |
| flyweight | 0 | 0 | 3 | 1 | 0 | sí |
| interpreter | 0 | 0 | 4 | 1 | 0 | sí |
| iterator | 0 | 0 | 7 | 1 | 3 | sí |
| mediator | 0 | 0 | 4 | 1 | 2 | sí |
| memento | 0 | 0 | 3 | 1 | 0 | sí |
| observer | 0 | 0 | 4 | 1 | 3 | sí |
| prototype | 0 | 0 | 1 | 2 | 3 | sí |
| proxy | 0 | 0 | 4 | 1 | 0 | sí |
| singleton | 0 | 0 | 2 | 3 | 3 | sí |
| state | 0 | 0 | 3 | 1 | 1 | sí |
| strategy | 0 | 0 | 2 | 1 | 3 | sí |
| template-method | 0 | 0 | 0 | 1 | 4 | no |
| visitor | 0 | 0 | 4 | 1 | 0 | sí |
| architecture.adapted-continuation-wrapper | 0 | 0 | 0 | 0 | 1 | no |
| architecture.batch-work-queue | 0 | 0 | 0 | 0 | 3 | no |
| architecture.cache-aside | 0 | 0 | 2 | 1 | 0 | no |
| architecture.continuation-wrapper | 0 | 0 | 0 | 0 | 1 | no |
| architecture.dependency-injection | 0 | 0 | 0 | 1 | 3 | no |
| architecture.dispatch-table | 0 | 0 | 2 | 1 | 0 | no |
| resilience.exception-retry | 0 | 0 | 2 | 1 | 0 | no |
| architecture.read-through-cache | 0 | 0 | 2 | 0 | 0 | no |
| architecture.subclass-factory | 0 | 0 | 1 | 1 | 0 | no |
| persistence.unit-of-work | 0 | 1 | 2 | 1 | 0 | no |

## Entradas que todavía usan operadores internos
