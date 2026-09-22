Voy a contrastar la memoria señalada con el código actual de MCP y `ken tools`, sin modificar archivos ni memorias.
Registraría la nueva función con `@ken_tool` y la anotación `list[dict[str, Any]]`: ese decorador la expone en MCP y en el registro consumido por `ken tools`. **Hoy existe una regresión en el CLI; no hay paridad completa.**

La evidencia actual:

- En [server.py](/private/tmp/ken-coding-memory-4n2epo1i/mcp-stale-memory/src/ken/mcp/server.py:306), `_items_schema` ya produce `{"type":"object"}` para elementos `dict`; el parámetro queda como un array de objetos.
- En [cli.py](/private/tmp/ken-coding-memory-4n2epo1i/mcp-stale-memory/src/ken/cli.py:1757), `_tool_py_type("object")` devuelve `str`, aunque existe `_tool_json_object`. La memoria histórica está marcada como desactualizada precisamente por ese archivo.

Recomiendo conectar `"object"` con `_tool_json_object` en el conversor general. El CLI espera **un objeto JSON por argumento**, separado por espacios: posición obligatoria o `--flag` opcional; no un único JSON que contenga toda la lista.

La comprobación debe verificar el esquema y ejercitar `ken.cli.main`: ejecutar `test_cli_decodes_goal_and_premise_objects` y `test_cli_rejects_invalid_object_values`, además de comparar dos objetos enviados por MCP y CLI. Llamar sólo al wrapper MCP no detecta esta regresión.

No ejecuté esos tests porque crean archivos y bases de datos.