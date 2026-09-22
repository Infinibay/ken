# Ronda 3: evidencia diferida y atributos proyectados

Base del runtime: `ae82f39`, copiada antes de esta ronda en
`/tmp/ken-opt3-baseline-20260921/ken`. Ambos runtimes usan los mismos TOML del
catálogo local; esos TOML no fueron modificados por esta optimización.

`comparison.json` compara búsquedas completas con índice preparado y sin caché de
resultados. Cada proceso hizo dos búsquedas secuenciales; se compara la segunda.
Las pruebas de pytest no corrieron en paralelo con las mediciones. `compare.py`
conserva el procedimiento exacto y las rutas de los corpus de esta sesión.

- Interpreter sobre 100 archivos: **11,416 → 3,356 s**, 3,40 veces más rápido.
- Los 23 GoF sobre los 26 archivos del SDK: **7,124 → 6,094 s**, 1,17 veces más rápido.
- Hallazgos, evidencia e incertidumbre tienen el mismo hash normalizado en cada
  comparación. La normalización elimina los hashes de compilación en referencias
  a consultas, normaliza la ruta temporal del catálogo e ignora el orden de
  listas de diccionarios; conserva su contenido completo.

Los JSON sin sufijo `timings` contienen la respuesta original de la segunda
búsqueda, antes de esa normalización. `candidate-source-sha256.json` identifica
los módulos medidos.

## Gate de 100 archivos

Comando reproducible desde la raíz del repositorio:

```sh
PYTHONPATH=.:src .venv/bin/python -m examples.bench.kql2_latency \
  /tmp/ken-sub5-corpus-100 /tmp/ken-sub5-baseline-cache --warmups 1 --repeats 1
```

**No aprobado**. Calentamiento: 71,764 s. Medición: **66,958 s**, con índice
preparado y caché de resultados desactivada; 9 patrones agotan el presupuesto:
Builder, Command, Iterator, Mediator, Memento, Observer, Singleton, Strategy y
Template Method. Interpreter ya completa su búsqueda en este lote.

Estos tiempos parciales no son latencias de un escaneo completo, ni demuestran
una mejora global frente a otro lote incompleto. El objetivo sigue siendo los
23 patrones completos sobre los mismos 100 archivos en menos de cinco segundos.

La arquitectura, los límites y tres diagramas Mermaid están en
[evidencia diferida](../../../design/kql2/late-materialization-2026-09-21.md).

`validation.json` registra la suite final: **13.170 aprobados, 10 xfail esperados**,
sin errores de mypy en siete módulos auxiliares. La batería amplia anterior
había expuesto un fallo del planificador ya reproducible en la base; se corrigió
la frontera de proyección y se repitió la suite completa satisfactoriamente.
