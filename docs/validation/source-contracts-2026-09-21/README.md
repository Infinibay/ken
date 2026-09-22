# Verificación de contratos de código

Se implementaron `ken_rule` y `ken_check`, su integración con las tools existentes
y comprobaciones opcionales desde los hooks de edición/final de turno.

## Evidencia funcional

- [Resultado sobre código real de Ken](result.json): copia exacta de
  `src/ken/checks/report.py`, con SHA-256 del original. Una mutación deliberada
  cambia el retorno del parámetro original por un objeto vacío. El contrato pasa,
  falla tras la mutación y vuelve a pasar al restaurarlo. Se detecta regresión y
  resolución; la memoria queda `stale` y el scheduler produce un aviso.
- [Llamadas y respuestas](events.json): definiciones, validación, recibos,
  búsquedas, relaciones y memoria del mismo recorrido. Los IDs pertenecen al
  proyecto temporal de la evaluación, eliminado al terminar.
- [MCP instalado](installed-mcp.json): `ken mcp` publica 12 herramientas,
  incluyendo `ken_rule` y `ken_check`. Una llamada real a `ken_find` sobre el
  checkout recupera `query_view` y respeta el formato compacto.
- [Tests de integración y regresión](tests.xml): 155 tests correctos. Incluyen
  un cliente MCP stdio real, CLI, validación positiva/negativa, familia de bugs,
  memoria sin replay, cambios de regla/engine/catálogos, archivos nuevos o
  borrados, carreras, symlinks, aislamiento de imports y eventos del daemon.
- [Tests de KQL 2](kql2-tests.xml): suite del lenguaje y sus rutas de ejecución.

El contrato de la demostración acredita la existencia de un retorno del parámetro
seleccionado. No acredita todas las ramas, una condición `full` particular ni
equivalencia de programas. Los ejemplos elegidos no miden precisión general de
un detector de bugs. No se ejecutaron sesiones nuevas de un modelo para esta
validación; el protocolo MCP y las tools se ejercitaron directamente.

## Reproducción

```sh
.venv/bin/python scripts/evaluate_source_contracts.py \
  --output /tmp/ken-source-contracts

.venv/bin/python -m pytest \
  tests/test_checks.py tests/test_check_tools.py tests/test_check_automation.py \
  tests/test_responsibility.py tests/test_justified_memory.py \
  tests/test_mcp_schema.py tests/test_mcp_read.py tests/test_hook.py \
  tests/test_daemon_helpers.py tests/test_daemon_state.py \
  tests/test_daemon_rank_mcp.py tests/test_daemon_http_resilience.py \
  -q -o addopts=''

.venv/bin/python -m pytest tests/kql2 -q -o addopts=''

.venv/bin/python -m mypy src/ken/checks src/ken/responsibility src/ken/knowledge \
  --follow-imports=silent
```

Mypy pasó para los 25 archivos de esos paquetes; Ruff F y la comprobación de
whitespace también pasaron. No se afirma que todo el repositorio tenga mypy limpio
ni que se haya ejecutado su suite completa.

[Uso, arquitectura y límites](../../design/source-contract-tools.md).
