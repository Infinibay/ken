# KQL2 pipeline audit — 2026-09-20

Informe principal, con siete diagramas Mermaid:
[recorrido y optimizaciones](../../design/kql2/performance-audit-2026-09-20.md).

Se auditó el worktree existente, sin modificar el engine, el catálogo ni sus
tests. Los scripts de esta carpeta ejecutan diagnósticos y prototipos limitados
al proceso de benchmark. No son optimizaciones integradas en producción.

## Inputs y metodología

- Python 3.12.9, macOS 26.6.2, arm64.
- Ken HEAD `ff36cb6932da60f441010f8e0e02e288bc8c72be`, con cambios locales previos.
- Fingerprint del engine:
  `001d8f3828c53deb651a71cb89f46627ca3eb23b854618f5acafb8791d60df70`.
- Codex HEAD `4fa7e82274bd70e145da05c66117865f7615e61d`, ámbito
  `sdk/typescript`: 26 archivos soportados, 5.098 entidades y 94.197 hechos.
- El estado del ámbito mostraba una carpeta `.ken` previa sin seguimiento;
  está excluida por el walker. Los benchmarks escribieron su caché en
  `/tmp/ken-kql2-audit-20260920`, no en el checkout de Codex.
- Hashes del catálogo y del manifiesto en [probes.json](probes.json).

Catálogo completo: seis llamadas secuenciales, alternando `indexed` y
`exploration`, con perfil de operadores y sin límite temporal. `profile=True`
evita la caché de resultados. Los backends compartieron índice: sólo la primera
llamada indexed fue fría para el índice. No se vació la caché del sistema
operativo. Las repeticiones 1 y 2 de cada backend son las comparaciones calientes.

Las seis terminaron con dos findings y el mismo hash de bindings, evidencia e
incertidumbre. `semantic_result` canoniza el orden de listas de diccionarios y
prefijos de hashes de compilación; no reduce la comprobación al número de matches.
Las comparaciones de hash de BODY verifican también los contadores de cada patrón.

## Resultados guardados

| Archivo | Contenido |
|---|---|
| [sdk-runs.json](sdk-runs.json) | Seis tiempos, outcomes, fases, cache hits y estado de completitud. |
| [sdk-warm-operators.json](sdk-warm-operators.json) | Perfiles completos de la última repetición caliente de ambos backends. |
| [probes.json](probes.json) | Parser, compilación fría/caliente y comparación exacta de manifiestos. |
| [hash-probe.json](hash-probe.json) | Cuatro ejecuciones ABBA: hash original y memoizado, con misma semántica y trabajo. |
| [cprofile.json](cprofile.json) | Principales funciones por tiempo inclusivo y propio; corrida diagnóstica separada. |
| [full-iterator.json](full-iterator.json) | Iterator en snapshot grande previo, 5 s, con perfil de operadores y cProfile. |
| [full-iterator-no-operator-profile.json](full-iterator-no-operator-profile.json) | Mismo diagnóstico sin perfil de operadores; cProfile sigue activado. |
| [validation.json](validation.json) | Comprobaciones sobre los artefactos de esta auditoría. |

Las medias calientes fueron 16,845 s indexed y 15,162 s híbrido. El experimento
de hash pasó de 15,185 s a 13,486 s de media, reducción del 11,2%. El prototipo
de manifiesto pasó de 1,573 s a 0,00629 s de mediana en la fase aislada. No se
midió la combinación de ambas mejoras; sus porcentajes no deben sumarse.

El cProfile completo tardó 40,26 s frente a unos 15 s sin cProfile. Sus tiempos
sirven para atribución, no para una comparación de velocidad. Los perfiles de
operadores son inclusivos; no sumar padre e hijos.

El snapshot grande se conserva en
`/tmp/ken-codex-perf/native-full-v11/query-index.sqlite`, IR `1.85.0`, con
2.620.444 entidades y 47.154.730 hechos. No se volvió a adquirir ni a verificar
contra el checkout actual. Con perfil de operadores, Iterator informó 4.998,7 ms
de planificación. Sin ese perfil, cProfile atribuyó aproximadamente 5,000 s a
`choose_next` y 4,992 s a `_count_rows`. Ambas consultas agotaron el presupuesto
con dos estados y cero hechos examinados por el executor. Esto confirma el
coste de planificación; no demuestra resultados completos ni ausencia de matches.

## Reproducir

Desde la raíz de Ken, usando un directorio nuevo para el primer benchmark:

```sh
PYTHONPATH=.:src .venv/bin/python -m examples.bench.catalog_exploration \
  ../codex /tmp/ken-kql2-audit-repro --scope sdk/typescript --repeats 3 --backend both

PYTHONPATH=.:src .venv/bin/python \
  docs/structural-validation/kql2-pipeline-audit-2026-09-20/probe.py \
  ../codex /tmp/kql2-probes.json

PYTHONPATH=.:src .venv/bin/python \
  docs/structural-validation/kql2-pipeline-audit-2026-09-20/hash_probe.py \
  ../codex /tmp/ken-kql2-audit-repro /tmp/kql2-hash-probe.json
```

Los scripts aceptan `--scope`. El experimento del hash calienta la compilación
fuera de los tiempos, usa la misma caché de datos y restaura `BodyPattern.__hash__`
tras cada corrida. Conserva el valor del hash estructural original; el mapa
diagnóstico retiene el objeto, tiene un límite de 4.096 entradas y vive una sola
corrida. No altera igualdad, roles, relaciones, presupuestos ni evidencias.

El prototipo de walker compara el manifiesto completo, incluidos bytes y
omisiones, con el recorrido actual. Esa igualdad se probó en el ámbito del SDK;
no sustituye las pruebas de ignores/symlinks necesarias para integrarlo.

Para obtener un cProfile, preservar primero los tiempos del benchmark: el harness
reutiliza nombres de salida en cada invocación.

```sh
cp /tmp/ken-kql2-audit-repro/comparison.json /tmp/kql2-baseline-comparison.json
PYTHONPATH=.:src .venv/bin/python -m cProfile -o /tmp/kql2-profile.pstats \
  -m examples.bench.catalog_exploration ../codex /tmp/ken-kql2-audit-repro \
  --scope sdk/typescript --repeats 1 --backend exploration
```

Para repetir el diagnóstico grande se necesita el snapshot local previo:

```sh
PYTHONPATH=.:src .venv/bin/python \
  docs/structural-validation/kql2-pipeline-audit-2026-09-20/snapshot_probe.py \
  /tmp/ken-codex-perf/native-full-v11/query-index.sqlite /tmp/kql2-full-iterator.json

PYTHONPATH=.:src .venv/bin/python \
  docs/structural-validation/kql2-pipeline-audit-2026-09-20/snapshot_probe.py \
  /tmp/ken-codex-perf/native-full-v11/query-index.sqlite \
  /tmp/kql2-full-iterator-no-operator-profile.json --no-operator-profile
```

La caché nueva de este trabajo quedó disponible para repetir mediciones. No se
borraron índices previos. No se ejecutó una suite de regresión de producción:
no se cambiaron sus archivos. Las verificaciones realizadas son los recorridos
completos, las comparaciones diferenciales de los prototipos y las comprobaciones
de los artefactos indicadas en `validation.json`.
