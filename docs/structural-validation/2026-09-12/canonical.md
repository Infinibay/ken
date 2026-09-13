# Resultados con el catálogo canónico

Esta ejecución reemplaza las firmas antiguas como ruta por defecto. Los 23 conceptos
GoF tienen queries canónicas y fixtures en Python, Java y TypeScript. **Los resultados
en repositorios reales siguen siendo candidatos estructurales, no una certificación
de intención GoF.** La matriz controlada no permite publicar precisión global.

## Proyectos locales

| Proyecto | Alcance | Archivos | Generadores Python (oráculo AST) | Candidatos Iterator | Búsquedas incompletas |
|---|---|---:|---:|---:|---|
| infinidev | `src/` | 485 | 13/13 | 3 | ninguna |
| SENN | `senn_byte/` | 275 | 31/31 | 26 | Mediator: límite de 100.000 estados |

En infinidev se excluyen 10 funciones decoradas de contextlib: conservar `yield`
en el IR no significa exponer una instancia Iterator al usuario del código.
SENN conserva 24 funciones generadoras y 2 tipos cursor como candidatos. El oráculo
AST ahora se compara con la consulta independiente `syntax.generators`, que incluye
todas las funciones con yield, sin las exclusiones propias del catálogo GoF.

Los resultados por patrón son:

| Patrón | infinidev | SENN |
|---|---:|---:|
| abstract-factory | 0 | 0 |
| adapter | 0 | 0 |
| bridge | 0 | 0 |
| builder | 0 | 2 |
| chain-of-responsibility | 0 | 0 |
| command | 0 | 0 |
| composite | 0 | 0 |
| decorator | 0 | 0 |
| facade | 2 | 2 |
| factory-method | 2 | 2 |
| flyweight | 1 | 0 |
| interpreter | 0 | 0 |
| iterator | 3 | 26 |
| mediator | 0 | inconcluso |
| memento | 0 | 0 |
| observer | 0 | 0 |
| prototype | 0 | 0 |
| proxy | 0 | 0 |
| singleton | 0 | 0 |
| state | 0 | 0 |
| strategy | 0 | 0 |
| template-method | 0 | 2 |
| visitor | 0 | 0 |

`0` significa que ninguna variante habilitada encontró evidencia en ese alcance.
No demuestra ausencia del patrón. `inconcluso` tampoco significa cero; es presupuesto
agotado. Se mantienen los límites por raíz: 100.000 estados, 500.000 filas,
1.000 resultados y 5 segundos. Cada dependencia comparte el presupuesto de su raíz.

## Casos revisados y límites que permanecen

- **Iterator en infinidev:** `iterate_messages_tool_calls` recorre mensajes y produce
  llamadas; es un uso de iteración válido. `best_effort`, `_locked` y otros scopes
  de contextlib dejan de ser candidatos Iterator.
- **Observer:** desaparecen los falsos positivos revisados en `add_evidence`,
  `format_for_developer` y limpieza de archivos. El catálogo exige registrar un
  parámetro en la misma colección que se notifica. No cubre todavía todas las
  suscripciones de colas/event buses: cero resultados no demuestra que no existan.
- **Builder en infinidev:** desaparece `EvidenceReviewEngine._ground`, que era
  coordinación de helpers con variables locales. El director ahora requiere que
  los pasos escriban campos del builder, no cualquier variable local.
- **Builder en SENN:** `PagedPermanentStore.begin_train` construye una vista mutable
  del estado; `PermanentReplayLedger.reserve` construye una reserva. Ambos satisfacen
  la relación entre estado actualizado y objeto retornado, pero **no los considero
  confirmaciones de un Builder GoF** sin evidencia adicional de construcción por
  etapas. Son candidatos residuales, y pueden ser falsos positivos de intención.
- **Factory Method en infinidev:** los métodos `check` de `PromptBehaviorChecker`
  y `StochasticChecker` sobrescriben un slot y construyen `Verdict`. La forma coincide,
  pero su propósito es comprobar comportamiento, no necesariamente un diseño Factory
  Method deliberado. Se conserva como candidato, no como prueba del patrón.
- **Flyweight en infinidev:** `WebRuntime.session` reutiliza sesiones por clave bajo
  un lock. Es un cache de objetos compartidos; no se ha probado la separación entre
  estado intrínseco/extrínseco necesaria para afirmar un Flyweight clásico.

La corrección sintáctica de las consultas y sus tests no elimina esta ambigüedad.
El informe no presenta el número de matches como número de patrones correctamente usados.

## Repositorios públicos

También se ejecutó el catálogo nuevo sobre Werkzeug, Blinker y Zap.
Werkzeug incluye 52 archivos Python y un JavaScript de debugger; la primera ejecución
histórica sólo incluía Python, por lo que no se comparan sus tiempos como benchmark
controlado. La regla Observer antigua confundía agregación de diccionarios y cierre
de archivos con notificación; esos casos concretos no pasan la consulta nueva.
Blinker todavía omite Signal: la suscripción mediante diccionarios, referencias débiles
y el generador intermediario exige flujo adicional. Zap mantiene las omisiones de
Core embebido y multiCore sobre slice: los 23 detectores no están certificados para Go.

## Evidencia y reproducción

Los JSON `*-canonical.json` contienen consultas ejecutadas, resultados, estados de
completitud, estadísticas, manifiestos con SHA-256 y hashes del motor y TOML utilizados.
Los proyectos locales tienen cambios respecto de HEAD: el commit solo no basta para
reproducirlos. Se analizaron sus archivos sin modificarlos ni ejecutar su código.
Los tiempos de construcción (aprox. 16 s y 21 s en esta ejecución) no son un benchmark
controlado; hubo otros procesos concurrentes y no se usó cache persistente del servicio.

```sh
.venv/bin/python examples/bench/validate_structural_repo.py ../infinidev --prefix src/ --output /tmp/infinidev.json
.venv/bin/python examples/bench/validate_structural_repo.py ../SENN --prefix senn_byte/ --output /tmp/senn.json
.venv/bin/python -m pytest -ra
```

- [infinidev: resultados y manifiesto](infinidev-canonical.json)
- [SENN: resultados y manifiesto](senn-canonical.json)
- [Werkzeug](werkzeug-canonical.json), [Blinker](blinker-canonical.json), [Zap](zap-canonical.json)
- [Cobertura de los 23 GoF y 28 variantes](../../gof-coverage.md)

Verificación final: **1.357 tests aprobados**, mypy sin errores en 86 módulos,
wheel y sdist construidos, instalación aislada con `uv tool install` y smoke del
catálogo/consulta nombrada. Las 34 variantes de diseño restantes siguen marcadas
como pendientes; no forman parte de esa cobertura implementada.
