La protección consiste en **resolver la ruta y comprobar que el destino resultante pertenece a la raíz del proyecto**. No basta con que el texto de la ruta comience por el directorio del proyecto.

El recorrido de una petición `ken_read(path=..., include=["source"])` es:

1. El servidor fija `_PROJECT_ROOT` al arrancar: [server.py:91](src/ken/mcp/server.py#L91).
2. `ken_read` valida `path` antes de consultar el índice o leer contenido: [server.py:1000](src/ken/mcp/server.py#L1000).
3. `_project_relative_path` llama a `resolve_project_path` y convierte el resultado validado en una ruta relativa canónica para el índice: [server.py:325](src/ken/mcp/server.py#L325).
4. La comprobación efectiva está en [_paths.py:59](src/ken/_paths.py#L59): aplica `expanduser()`, resuelve raíz y destino con `resolve()`, y ejecuta `resolved.relative_to(root)`. Si el destino queda fuera, lanza `ValueError("path escapes project root: ...")`.
5. Solo después se llega a `file_snippets` y a la lectura mediante `read_text`: [server.py:1028](src/ken/mcp/server.py#L1028), [search.py:474](src/ken/search.py#L474), [search.py:789](src/ken/search.py#L789).

El tratamiento concreto es:

| Caso | Resultado |
|---|---|
| Ruta relativa | Se interpreta desde la raíz del proyecto, no desde el directorio actual. |
| Ruta absoluta interna | Se acepta. |
| Ruta absoluta externa | Se rechaza, incluso si pertenece a un directorio hermano cuyo nombre comparte el prefijo del proyecto. |
| Componentes `..` | Se normalizan; se rechazan cuando el destino final queda fuera. |
| Enlace simbólico interno | Se sigue y se utiliza la ruta canónica del destino. |
| Enlace simbólico hacia fuera | Se rechaza, también si falta el archivo final. |
| Destino inexistente | La inexistencia por sí sola no causa rechazo: `resolve()` se usa sin `strict=True`. La contención sigue comprobándose. |
| Enlace roto | Se acepta o rechaza según dónde quede su destino resuelto. |

Para un destino **interno inexistente**, hay dos resultados posteriores distintos:

- **Sin entrada en el índice:** `source` contiene `ok: false` y `error: "file not indexed"`: [search.py:421](src/ken/search.py#L421).
- **Con entrada residual en el índice:** la lectura captura `OSError` y devuelve un fragmento con `code: ""`: [search.py:789](src/ken/search.py#L789).

En ambos casos, el `ok` exterior de `ken_read` puede seguir siendo `true`; no agrega el estado de los resultados internos: [server.py:1011](src/ken/mcp/server.py#L1011).

La CLI comparte esta función y transforma la excepción de escape en un mensaje de error y código de salida **1**: [cli.py:1699](src/ken/cli.py#L1699). Existe además una prueba de ese comportamiento: [test_tools_cli.py:121](tests/test_tools_cli.py#L121).

Dejé una comprobación reproducible en [audit_paths.py](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-ko315rd1/audit_paths.py). Desde la raíz:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 audit_paths.py
```

**Resultado: 14 casos aprobados**, incluidos rutas relativas y absolutas, `..`, enlaces internos y externos, enlaces rotos y archivos inexistentes con y sin entrada en el índice. El script ejecuta las funciones reales extraídas del código mediante AST, con SQLite en memoria; no prueba el transporte MCP ni su registro. Todos los archivos temporales se crean dentro del repositorio y se eliminan. No pude ejecutar la suite de `pytest` porque no está instalado.

El límite de esta protección es que **la validación y la apertura son operaciones separadas**: `_read_line_range` no vuelve a comprobar la contención. Por tanto, este recorrido bloquea los escapes examinados, pero no garantiza protección frente a una sustitución concurrente de directorios por enlaces entre ambas operaciones.

No modifiqué código del producto ni hice commits; el único archivo añadido es la comprobación.