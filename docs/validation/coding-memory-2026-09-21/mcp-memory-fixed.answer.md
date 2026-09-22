Consultaré la nota indicada y los puntos de esquema y conversión CLI para confirmar el contrato actual, sin modificar archivos ni memorias.
El soporte ya existe. Integraría la nueva función con `@ken_tool` y su parámetro anotado `list[dict[str, Any]]`: el decorador registra MCP y CLI. Mantendría la lógica de dominio en la función, sin conversiones JSON específicas de la tool.

La evidencia confirma dos responsabilidades independientes:

- [server.py](/private/tmp/ken-coding-memory-4n2epo1i/mcp-memory-fixed/src/ken/mcp/server.py:306): `_annotation_to_schema` y `_items_schema` generan `{"type":"array","items":{"type":"object"}}` para el registro.
- [cli.py](/private/tmp/ken-coding-memory-4n2epo1i/mcp-memory-fixed/src/ken/cli.py:1757): `_build_tool_parser` usa `_tool_py_type` → `_tool_json_object`, que decodifica cada argumento y exige un diccionario. El CLI recibe objetos separados: `--items '{"a":1}' '{"b":2}'`, no un único array JSON. Los parámetros requeridos son posicionales y exigen al menos un elemento.

Recomiendo comprobar el esquema publicado por MCP y el registro, e invocar también `ken.cli.main` con dos objetos, verificando tipos y resultados equivalentes. Añadiría rechazo de JSON inválido y valores no objeto. [Las regresiones existentes](/private/tmp/ken-coding-memory-4n2epo1i/mcp-memory-fixed/tests/test_reasoning_memory.py:197) cubren `--goal`, `--facts` y `--assumptions`: llamar solamente al wrapper MCP omitía los fallos anteriores.

Confirmación por lectura; no ejecuté pruebas ni modifiqué archivos o memorias.