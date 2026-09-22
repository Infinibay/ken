# Validación del refactor de interfaces KQL

Comparación contra la versión de evidencia diferida del 21 de septiembre,
incluidos sus cambios todavía sin commit. No es una comparación contra
`ae82f39`, que precede esa optimización.

- `comparison.json`: ambas ejecuciones de cada proceso, tiempos y hashes.
- `before-*.json` / `after-*.json`: resultados completos de la segunda ejecución.
- `source-sha256.json`: identidad de los módulos antes y después del refactor.
- `validation.json`: resultados de pruebas, chequeo de tipos y compatibilidad.
- `compare.py`: preparación fuera del cronómetro; consultas sin caché de resultados.

Se usaron los mismos corpus e índices que en
`../kql2-latency-2026-09-20/round-3/`. El cambio de método en `Fact` modifica la
revisión conservadora del grafo: se preparó cada versión antes de medirla.

```sh
kql_comparison=docs/structural-validation/kql2-runtime-refactor-2026-09-21/compare.py
PYTHONPATH=/tmp/ken-refactor-baseline-20260921:. .venv/bin/python "$kql_comparison" ken-refactor-before-interpreter100 interpreter100
PYTHONPATH=/tmp/ken-refactor-baseline-20260921:. .venv/bin/python "$kql_comparison" ken-refactor-before-sdk26 sdk26
PYTHONPATH=src:. .venv/bin/python "$kql_comparison" ken-refactor-after-interpreter100 interpreter100
PYTHONPATH=src:. .venv/bin/python "$kql_comparison" ken-refactor-after-sdk26 sdk26
```

Los comandos parten de la raíz del repositorio. La copia local usada como
baseline está en `/tmp/ken-refactor-baseline-20260921/ken`; los hashes anteriores
permiten comprobar que no se está comparando contra otra revisión.

Las mediciones se hicieron secuencialmente, antes de ejecutar la suite completa.
Interpreter: 3,392 → 3,224 s. GoF/SDK: 5,798 → 5,896 s. Todos los resultados son
completos, con acierto de índice y hashes semánticos idénticos. Dos muestras por
variante no permiten atribuir pequeñas diferencias temporales al refactor.

Pruebas y tipos:

```sh
PYTHONPATH=src:. .venv/bin/pytest tests/kql2 tests/structural -o addopts='' -q --tb=short
PYTHONPATH=src:. .venv/bin/mypy src/ken/structural/relational*.py src/ken/structural/model.py src/ken/structural_store/graph_records.py --follow-imports=silent
```

Los 14 módulos pasan el chequeo focalizado. También se ejecutó mypy completo
contra ambas versiones: 461 → 454 errores, ninguno nuevo; los siete eliminados
estaban en el ejecutor. Los errores restantes pertenecen a otros módulos.

La suite completa terminó correctamente: **13.184 passed, 10 xfailed** en
414,84 s. Se añadieron 14 casos que verifican los contratos de extensión,
proyección, evidencia y vida útil del perfil.

El gate global de 23 patrones/100 archivos no se volvió a ejecutar en este
refactor. El último resultado sigue siendo 66,96 s y nueve consultas incompletas;
no se afirma que se haya alcanzado el objetivo global de menos de 5 s.
