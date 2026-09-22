# Consultas de responsabilidad con evidencia y supuestos

2026-09-21. Se implementó `ken_who` / `ken tools who` y se ejecutaron doce
consultas reales contra el índice de este proyecto. La herramienta es útil para
localizar responsabilidades documentadas y exponer ambigüedad. La evaluación
también mostró fallos de recuperación en español y ante una paráfrasis inglesa.
**No mide una probabilidad calibrada ni demuestra comprensión general del código.**

## Uso probado

```sh
.venv/bin/python -m ken tools who \
  "¿Quién guarda las memorias entre sesiones?" \
  --path src/ken --hypotheses "Store or update a reusable finding"
```

Devuelve `remember`, en `src/ken/memory.py`, como primer candidato con score
heurístico 0,85, el docstring actual, la huella de la fuente y los supuestos.
La equivalencia de la formulación inglesa se declara; no es una traducción
certificada. `confidence.probability` permanece en `null` y `calibrated=false`.

El [contrato](../../design/responsibility.md) describe límites, razonadores,
política de puntuación y extensión. Esta herramienta usa documentación, nombres
y expresiones de llamada del AST. Todavía no ejecuta el parser lingüístico ni
los programas de prueba del engine experimental sobre los docstrings.

## Consultas y resultados

Modelo real configurado: `ken/static-qwen3-r512-v2`. Cada consulta se hizo en un
proceso nuevo mediante `python -m ken tools who`, con alcance `src/ken`, tres
candidatos y tests excluidos. Se usó el índice vivo, sin fijar un commit o detener
el watcher. Las fuentes candidatas se comprobaron contra el código actual.

| Caso | Responsable esperado | Resultado |
|---|---|---|
| Guardar findings reutilizables, inglés | `remember` | Primero, 0,850 |
| Registrar funciones como tools MCP/CLI | `ken_tool` | Primero, 0,717 |
| Decodificar parámetros objeto y arrays | `_tool_json_object` | Primero, 0,857 |
| Confinar rutas al proyecto | `resolve_project_path` | Primero, 0,750 |
| Puntuar propósito documental | `doc_intent_scores` | Primero, 0,855 |
| Extraer fragmentos de símbolos/rangos | `file_snippets` | Segundo; empate con su wrapper, `ambiguous` |
| Guardar memorias, español | `remember` | `unknown` |
| Guardar memorias, español + hipótesis inglesa | `remember` | Primero, 0,850 |
| Registrar herramientas, español | `ken_tool` | Candidatos incorrectos de confianza débil, `ambiguous` |
| Registrar herramientas, español + hipótesis inglesa | `ken_tool` | Primero, 0,858 |
| Convertir argumentos JSON en diccionarios, paráfrasis inglesa | `_tool_json_object` | `unknown` |
| Lanzar cohetes a Marte, control fuera del dominio | Ninguno previsto | `unknown` |

Las seis primeras preguntas fueron redactadas cerca del vocabulario de los
docstrings: son comprobaciones favorables de funcionamiento, no evaluación ciega.
El esperado apareció primero en cinco y entre los tres primeros en seis. Las dos
consultas españolas fallaron sin reformulación y acertaron con las hipótesis
inglesas suministradas. La paráfrasis inglesa falló: la forma «JSON arguments
into dictionaries» no recuperó suficiente evidencia de «Decode object parameters».

No se ajustaron los pesos para hacer pasar esos fallos. Sirven para separar tres
problemas: recuperar el candidato, interpretar su documentación y acreditar su
responsabilidad real. Esta primera versión aporta la evidencia para investigarlos;
no resuelve automáticamente los tres.

La mediana observada fue **1,24 segundos**, incluyendo arranque del proceso. Es
una medición local de una ejecución por pregunta, sin control de caché o carga.
No hay una comparación de ahorro de tokens ni agentes Codex adicionales en esta
ronda: son llamadas al CLI de Ken.

## Pruebas del contrato

**159 pruebas pasaron**, incluidas 24 específicas de la nueva herramienta y las
de MCP, lectura, CLI, búsqueda, intención documental y memoria relacionadas.
Se probaron:

- Paridad del registro SDK MCP y CLI, argumentos obligatorios e hipótesis como lista.
- Docstrings completos de métodos Python, ubicación y fuente actual después de cambios.
- Negaciones, condiciones, delegación y supuestos que no desaparecen al cambiar de paráfrasis.
- Ambigüedad conservada con `limit=1`, y `unknown` sin convertirlo en prueba de ausencia.
- Símbolos eliminados, errores de parseo, archivos ausentes y enlaces fuera del proyecto.
- Exclusión de tests, alcance antes del ranking y límites del contrato de entrada.
- Llamadas de funciones internas no atribuidas a la externa; llamadas observadas sin resolver su ejecución.
- Repetir evidencia no aumenta el score; añadir un razonador no exige cambiar el coordinador.

Los tests de contrato usan un embedder determinista; las doce consultas usan el
modelo real. Mypy pasó en los siete archivos del paquete y Ruff no encontró
errores F. La comprobación de tipos no es un pase del repositorio completo.

Artefactos: [resultados por pregunta](results.json), [ejecución resumida](run.txt),
[JUnit](tests.xml). Cada respuesta íntegra está en su archivo `<caso>.json`, por
ejemplo [con hipótesis explícita](persist_es_hypothesis.json),
[ambigüedad](snippets.json) y [fallo de paráfrasis](json_paraphrase.json).

Reproducción:

```sh
.venv/bin/python scripts/evaluate_responsibility.py
.venv/bin/python -m pytest tests/test_responsibility.py tests/test_mcp_schema.py \
  tests/test_mcp_read.py tests/test_search_cli.py tests/test_doc_intent_integration.py \
  tests/ranker/test_fuzzy.py tests/test_justified_memory.py \
  tests/test_structural_memory_bridge.py tests/test_reasoning_memory.py -o addopts='' -q
```

El [evaluador](../../../scripts/evaluate_responsibility.py) conserva las preguntas
y los símbolos esperados antes de ejecutar. Volver a ejecutarlo actualiza los
resultados en este directorio con el índice vivo de ese momento.

## Próximas mejoras justificadas por los resultados

1. Recuperar docstrings completos por fragmentos y evaluar recuperación multilingüe
   con preguntas alejadas del vocabulario literal. Releer sólo los candidatos
   no descubre el método que quedó fuera del conjunto inicial.
2. Resolver destinos de llamadas para distinguir entrypoint, coordinador e
   implementación. El empate wrapper/función muestra una responsabilidad real
   compartida en distintos niveles, no necesariamente un fallo del ranking.
3. Añadir un razonador del grafo lingüístico con sus pruebas y cobertura explícita,
   para mejorar el tratamiento de negación, condiciones y sujeto implícito de
   los docstrings. Sus pruebas deberán seguir siendo condicionales a la fidelidad
   de la documentación al código.
4. Calibrar confianza con ejemplos etiquetados independientes: antes de llamar
   «80%» a un score, comprobar qué fracción de casos comparables realmente acierta.
