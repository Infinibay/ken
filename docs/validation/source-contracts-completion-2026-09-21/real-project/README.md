# Inspección de código real de Ken

Resultados CLI, sobre el checkout de trabajo y sin modificar los módulos
analizados. `impact` devuelve observaciones; hay límites explícitos de cobertura.

| Caso | Resultado |
| --- | --- |
| [query_view en checks](checks.json) | `integration.py::search` llama a `report.py::query_view`; se conservan candidatos de BODY desconocidos. |
| [Escritor de manifiestos, alcance de archivo](local.json) | `_atomic_write` recibe llamadas de `VectorStore._load_or_create` y la función global `compact`; la query de todos los usos llega a `max_rows`. |
| [Alcance src, recorrido original](broad-before.json) | Timeout de 30 segundos; el planner seleccionaba 264 de 268 archivos. |
| [Alcance src, direcciones separadas](broad-after.json) | La selección baja a 40 archivos, pero el worker aún agota 30 segundos. Estado `unknown`. |

```sh
ken tools related 'src/ken/checks/report.py::query_view' impact \
  --path src/ken/checks --depth 3
ken tools related 'src/ken/vectors.py::_atomic_write' impact \
  --path src/ken/vectors.py --depth 3
ken tools related 'src/ken/vectors.py::_atomic_write' impact \
  --path src --depth 3 --timeout-ms 30000
```

Los dos primeros casos se repitieron tras las correcciones finales de resolución
y nombres cualificados. La comparación de alcance amplio precede a esas dos
correcciones: mide el planner de imports, no una comparación emparejada de toda
la versión final. Cuando se mata el worker por tiempo no se conserva un snapshot
validado parcial; por eso `acquisition` queda `null` en esas salidas.

Se conservan fuentes e inventario mediante las pruebas automatizadas y los
recibos de los otros experimentos. Estas respuestas compactas documentan el
smoke test del checkout; no son snapshots autónomos reproducibles de todo Ken.
