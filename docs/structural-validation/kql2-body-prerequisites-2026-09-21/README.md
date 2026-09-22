# Validación de requisitos previos de BODY

La referencia es `/tmp/ken-opt5-baseline-20260921/ken`, copia del runtime tras la
ronda de accesos selectivos y antes de esta ronda. Incluye las refactorizaciones
anteriores sin commit. `source-sha256.json` identifica los módulos antes y
después; un hash nulo indica un archivo nuevo.

## Regresión

**13.272 pruebas pasan y 10 tienen fallo esperado**, en 399,25 s. Se añadieron
70 pruebas. `pytest.log` conserva la salida completa y `validation.json` resume
el comando, los resultados y el chequeo de tipos.

```sh
PYTHONHASHSEED=0 PYTHONPATH=src:. .venv/bin/python -m pytest tests/kql2 tests/structural -o addopts='' -q --tb=short
```

Seis módulos modificados pasan mypy con `--follow-imports=silent` y
`--disable-error-code=import-untyped`. El módulo histórico `body.py` tiene deuda
de tipos: pasa de 389 a 383 errores existentes, sin diagnósticos nuevos tras
normalizar los números de línea. El detalle está en
`body-typing-comparison.json`; no se cambiaron las reglas de mypy del proyecto.

## Comparaciones completas

`compare.py LABEL CASE` ejecuta hasta dos búsquedas en un proceso, con el índice
preparado fuera del cronómetro, sin caché de resultados y con un presupuesto
individual de 120 segundos. Los casos son `sdk26`, `strategy100`, `iterator100`
y `observer100`. SDK comprende los 23 GoF; los casos de 100 archivos consultan
el patrón indicado por su nombre. Una consulta incompleta se registra y no se
repite. Las comparaciones finales usan `PYTHONHASHSEED=0` en ambas versiones.

```sh
kql_comparison=docs/structural-validation/kql2-body-prerequisites-2026-09-21/compare.py
PYTHONHASHSEED=0 PYTHONPATH=/tmp/ken-opt5-baseline-20260921:. .venv/bin/python "$kql_comparison" before-iterator100 iterator100
PYTHONHASHSEED=0 PYTHONPATH=src:. .venv/bin/python "$kql_comparison" after-iterator100 iterator100
```

Las mediciones se ejecutan secuencialmente, separadas de la suite de pruebas.
La comparación semántica incluye bindings, evidencia e incertidumbre, con
normalización del orden de pruebas, identificadores de compilación y ruta al
catálogo de la copia temporal. Las muestras y hashes quedan en `comparison.json`
y los resultados originales de la segunda muestra en `before-*.json` y
`after-*.json`.

## Aceptación de 100 archivos

El gate exige que los 23 GoF terminen en menos de 5 segundos para todo el lote,
con exactamente 100 archivos e índice preparado. Se usa un proceso nuevo y
cero calentamientos de consultas. Los presupuestos individuales son de 5
segundos: agotar cualquiera produce un resultado incompleto y falla el gate.

```sh
PYTHONHASHSEED=0 PYTHONPATH=src:. .venv/bin/python -m examples.bench.kql2_latency /tmp/ken-sub5-corpus-100 /tmp/ken-sub5-baseline-cache --warmups 0 --repeats 1
```

`gate-*-latency.json` conserva los parámetros, el corpus con sus hashes y el
resultado global. `gate-*-latency-0.json` conserva cada resultado de patrón.
Las consultas incompletas no se usan para afirmar equivalencia de resultados
completos ni como tiempos de un escaneo terminado.

## Resultados finales

| Consulta completa | Antes | Después |
|---|---:|---:|
| Observer / 100 archivos | 119,869 s | 15,248 s |
| Iterator / 100 archivos | 16,198 s | 10,408 s |
| Strategy / 100 archivos | 5,343 s | 5,167 s |
| 23 GoF / 26 archivos | 5,264 s | 4,994 s |

Se informa la segunda ejecución de cada proceso. Las dos muestras de las cuatro
consultas terminan completas; los hashes de resultados, evidencia e
incertidumbre coinciden entre versiones y repeticiones. El SDK tiene dos
hallazgos e Iterator tres; Strategy y Observer no tienen hallazgos positivos en
este corpus. La suite diferencial también cubre fixtures positivos.

Observer resulta 7,86 veces más rápido e Iterator reduce su tiempo un 35,7 %.
Estas mejoras corresponden a consultas completas, sin caché de resultados.

El gate de los 23 GoF sobre 100 archivos **sigue sin pasar**: 65,380 s y nueve
patrones incompletos antes; 63,438 s y ocho después. Strategy pasa a completar
dentro de su presupuesto individual en el lote. Siguen incompletos Builder,
Command, Iterator, Mediator, Memento, Observer, Singleton y Template Method.
Las catorce consultas completas en ambas versiones conservan resultados e
incertidumbre. El objetivo exige el lote completo por debajo de 5 s, no sólo
cada consulta por separado; estos tiempos parciales no satisfacen ese objetivo.
