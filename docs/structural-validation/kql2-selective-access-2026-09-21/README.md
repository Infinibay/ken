# Validación de accesos selectivos

Baseline: copia del runtime ya refactorizado, con sus cambios sin commit, en
`/tmp/ken-opt4-baseline-20260921/ken`. `source-sha256.json` identifica las dos
implementaciones modificadas antes y después. No hay cambios de esquema, corpus
ni catálogo en esta ronda.

- `comparison.json`: dos muestras por proceso para cada consulta completa.
- `before-*.json` / `after-*.json`: resultados completos de la segunda muestra.
- `micro-*.json`: tres repeticiones de selección vectorial y acceso puntual SQL.
- `gate-*-latency.json`: corpus, preparación, parámetros y resultado del gate.
- `gate-*-latency-0.json`: resultados del lote y estado de cada patrón.

## Consultas completas

Desde la raíz del repositorio:

```sh
kql_comparison=docs/structural-validation/kql2-selective-access-2026-09-21/compare.py
PYTHONPATH=/tmp/ken-opt4-baseline-20260921:. .venv/bin/python "$kql_comparison" before-strategy100 strategy100
PYTHONPATH=src:. .venv/bin/python "$kql_comparison" after-strategy100 strategy100
```

Los otros casos son `sdk26` e `interpreter100`. El script prepara el índice fuera
del cronómetro y desactiva la caché de resultados. `semantic_result` normaliza
identificadores de compilación y orden de pruebas; se normaliza también la ruta
al catálogo de la copia temporal. Se preservan el contenido de evidencia, los
bindings y la incertidumbre. Todos los hashes coinciden.

| Caso | Segunda muestra antes | Segunda muestra después |
|---|---:|---:|
| Strategy / 100 | 6,977 s | 5,513 s |
| Catálogo / 26 | 6,265 s | 5,694 s |
| Interpreter / 100 | 3,533 s | 3,507 s |

## Accesos individuales

`micro.py LABEL` usa el mismo corpus preparado para las operaciones y un vector
determinista de 20.000 filas para las selecciones. La preparación queda fuera del
cronómetro. Las tres repeticiones y los checksums se conservan en los JSON.

| Trabajo | Mediana antes | Mediana después |
|---|---:|---:|
| 2.000 selecciones por identidad y tipo | 3,801 s | 0,0152 s |
| 100 accesos a operaciones por identidad | 1,342 s | 0,00135 s |

Estos factores no se extrapolan al lote completo.

## Gate de 100 archivos

```sh
PYTHONPATH=src:. .venv/bin/python -m examples.bench.kql2_latency /tmp/ken-sub5-corpus-100 /tmp/ken-sub5-baseline-cache --warmups 0 --repeats 1
```

Se ejecutó primero con el `PYTHONPATH` del baseline y después con el candidato,
guardando cada reporte antes de ejecutar el siguiente. Ambos usaron el índice
preparado, un proceso nuevo y cero calentamientos de consultas. Salida 1 esperada:
el objetivo exige los 23 patrones completos en menos de 5 s para todo el lote.

Antes: 71,077 s, diez consultas incompletas. Después: 64,699 s, ocho incompletas.
Abstract Factory y Strategy pasan a completar dentro del presupuesto individual.
El objetivo global sigue pendiente. Un diagnóstico separado de Observer agotó
40 s en ambas versiones de la primera etapa; no se usa como comparación de una
consulta completa.

## Regresión

Resultado final: **13.202 pruebas pasan y 10 tienen fallo esperado**, en 418,75 s.
Los dos módulos modificados pasan mypy. Se añadieron 18 pruebas de selección y
acceso puntual. El log y el resumen están en `pytest.log` y `validation.json`
del directorio de validación.

```sh
PYTHONPATH=src:. .venv/bin/pytest tests/kql2 tests/structural -o addopts='' -q --tb=short
PYTHONPATH=src:. .venv/bin/mypy src/ken/kql2/exploration/records.py src/ken/structural_store/graph_index.py --follow-imports=silent --disable-error-code=import-untyped
```

El chequeo de tipos omite únicamente el aviso por dependencias sin stubs, ya
existente para FlatBuffers. No se modifica la configuración de mypy del proyecto.

La versión final conserva el entorno completo de BODY. Se descartó una
proyección experimental porque rompía 109 casos; al retirarla, los 109 vuelven a
pasar. Todos los archivos `after-*` y `gate-after-*` corresponden a la versión
corregida, con sólo las dos optimizaciones de almacenamiento.
