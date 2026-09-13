# Preparación de comparación exploratoria — pendiente de revisión

No se ha lanzado una nueva campaña. Se conserva íntegro el piloto anterior y sus limitaciones. Solo se ejecutará un Codex O un Infinidev a la vez, incluidos preflights.

## Preflight MCP corregido

Evidencia: `2026-09-07-mcp-query-preflight/probe.{stdout,stderr,metadata.json}` (rutas relativas a este directorio). Codex `gpt-6-astra` por subscription, salida 0, 15.852 s. El permiso local `mcp_servers.ken.default_tools_approval_mode="approve"` restringido mediante `enabled_tools=["ken_find"]` permite invocar la herramienta en sandbox read-only. El intento anterior, conservado en `2026-09-07-mcp-approval-preflight/`, falló porque el cliente envió `task` y el schema instalado exige `query`.

En el intento corregido la llamada completó sin error de validación, **pero devolvió content=[]**. Esto verifica permiso y aceptación de argumentos, no recuperación útil, relevancia ni índice sano. No basta para declarar preparada la condición con Ken; hace falta diagnóstico offline del índice/copia y un resultado no vacío verificable antes de una campaña aprobada. No se ha ampliado permiso a otras herramientas ni probado nuevas variantes de modelo.

Ken servido corresponde al paquete instalado `ken-rank 0.14.0` de uv/site-packages, no al checkout evaluado. La diferencia entre instrucciones AGENTS (`task`) y schema (`query`) es un confusor comprobado; debe proporcionarse a ambos clientes con Ken el schema real, sin cambiar el producto. El catálogo final de herramientas y su versión deben congelarse y registrarse antes de comparar; el preflight solo habilitó ken_find y no valida el resto.

## Dos tareas propuestas (prompts visibles, sin pistas de ubicación)

### A. Seguridad de rutas

> Investiga cómo evita este proyecto que una petición que contiene una ruta acceda fuera del proyecto. Sigue el recorrido desde un punto de entrada hasta la comprobación efectiva. Explica el tratamiento de rutas relativas, absolutas y enlaces simbólicos, e identifica qué ocurre con destinos inexistentes. Aporta referencias de archivo y línea y una comprobación reproducible de los casos relevantes. No modifiques el código del producto.

### B. Arranque y descubrimiento

> Investiga cómo localiza este proyecto su estado de trabajo cuando se ejecuta desde un subdirectorio y cómo decide conectarse a un servicio existente o arrancarlo. Describe el recorrido completo que encuentres, los casos en que no hay un proyecto preparado y dónde se comunican esos errores. Aporta referencias de archivo y línea y una comprobación reproducible. No modifiques el código del producto.

Son propuestas, no tareas ya ejecutadas ni respuestas verificadas. Antes de aprobarlas debe prepararse una rúbrica privada a partir del snapshot: entradas reales, enlaces de llamadas, ramas de error y verificaciones offline. La rúbrica no se pasa a los agentes. Si algún supuesto del prompt no existe en el snapshot, se corrige el prompt antes de congelar las tres condiciones, no después de ver sus resultados.

Cada tarea se ejecutaría con el mismo prompt y snapshot en tres copias nuevas: Codex sin Ken, Codex con Ken funcional e Infinidev subscription. Deben registrarse diferencias de prompts internos y catálogo; Infinidev no aísla el efecto causal de Ken. Preparar entorno de checks idéntico, límite único suficiente, orden registrado y repeticiones acordadas antes de lanzar. Se proponen tareas de investigación porque obligan a descubrir ubicaciones; no se equipararán sus resultados con calidad de implementación.

## Captura de métricas propuesta

- Tiempo: reloj monotónico del proceso, inicio/fin, salida y timeout. Timeout es observación censurada, no duración de tarea terminada.
- Codex: conservar JSONL; extraer usage de turn.completed, input/output/cached sin doble suma; contar comandos y MCP por estado y nombre. Si no hay usage, null.
- Infinidev: stdout/stderr completos y snapshot de SQLite de la sesión nueva después de terminar. Revisar si esta ejecución escribe usage exacto por petición/actor; deduplicar solo con identificadores verificables y separar orquestador/trabajadores. En el piloto las bases tenían tres eventos iniciales y ningún usage, por lo que **la captura exacta todavía no está demostrada**. No basta con volver a consultar las mismas tablas ni sumar contadores ktk redondeados.
- Sin un registro exacto accesible mediante mecanismos existentes, tokens Infinidev se informarán como no disponibles; no se instrumentará el producto ni se tocarán credenciales/configuración global. Antes de la campaña se decidirá si se continúa con tiempo/calidad y esta limitación explícita.
- Herramientas: conservar invocaciones y resultado; reportar contadores nativos y taxonomía común solo donde los eventos permiten correspondencia. No equiparar líneas running a llamadas completadas.
- Calidad: rúbrica privada común, citas contrastadas con el snapshot, resultados reproducibles y errores/omisiones; separar finalización de precisión y de cantidad de herramientas. Archivos de evaluación fuera de las copias visibles al agente.

## Estado de autorización

Preparación entregada para revisión del orchestrator (hilo 60 / ticket t_f44da8f7beb6). No hay nuevas mediciones comparativas ni ganador. Pendientes: revisar prompts/rúbrica, resolver búsqueda vacía y catálogo MCP, aceptar explícitamente el límite de tokens Infinidev o demostrar fuente exacta existente, y autorizar campaña secuencial.
