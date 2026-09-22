# Segunda ronda: optimización de búsquedas KQL2

**El objetivo global de menos de 5 segundos sigue sin cumplirse.** El gate de
100 archivos devuelve `passed=false`: 67,167 s medidos, con 10 reglas de 23
interrumpidas por el presupuesto diagnóstico de 5 s por regla. Ese valor **no es
el tiempo de un escaneo completo**. Índice reutilizado, perfilador desactivado y
caché de resultados desactivada.

Se conserva la misma muestra del [manifiesto anterior](../corpus.json): 100
archivos Python/TypeScript, 963.991 bytes y 29.423 líneas. No se seleccionaron
archivos en función de su tiempo de búsqueda.

## Comparación A/B completa para cargas acotadas

| Carga | Baseline, segunda ejecución | Candidato, segunda ejecución | Completa | Misma semántica y evidencia |
|---|---:|---:|---|---|
| Abstract Factory, 100 archivos | 13,253 s | 1,694 s | Sí | Sí |
| Catálogo de 23 patrones, 26 archivos TypeScript | 8,265 s | 6,760 s | Sí | Sí |

La primera ejecución con índice preparado también se registra: 18,390 frente a
6,266 s para Abstract Factory; 9,122 frente a 7,910 s para el catálogo TypeScript.
Por eso la mejora de Abstract Factory es 7,8 veces **en la segunda ejecución**,
no una promesa de 1,7 s al iniciar un proceso. El criterio global sigue siendo
el lote de los 23 patrones sobre los 100 archivos.

El baseline es una copia del worktree inmediatamente anterior a esta ronda en
`/tmp/ken-opt2-baseline-20260920/ken`, no Git HEAD. El worktree ya tenía cambios de
la intervención anterior y otros cambios locales. Los mismos archivos e índices
se usaron en ambos procesos; `use_result_cache=False` y `profile=False` en ambos.

La comparación del SDK normaliza sólo el prefijo de instalación en `rule.source`:
el catálogo copiado vive en `/tmp`, y el actual en `src/ken`. No se normalizan las
rutas del código analizado, la incertidumbre ni la evidencia. Los JSON originales
quedan archivados para revisar esa única diferencia de ubicación.

- Huella normalizada SDK: `e163bf84f0272dde9b813bdc7f92f69f504860e851e64e19b5b0246328b2f9a2`.
- Huella Abstract Factory: `c8ffb1a6967b264da369dfec9fb4d7f00c6ebc6796fe225c6175861182e8afa6`.

El A/B precede al último cambio de lectura de inicializadores. El gate final ya
incluye esa lectura local; después se añadió la liberación explícita de sus
callbacks al cerrar el ejecutor. Las pruebas finales cubren ambos cambios.

## Diagnóstico del lote completo

Persisten timeouts en Builder, Command, Interpreter, Iterator, Mediator, Memento,
Observer, Singleton, Strategy y Template Method. Abstract Factory y Facade, que
agotaban el presupuesto en la ronda anterior, completan ahora la ejecución
medida. El calentamiento de este gate todavía agotó el presupuesto de Abstract
Factory: todas las corridas se conservan y no se oculta ese caso.

El perfil de Abstract Factory muestra el efecto concreto del índice por nombre
y aridad: el cruce de 5.135 filas contra 280 métodos pasa a producir 8.786
candidatos, frente a las 1.437.800 combinaciones potenciales. Facade completa en
2,212 s en el diagnóstico caliente con perfilador, con 84.631 hechos examinados;
ese perfil no es el gate global ni una comparación A/B sin perfilador.

Los diagramas y restricciones de seguridad semántica están en el
[documento de diseño](../../../design/kql2/join-optimization-2026-09-20.md).

## Artefactos y reproducción

- `*-timings.json`: ambas ejecuciones A/B, completitud, índice reutilizado,
  caché de resultados desactivada y hashes.
- `baseline-*.json` y `candidate-*.json`: respuestas completas del segundo run.
- `abstract100-profile.json`, `facade100-profile.json`: trabajo por operador.
- `gate-100.json`, `gate-100-outcomes.json`: gate, manifiesto y resultados.
- `engine-changes.patch`: ocho archivos de producción contra la copia inicial
  de esta ronda; incluye archivos nuevos y no mezcla cambios previos.
- `validation.json`: comandos y alcance de la verificación.

```bash
PYTHONPATH=.:src .venv/bin/python -m examples.bench.kql2_latency \
  /tmp/ken-sub5-corpus-100 /tmp/ken-sub5-baseline-cache \
  --warmups 1 --repeats 1
```

El comando terminó con **exit 1**, como corresponde. Los tests diferenciales
cubren atributos ausentes, modalidad `may`, comparación literal frente a
alternativas, booleanos, barreras de planificación, cancelación, receptores y
parentesco entre callables. Los tests de inicializadores conservan los casos
de enlaces faltantes, construcciones anidadas y lambdas con otro owner.

La suite amplia de KQL2 y structural pasó después del primer cambio de postings.
Una suite focalizada posterior cubre el conjunto final de modificaciones y las
matrices de equivalencia entre memoria y almacenamiento nativo. Los siete módulos
auxiliares modificados pasan mypy; `relational.py` conserva los siete diagnósticos
preexistentes de la copia baseline. No se atribuyen a esta intervención como
errores nuevos ni se considera limpio el gate de tipos de ese archivo.

Los tres diagramas nuevos se revisaron textualmente; no se ejecutó un renderizador
Mermaid. Las cifras corresponden al equipo local y a las cargas declaradas.
