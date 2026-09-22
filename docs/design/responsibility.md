# Quién hace qué: hipótesis de responsabilidad

Busca directamente en la documentación de **módulos, clases, métodos y funciones**.
No necesita findings guardados ni consultas previas. El ejemplo de guardar findings
era una responsabilidad del código de Ken, no la fuente de esta búsqueda.

```sh
ken tools who "Who provides SQLite connection helpers?" --path src/ken
ken tools who "Who resolves non-relative JS/TS imports via tsconfig paths and workspace names?" --path src/ken
ken tools who "Who fsyncs every segment touched since the last flush?" --path src/ken
```

Estos ejemplos recuperan, respectivamente, el módulo `src/ken/db.py`, la clase
`AliasResolver` y el método `VectorStore.flush`, con su propia documentación.

La interfaz empieza por una pregunta que haría quien está programando:

```sh
ken tools who "Who stores reusable findings?" --path src/ken
ken tools who "¿Quién guarda las memorias entre sesiones?" \
  --path src/ken --hypotheses "Store or update a reusable finding"
```

Desde este checkout puede usarse `.venv/bin/python -m ken` en lugar de `ken`.
Para otro proyecto: `ken tools --path /proyecto who "..." --path src`.
El primer `--path` elige el proyecto; el segundo acota la búsqueda dentro de él.
La misma herramienta está registrada en MCP:

```python
ken_who(
    question="¿Quién guarda las memorias entre sesiones?",
    path="src/ken",
    hypotheses=["Store or update a reusable finding"],
    limit=3,
)
```

No modifica código ni memorias, ejecuta funciones del proyecto ni llama a un LLM.
Usa el modelo de embeddings configurado para el proyecto. Un MCP abierto antes
del cambio necesita reiniciarse para anunciar la herramienta nueva.

También observa llamadas y sitios cuyo valor se retorna usando KQL 2, con
alcance por archivo y presupuesto compartido de 3 s. `verify=False` permite
omitir esa observación. Conserva los scores documentales y declara el alcance:
una relación de llamadas no demuestra por sí misma la responsabilidad escrita
en el docstring. El formato compacto incluye el resumen estructural; `full=True`
retiene las consultas, sus resultados y los snapshots. Ver [contratos de código](source-contract-tools.md).

## Contrato de respuesta

Por defecto la respuesta es compacta: estado, candidatos con tipo, ubicación,
score heurístico y una cita documental breve (hasta 200 caracteres), elegida por
su relación con la consulta. Omite campos vacíos, hashes y diagnóstico interno.
En módulos no repite la ruta también como nombre de símbolo.

```sh
ken tools who "Who provides SQLite connection helpers?" --path src/ken
ken tools who "Who provides SQLite connection helpers?" --path src/ken --full
```

`--full` (MCP: `full=True`) conserva el formato detallado anterior: documentación,
contribuciones de todos los razonadores, supuestos, huella SHA-256 de la fuente,
cobertura y la llamada `ken_read` necesaria para inspeccionar cada candidato.
El formato no modifica la búsqueda, el ranking ni las puntuaciones.

Ambos formatos conservan ambigüedad y contraevidencia. El compacto sólo añade
`assumed_formulation` si la respuesta depende de una reformulación propuesta,
`caveats` cuando hay condiciones, negaciones, delegación u otros supuestos
específicos, y `uninspected_candidates` cuando algunos candidatos no pudieron
comprobarse (por ejemplo, por límites de lectura o fuentes ausentes).
En `unknown` aclara que falta evidencia, sin afirmar que el código no existe.

`kind` distingue `module`, `class`, `method` y `function`;
En `--full`, `source.documentation_kind` identifica el docstring utilizado. Un módulo se
identifica por su ruta en `symbol`. No se atribuye automáticamente la documentación
de un módulo a sus funciones ni la de una clase a todos sus métodos. El campo
`coverage.findings_used=false` hace explícito que no se consultaron memorias.

Una respuesta puede ser `candidates`, `ambiguous` o `unknown`. Si los dos primeros
candidatos tienen puntuaciones próximas se conserva `ambiguous`, incluso con
`limit=1`. `unknown` significa evidencia insuficiente dentro de lo inspeccionado;
no demuestra que esa responsabilidad no exista en el proyecto.

Las formulaciones de `hypotheses` son **supuestos de equivalencia** aportados por
el llamador: «guardar memorias» podría significar «persist findings». No se
traducen silenciosamente ni se presentan como hechos demostrados. Se usa la
mejor formulación por candidato, sin sumar votos por repetir paráfrasis. Una
contradicción encontrada con otra formulación no desaparece al elegir la mejor.

## Razonadores y confianza

| Razonador | Aporte | Límite |
|---|---|---|
| `DocumentationReasoner` | Similitud y términos de la documentación; avisos de negación, condiciones y delegación | La documentación puede estar equivocada; los avisos son patrones superficiales, no una interpretación gramatical general. |
| `NameReasoner` | Correspondencia entre la responsabilidad y el nombre del símbolo | Un nombre puede ser engañoso. |
| `CallsReasoner` | Expresiones de llamada Python con nombres relacionados, ligadas a líneas reales | No resuelve el destino ni acredita que se ejecute; aporta contexto, no un voto de implementación. |

`score` (`confidence.score` en `--full`) es un número de 0 a 0,95 para ordenar
candidatos. **No es una probabilidad de acierto**: el formato compacto declara
`score_kind=heuristic_not_probability`; el completo conserva `calibrated=false`
y `probability=null`. La política
`responsibility-evidence/1` toma el máximo de documentación, nombre ponderado
por 0,65 y soporte de extensiones ponderado por 0,5. Añade una pequeña coincidencia
entre documentación y nombre (0,05 por su mínimo). Una posible negación limita
la puntuación a 0,2; una condición o delegación, a 0,55. La documentación combina
similitud y coincidencia léxica mediante máximo, porque no son pruebas independientes.
No se usa una multiplicación bayesiana con una independencia inventada.

La probabilidad calibrada requiere preguntas etiquetadas, separación entre ajuste
y evaluación, y medir cuántas respuestas de cada intervalo de confianza son
correctas. Los doce ejemplos iniciales no justifican convertir el score en porcentaje.

## Fuentes y alcance

La recuperación reutiliza el índice de símbolos y de intención documental de Ken,
incluidas las entradas `module_docstring` que no están ligadas a un símbolo.
Se filtra por ruta antes de ordenar y se excluyen tests por defecto
(`include_tests=True` / `--include-tests` los incluye).

Se comprueban hasta 40 candidatos, en hasta 24 archivos, con 2 MiB por archivo.
Los candidatos se resuelven otra vez sobre el contenido actual, sin ejecutar
código. Python usa el AST para obtener el docstring completo y las llamadas
propias de la función; no atribuye las llamadas de funciones internas a la externa.
Los otros lenguajes usan el extracto documental del parser existente y no tienen
todavía este razonador de llamadas. Se recalcula la similitud con la documentación
actual de los candidatos. Un símbolo eliminado, una fuente ilegible o un error de
parseo se informa como cobertura incompleta y no se cita como evidencia vigente.

El índice inicial suele contener sólo la primera línea del docstring: puede omitir
símbolos nuevos o conceptos presentes exclusivamente más adelante. Releer candidatos
no corrige una omisión anterior de recuperación. Un docstring largo se limita a
12.000 caracteres para el embedding y 900 en la respuesta completa. La cobertura
en `--full` siempre declara `exhaustive=false`.

**Esta primera herramienta usa razonadores heurísticos de evidencia de código.**
No ejecuta todavía el parser lingüístico del engine experimental ni sus programas
de pruebas sobre los docstrings. No reutiliza la base de ternas. Un razonador que
aporte pruebas del grafo podrá sumarse al mismo contrato, conservando el alcance
y los supuestos de esas pruebas. Interpretar una frase no acredita por sí mismo
que el código la implemente.

## Responsabilidades y extensión

- `model.py`: pregunta interpretada, símbolo observado y contribución de evidencia.
- `retrieval.py`: selección de candidatos en el índice.
- `source.py`: observación del código actual, con límites de lectura.
- `reasoners.py`: contribuciones y política de puntuación.
- `assessment.py`: combinación de formulaciones, condiciones y ambigüedad.
- `report.py`: proyección compacta o completa del mismo resultado.
- `service.py`: coordinación del caso de uso; MCP y CLI comparten este servicio.

Un razonador implementa `assess(inquiry, symbol) -> tuple[Evidence, ...]` y se
compone mediante `who(..., reasoners=(...))`. Puede aportar soporte, contexto o
contraevidencia sin cambiar el coordinador. El soporte positivo de una extensión
tiene peso conservador hasta validar su comportamiento. Repetir evidencia no
incrementa la confianza.

[Resultados de las consultas y pruebas](../validation/responsibility-2026-09-21/README.md).

[Validación específica de módulos, clases, métodos y funciones](../validation/responsibility-2026-09-21/code-documentation/README.md).

La verificación KQL comparte ahora una adquisición entre los candidatos y sus
imports explícitos. `responsibility_map` añade cadenas de llamadas y roles
candidatos de entrada, coordinación y ejecución, con bases e incertidumbres.
`ken_related(..., relation="impact")` sigue usos de resultados y
`relation="roles"` permite inspeccionar un símbolo sin búsqueda documental.
Estos roles son hipótesis estructurales y no modifican el score de responsabilidad.
Ver [interfaz y límites de inspección](code-inspection.md).
