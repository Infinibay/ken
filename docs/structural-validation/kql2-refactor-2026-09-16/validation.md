# Validación de la refactorización KQL2 — 2026-09-16

Se trabajó sobre el worktree existente, conservando sus cambios previos en
parser, compilador, semántica, BODY, catálogo y experimentos. Las copias usadas
como baseline contienen ese estado local previo, no solamente `HEAD`.

## Comportamiento

| Verificación | Resultado |
|---|---|
| Suite KQL2 inicial | Sin fallos, antes de modificar el parser/ejecutor |
| KQL2 final + tests nuevos del dispatcher relacional | **1.071 passed**, 16,42 s |
| Suite estructural posterior | **11.604 passed, 10 xfailed, 1 failed**, 394,15 s |
| Parser anterior vs actual, durante la suite KQL2 | **2.284 entradas válidas** con AST idéntico; **327 inválidas** con el mismo mensaje, código y span |
| Ruff, reglas `F,I,UP035`, archivos de esta refactorización | Sin errores |
| Ruff format, archivos de esta refactorización | 24 archivos conformes |
| Mypy KQL2 + módulos relacionales | Sin errores en los módulos refactorizados; permanecen 406 errores previos en otros tres archivos |
| Whitespace del diff propio | Sin errores; había un blank line al final de un documento de catálogo modificado previamente |

Los tests nuevos verifican equivalencia de profiling y presupuestos,
independencia entre snapshots, límite de la caché de propiedades, lecturas SQL
evitadas, 1.500 pasos sin recursión de joins, cierre de iteradores, barreras de
planificación, extensión del dispatcher, métricas anidadas y bypass de resultados
cacheados al perfilar. Los tests existentes ejercitan ambos backends, KQL1,
catálogo, bibliotecas, artefactos, BODY, errores de cálculo y lógica de unknown.

La comparación del parser cargó la copia anterior bajo otro nombre de módulo y
comparó todos los campos del AST, no solamente la aceptación del texto. También
comparó `ParseError.message`, `code` y `span` en entradas inválidas.

### Fallo preexistente confirmado

`tests/structural/test_dispatch_table.py::test_dispatch_table_avoids_unrelated_method_parameter_cross_product`
falló tanto en la ejecución inicial de la suite estructural como en la posterior:

- `max_states=2000`.
- `states=2001`, `rows_examined=1321`, `unknown=['budget:max_states']` en ambos casos.
- El catálogo `dispatch-table.toml` ya tenía cambios locales antes de esta tarea.

No se aumentó el presupuesto, no se marcó el test como xfail ni se modificó la
regla del catálogo para encubrirlo. Su corrección queda pendiente fuera de esta
refactorización de arquitectura.

### Tipado preexistente

La revisión inicial de KQL2 reportó 423 errores: 17 en `syntax/parser.py`,
395 en `body.py`, 6 en `graph.py` y 5 en `source_patterns.py`. Los 17 del parser
quedaron resueltos al separar las producciones y sus variables locales. Los 406
restantes no cambiaron; no se agregaron exclusiones ni `ignore_errors`.

## Rendimiento

[Reporte completo con muestras y hashes](benchmark.json).

31 repeticiones por workload, alternando el orden entre implementaciones en el
mismo proceso, 500 clases y 500 métodos. El benchmark verifica igualdad de
resultados y, en el backend indexado, de estados, scans y unknown antes de medir.

| Workload | Mediana previa (ms) | Mediana actual (ms) | Variación |
|---|---:|---:|---:|
| Parser, 120 parses | 14,623 | 14,032 | −4,0% |
| Lookup por nombre + método | 0,0575 | 0,0514 | −10,6% |
| Join clase/método | 12,740 | 9,273 | −27,2% |
| Join + filtros | 15,414 | 12,318 | −20,1% |
| Propiedades compartidas | 14,449 | 14,015 | −3,0% |
| Join de grafos | 7,565 | 7,758 | **+2,5%** |

La mejora mayor viene de evitar lecturas SQL de propiedades que ya están en los
nodos y reutilizar el contexto de expresiones. La separación del dispatcher de
grafos no produjo una mejora en este workload: se observó un pequeño aumento.
Estas cifras no establecen un speedup general del buscador. No incluyen
adquisición de proyectos, parsing fuente, cachés de resultados ni cargas BODY.

Reproducir la implementación actual:

```console
.venv/bin/python examples/bench/kql2_refactor.py --repeats 31 --output /tmp/kql2.json
```

Para comparar con otro estado, guardar antes sus módulos `syntax/parser.py`,
`execution.py` y `structural/relational.py` como `parser.py`, `execution.py` y
`relational.py` dentro de un directorio y pasarlo con `--baseline-dir`. Los
hashes de las copias utilizadas en esta medición están en el reporte.

[Arquitectura y guía de extensiones](../../design/kql2/engine-architecture.md).
