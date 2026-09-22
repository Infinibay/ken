# KQL2: validación del objetivo de latencia

**Resultado: no aprobado.** Se confirmó que los 5 segundos se refieren a buscar
con el índice preparado. Se midió sin perfilador y sin caché de resultados.

La continuación está documentada en la [segunda ronda](round-2/README.md), con
comparaciones A/B nuevas. Este registro conserva las mediciones de la primera.

| Muestra | Medición caliente | Completa | Objetivo <5 s |
|---|---:|---|---|
| 100 archivos Python/TypeScript | 76,773 s | No: 12 de 23 reglas agotaron su presupuesto | No |
| 26 archivos TypeScript, repetición 1 | 8,874 s | Sí | No |
| 26 archivos TypeScript, repetición 2 | 9,062 s | Sí | No |

Los 76,773 s son un diagnóstico **interrumpido**, no el tiempo de un escaneo
completo. Se aplicó un techo de 5 s por regla para hacer finita la prueba; el
criterio de aceptación exige menos de 5 s para el lote entero, con `complete=true`.
No se puede interpretar su lista vacía de hallazgos como ausencia de patrones.

La apertura del índice y comprobación de archivos de la corrida final de 100
archivos sumó unos 74 ms. Esa fase ya no explica la latencia del lote.

Con el mismo harness con perfilador de la auditoría original, la corrida caliente
de 26 archivos pasó de unos 15,16 s a **8,126 s**, completa y con idéntica huella de
evidencia (`sdk26-profile-final.json`). Es una mejora de esa muestra, no una
validación del objetivo para 100 archivos.

## Artefactos

- `corpus.json`: selección fijada antes de optimizar; 100 archivos, 963.991 bytes,
  29.423 líneas, con ruta de origen, tamaño y hash por archivo.
- `final-100-gate.json`: fases de preparación, manifiesto y resultado del gate.
- `final-100-outcomes.json`: respuesta final y estado/presupuesto de cada regla.
- `sdk26-gate.json`: dos mediciones completas tras calentamiento.
- `original-cold-diagnostic.json`: engine previo, incluyendo adquisición fría;
  no comparable directamente con los tiempos de búsqueda caliente.
- `sql-prototype-exploration-{0,1}.json`: prototipo retirado de producción; no
  mostró una mejora consistente y ambas corridas quedaron incompletas.
- `typing.json`: comparación de diagnósticos de BODY con la copia del worktree
  anterior a estos cambios. Ese archivo ya tenía errores de tipos.
- `validation.json`: comandos ejecutados y resultados de verificación.
- `engine-changes.patch`: sólo los siete archivos del engine modificados en
  esta intervención, contra la copia inicial del worktree, sin mezclar los
  cambios locales que ya existían respecto de Git HEAD.

La huella de hallazgos **y evidencia**, normalizada igual que en la auditoría
original, permanece igual en los 26 archivos:

`68a0c59874b83214fb0420e3369829f7041447a8e21b8eac9c3706193efdd5cd`.

El gate usa otra huella más amplia, incluyendo completitud e incertidumbre por
regla; no deben compararse entre sí ambas clases de hashes. La muestra de 100
archivos no tiene todavía una corrida completa para certificar esa equivalencia.

## Reproducir

El origen es el checkout local de Codex registrado en `corpus.json`; no se editó.
El corpus de esta sesión está en `/tmp/ken-sub5-corpus-100`, con rutas relativas
originales. Para recrearlo desde ese checkout, copiar las rutas del manifiesto
y verificar sus SHA-256 antes de medir. No sustituir archivos que hayan cambiado
silenciosamente ni elegir archivos según su tiempo de ejecución.

Desde la raíz de Ken:

```bash
PYTHONPATH=.:src .venv/bin/python -m examples.bench.kql2_latency \
  /tmp/ken-sub5-corpus-100 /tmp/ken-sub5-baseline-cache \
  --warmups 1 --repeats 1
```

Ese comando terminó con **exit 1**, como corresponde. Sin `--repeats 1`, el
gate exige tres mediciones. El índice se prepara fuera del cronómetro, pero
la API completa de búsqueda se mide. `--profile` es sólo para diagnóstico;
el caso de aceptación por defecto no lo activa.

## Verificación de cambios

La suite amplia `tests/kql2 tests/structural tests/test_gitignore_filter.py` pasó
antes del último ajuste para compartir contextos entre reglas. Después de ese
ajuste pasaron nuevamente las pruebas focalizadas de recursos, BODY, columnas
nativas, límites de caché, planificación y bypass de resultados. Cubren:

- Misma evidencia en alternativas de hechos y conservación de modalidad `may`.
- Dominio independiente pospuesto sin perder bindings; barreras dependientes y
  scopes que no deben moverse.
- BODY con argumentos distintos reutiliza contexto pero no resultados.
- Consultas distintas comparten preparación y conservan presupuestos/callbacks
  separados; un ejecutor cerrado no queda retenido por el lote.
- Scope con gitignore heredado, ancestros ignorados y symlinks.
- Bypass de resultados con índice reutilizado y sin perfilador.

Mypy pasó para los seis módulos de servicio/planificación/caché modificados y
para el benchmark ejecutado como módulo con `MYPYPATH=src:.`. BODY no tiene un
gate de tipos limpio: 392 diagnósticos en la copia previa y 389 tras el cambio,
sin nuevas clases/cantidades de mensajes normalizados en la comparación.

`git diff --check` pasó para los archivos editados en esta intervención. El
worktree completo conserva avisos de espacios previos en documentación y en
`experiments/text-graph-engine/prototype/qa/feed.py`, fuera de este trabajo.

Los diagramas Mermaid se revisaron textualmente; no se ejecutó un renderizador
Mermaid. Las medidas se hicieron en el equipo local y no constituyen una garantía
para cualquier conjunto de 100 archivos: el manifiesto fija esta carga concreta.
