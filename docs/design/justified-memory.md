# Memoria de programación con justificaciones y vigencia

Primera integración, 2026-09-21. Extiende las herramientas existentes y los hooks
de Ken. La unidad reutilizable es una conclusión con explicación breve, evidencia
y dependencias declaradas. El agente escribe el aprendizaje; el hook lo recupera.
No se extrae automáticamente un razonamiento completo de la conversación.

## Uso desde una tarea de programación

Después de investigar un bug o comparar una alternativa, el agente puede guardar:

```python
ken_remember(
    topic="Parámetros JSON entre MCP y CLI",
    content="Las listas de objetos requieren esquema de items y conversión JSON en argparse. Probar ambos caminos.",
    anchor_file="src/ken/cli.py",
    justification={
        "kind": "observation",
        "rationale": "Probar sólo el wrapper MCP no ejercita cómo ken tools convierte sus argumentos.",
        "evidence": [{"path": "reports/cli-regression.txt", "note": "Resultado de la prueba focal."}],
        "dependencies": [
            {"path": "src/ken/cli.py"},
            {"path": "src/ken/mcp/server.py"},
            {"path": "tests/test_reasoning_memory.py"},
        ],
        "assumptions": ["Mismo contrato y entorno que la prueba registrada."],
        "recheck": "Ejecutar test_cli_decodes_goal_and_premise_objects tras cambiar la conversión.",
    },
)
```

El archivo de evidencia debe existir. Cada evidencia se incorpora automáticamente
como dependencia. Ken captura SHA-256 al registrar. Para ligar la observación al
contenido leído previamente, se puede incluir `sha256` en evidencia/dependencia;
si cambió entre la observación y el registro, la escritura se rechaza completa.

```python
ken_recall(topic="Parámetros JSON entre MCP y CLI", detail="answer", max_chars=1800)
ken_recall(topic="Parámetros JSON entre MCP y CLI", detail="summary", max_chars=1800)
ken_recall(topic="Parámetros JSON entre MCP y CLI", detail="full")
```

`answer` empieza por la conclusión completa, su tipo, fuentes, supuestos y estado
de vigencia. Con tópico exacto lee únicamente esa memoria y comprueba sus entradas,
sin recorrer sus vecinos ni ejecutar KQL. Indica si se puede considerar su
reutilización o si hay que revisar las entradas. El agente todavía debe comprobar
que pregunta, alcance y supuestos coincidan. Una hipótesis conserva ese carácter.
Si falta evidencia, se amplía sólo esa memoria con `full` o se lee el símbolo
necesario. No se exige repetir `impact` después de cada recuperación.

`summary` añade explicación breve y más detalle de vigencia. Ambos devuelven
`memories`, `omitted` y `detail`, con presupuesto sobre el JSON
serializado sin indentación. `full` conserva las formas anteriores; una consulta
por tópico incluye ahora `finding`, además de sus vecinos. La evidencia pesada
permanece en archivos. El CLI compartido acepta el mismo objeto mediante
`ken tools remember ... --justification '{...}'`.

Una conclusión o sus supuestos nunca se cortan silenciosamente para caber:
se entrega el registro completo o una referencia `expand` con
`conclusion_omitted`. `full` sigue siendo el default por compatibilidad.

## Qué es automático

- `SessionStart`: las memorias recientes incluyen un estado de dependencias.
- `UserPromptSubmit`: las memorias justificadas seleccionadas por el ranking
  aportan un bloque breve adicional, dentro del presupuesto total de 3500
  caracteres. Se omite su repetición en la misma sesión si su contenido y estado
  no cambiaron. La deduplicación vuelve a empezar al reiniciar el daemon/sesión.
  El bloque sugiere recuperar la conclusión con `detail="answer"` antes de ampliar
  la evidencia.
- `ken_recall` y el ranking ampliado: comprueban dependencias del worktree actual.

Se reutilizan los hooks existentes; no hace falta una tool nueva ni otro watcher.
Las comprobaciones suceden al recuperar. La captura de conclusiones sigue siendo
explícita, porque leer un archivo o ver pasar un test no acredita por sí mismo
una conclusión general. No hay ejecución automática de comandos ni llamadas LLM.

Un servidor MCP o daemon ya iniciado conserva el código anterior en memoria:
reiniciarlo para que cargue esta versión. Instalar desde el checkout si el binario
activo apunta a una instalación antigua. En hosts sin hooks, usar `ken_recall`.

## Significado de la vigencia

| Estado | Significado |
|---|---|
| `unchanged` | Coinciden las dependencias declaradas que pudieron comprobarse. |
| `stale` | Cambió al menos una dependencia. Revisar antes de reutilizar. |
| `unknown` | Falta una dependencia, no se puede leer o se agotó el presupuesto. |
| `untracked` | No se declararon dependencias comprobables. |

Ninguno acredita verdad, completitud de las dependencias ni validez de supuestos.
`hypothesis` sigue siendo hipótesis; una observación o decisión no se convierte
en teorema. Reescribir una nota sin justificación retira su justificación anterior
en la misma transacción. El esquema nuevo es aditivo y usa la misma `ken.db`.

Para búsquedas de ausencia o inventarios, declarar el alcance, por ejemplo:

```json
{"kind": "tree", "path": "src/ken/knowledge", "pattern": "*.py"}
```

La huella incluye rutas y contenido de los archivos coincidentes, recursivamente.
Detecta adiciones y eliminaciones. `pattern` usa la semántica de
`PurePosixPath.match`; `*.py` coincide con archivos Python a cualquier profundidad.
No se omiten silenciosamente directorios de la búsqueda; se rechazan enlaces
simbólicos internos que impidan acreditar su alcance. El root del proyecto puede
ser un alias del sistema, por ejemplo `/var` en macOS.

La comprobación tiene límites compartidos por lote: 256 archivos, 16 MiB,
10.000 entradas y 200 ms. Registrar dispone de dos segundos. Agotar un límite
produce `unknown`, nunca `unchanged`. Los hashes son conservadores: cambiar un
comentario también pide revisión. Entorno, paquetes externos, configuración no
declarada y dependencias transitivas no se descubren automáticamente.

## Responsabilidades

- `memory.py`: guarda la nota y su justificación atómicamente.
- `knowledge/records.py`: valida el contrato y une notas con justificaciones.
- `knowledge/dependencies.py`: captura y compara las entradas declaradas.
- `knowledge/context.py`: produce resúmenes, límites y deduplicación de entrega.
- MCP, ranker y hooks: seleccionan y entregan esos resultados.

El motor estructural experimental puede aportar evidencia mediante
`textgraph.ken_memory.export_finding(engine, graph_path, result, project_root=..., topic=...)`.
Devuelve argumentos de `ken_remember` y conserva respuesta, consulta y pruebas
en un recibo de archivo. Verifica la respuesta antes de exportar; la memoria
posterior comprueba hashes. El grafo lingüístico original permanece intacto.
Este primer adaptador acepta un `Graph`; no importa el engine en el runtime de
Ken, no usa el almacén anterior de ternas y no ejecuta NLP en los hooks.

Si el engine está dentro del proyecto, su código Python es una dependencia de
árbol. Fuera del proyecto se declara la versión externa como supuesto pendiente.
Los operadores personalizados y configuración adicional deben declararse como
dependencias. La verificación formal no corrige una interpretación lingüística
incorrecta ni garantiza cobertura; las pruebas de integración conservan ese límite.

## Evaluación

`tests/test_justified_memory.py` cubre sesiones, cambios relevantes/irrelevantes,
alta de archivos, presupuesto, supuestos, rollback, compatibilidad, CLI y hooks.
`tests/test_structural_memory_bridge.py` verifica la entrega del motor y la
reutilización sin parsear ni inferir otra vez.

`scripts/evaluate_coding_memory.py` prepara copias del propio Ken y su base real
para comparar Codex CLI con memoria clásica y enriquecida. Ejecuta comprobaciones
focales y reproduce una regresión real de conversión de JSON sólo en la copia.
`--collect` obtiene uso de tokens y llamadas del JSONL del CLI. El experimento
fija la selección inicial de notas: evalúa su uso por el agente, no la precisión
del recuperador. Es una muestra pequeña, sin estimación estadística de ahorro.

Resultados, respuestas y trazas de ocho sesiones reales de Codex CLI:
[evaluación de memoria para programación](../validation/coding-memory-2026-09-21/README.md).
