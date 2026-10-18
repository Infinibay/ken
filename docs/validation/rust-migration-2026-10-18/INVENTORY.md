# Inventario inicial de la migración a Rust

Fecha: 2026-10-18. Fuente: `baseline.json`, capturada del worktree, no sólo de HEAD.

Este inventario identifica la superficie que hay que migrar. No acredita paridad ni pruebas aprobadas. Los comandos anidados, esquemas MCP y dependencias requieren captura dinámica en M0.

## `src/ken`

409 archivos Python; 76926 líneas físicas.

| Área | Archivos Python | Líneas |
| --- | ---: | ---: |
| `(root)` | 37 | 13082 |
| `bench` | 15 | 1030 |
| `checks` | 12 | 1468 |
| `code_reasoning` | 31 | 5436 |
| `common_ast` | 7 | 828 |
| `daemon` | 5 | 1845 |
| `embedder` | 7 | 1788 |
| `inspection` | 11 | 1221 |
| `knowledge` | 5 | 702 |
| `kql2` | 83 | 17289 |
| `mcp` | 3 | 1906 |
| `parsers` | 24 | 3912 |
| `ranker` | 9 | 3342 |
| `reasoning` | 5 | 526 |
| `responsibility` | 9 | 957 |
| `retrieval` | 52 | 5639 |
| `skills` | 4 | 312 |
| `structural` | 60 | 12146 |
| `structural_store` | 30 | 3497 |

## `tests`

538 archivos Python; 70075 líneas físicas.

| Área | Archivos Python | Líneas |
| --- | ---: | ---: |
| `(root)` | 55 | 13206 |
| `bench` | 13 | 758 |
| `code_reasoning` | 8 | 2213 |
| `common_ast` | 9 | 702 |
| `kql2` | 115 | 14653 |
| `parsers` | 23 | 1382 |
| `ranker` | 18 | 2861 |
| `retrieval` | 56 | 4923 |
| `structural` | 241 | 29377 |

## Declaraciones visibles en la entrada CLI

`install`, `reinstall`, `status`, `rank`, `explain`, `search-files`, `search-symbols`, `bench`, `reembed`, `vectors`, `default-model`, `models`, `remember`, `forget`, `findings`, `recall`, `related-findings`, `file-findings`, `findings-graph`, `rebuild`, `serve`, `hook`, `session-start`, `session-end`, `user-prompt`, `stop`, `tool-call`, `mcp`, `tools`, `uninstall`, `kql2`, `code-check`, `code-find`, `retrieval`

Inventario parcial por AST de `src/ken/cli.py`; incluye subcomandos de hooks. Las rutas KQL2, structural, retrieval y code reasoning registran opciones adicionales en otros módulos.

## Herramientas MCP declaradas

`ken_find`, `ken_query`, `ken_rule`, `ken_check`, `ken_code_find`, `ken_code_check`, `ken_who`, `ken_read`, `ken_related`, `ken_rank`, `ken_reason_record`, `ken_reason`, `ken_calculate`, `ken_recall`, `ken_remember`

## Evidencia y límites

- SHA-256 por archivo de fuentes, recursos, pruebas y contratos en `baseline.json`.
- Se incluyen recursos de modelos y esquema SQL; no se capturan pesos descargados, estado privado de `.ken/`, secretos ni bases del usuario.
- Los cambios existentes siguen sin commitear; el branch no los convierte en un snapshot recuperable.
- Antes de comparar resultados se comprobarán las huellas del alcance usado; una diferencia exige declarar otra revisión de base.
- CI actual: Python 3.12 en Linux/macOS, pytest, mypy y smoke del wheel. No se ha ejecutado la suite completa en esta preparación.
