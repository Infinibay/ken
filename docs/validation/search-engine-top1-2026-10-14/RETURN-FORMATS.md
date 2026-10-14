# Formatos de respuesta

Implementado en el checkout experimental; el perfil predeterminado de búsqueda
no se promueve mientras no supere la aceptación aprobada.

Para ubicaciones y código verificado en texto plano:

```sh
ken search-symbols 'Where is `redirect` defined?' --path PROJECT --response-format compact
ken search-files 'remove credentials' --path PROJECT --response-format compact -n 3
ken tools --path PROJECT find 'remove credentials' --scope symbols --response-format compact
```

En MCP:

```python
ken_find(query='remove credentials', scope='symbols', response_format='compact')
```

Ejemplo de salida, con dos fragmentos separados:

```text
src/client.py:12-13 :: Client.redirect [partial]
    prepare()
    send()
@42-42
    return response

2 more results omitted.
```

Cada encabezado identifica archivo, rango inclusivo y función cuando existe.
`@42-42` inicia otro fragmento del mismo resultado: no implica continuidad con
el anterior. `[partial]` indica que no se mostró toda la entidad; `[stale]` y
las advertencias conservan el aviso de fuente desactualizada. No se muestran
scores, hashes ni versiones. Una búsqueda vacía dice `No matches.`; los errores
conservan la acción de recuperación.

El orden, la fuente verificada y el presupuesto de evidencia son los mismos que
en `response_format='evidence'`. La representación compacta no puede recuperar
anclas adicionales para facilitar la aceptación. `max_chars` limita la respuesta
estructurada subyacente; cambiar de formato no aumenta ese presupuesto.

La respuesta estructurada sigue disponible en MCP con
`response_format='evidence'`, y en CLI con `--response-format evidence --json`.
Combinar `compact` y `--json` devuelve un error con el comando correcto.
El modo `legacy` sigue siendo el predeterminado y conserva sus contratos.
No se agregó una dependencia de YAML ni un modelo para formatear resultados.

Validación: pruebas públicas CLI/MCP, dos consultas reales por stdio persistente,
fragmentos discontinuos, errores y passthrough `ken tools`. Al renderizar las
mismas 400 respuestas guardadas, los caracteres totales bajan de 3,472,418 en JSON
canónico a 2,040,715 en texto compacto: 41.23% menos. Medianas: 9210.5 y 5248.5.
Son caracteres, no una medición de tokens o precisión. Recibo:
`output/development/compact-render-comparison.json`.
