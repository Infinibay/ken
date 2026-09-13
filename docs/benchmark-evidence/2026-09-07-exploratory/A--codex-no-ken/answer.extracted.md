El recorrido de `ken_read` impide salir del proyecto **resolviendo primero la ruta y comprobando después su pertenencia a la raíz**. No comprueba que el archivo exista. La protección se aplica antes de consultar el índice o leer contenido.

1. **Entrada y raíz del proyecto.** La petición puede entrar por MCP como `ken_read(path=...)` o por `ken tools --path PROYECTO read RUTA`: ambos registran la misma función mediante [`ken_tool`](src/ken/mcp/server.py:192). MCP fija `_PROJECT_ROOT` al arrancar en [`run`](src/ken/mcp/server.py:91); la CLI lo hace en [`_tools_cli`](src/ken/cli.py:1695). La raíz se descubre buscando `.ken/meta.json` hacia arriba, con precedencia de `KEN_PROJECT_ROOT` ([`find_project_root`](src/ken/_paths.py:69)). El argumento que selecciona el proyecto y la ruta del archivo son parámetros distintos.

2. **Validación inmediata.** La primera instrucción de [`ken_read`](src/ken/mcp/server.py:1000) llama a `_project_relative_path(path)`. Este adaptador invoca `resolve_project_path` y convierte el resultado validado a una ruta relativa POSIX para el índice ([`server.py:325`](src/ken/mcp/server.py:325)).

3. **Comprobación efectiva.** En [`_paths.py:59`](src/ken/_paths.py:59), se expanden `~` y se resuelven tanto la raíz como el destino. La línea 63 ejecuta `resolved.relative_to(root)`: si no pertenece a la raíz, lanza `ValueError("path escapes project root: …")`. Es una comprobación por componentes, por lo que una carpeta hermana llamada `project-extra` no pasa como descendiente de `project`. La CLI captura la excepción, escribe el error en stderr y devuelve código 1 ([`cli.py:1701`](src/ken/cli.py:1701)).

El tratamiento concreto es:

| Caso | Resultado |
|---|---|
| Relativa `src/a.py` | Se interpreta desde la raíz del proyecto, no desde el directorio actual. |
| Absoluta interna | Se acepta y se transforma a relativa para consultar el índice. |
| `src/../src/a.py` | Se acepta: `..` se normaliza; no se prohíbe por su mera presencia. |
| `../outside/a.py` o absoluta externa | Se rechaza por quedar fuera tras resolverla. |
| Enlace simbólico interno | Se sigue y se usa la ruta canónica de su destino. |
| Enlace hacia fuera | Se rechaza, incluso si el archivo final no existe. |
| Enlace roto | Depende de dónde quede su destino resuelto: interno, aceptado; externo, rechazado. |
| Destino interno inexistente | Pasa la validación de pertenencia. |
| `.` | Pasa: este helper tampoco exige que el destino sea un archivo. |

**Los destinos inexistentes tienen dos tratamientos posteriores.** `resolve()` se invoca sin `strict=True`, por lo que admite componentes inexistentes. Si la ruta aceptada no está en el índice, `file_outline` y `file_snippets` devuelven `{"ok": false, "error": "file not indexed", ...}` ([`search.py:188`](src/ken/search.py:188), [`search.py:421`](src/ken/search.py:421)). `ken_read` conserva su `ok: true` exterior y coloca ese error dentro de `outline` o `source` ([`server.py:1011`](src/ken/mcp/server.py:1011)).

Si el archivo sigue indexado pero fue borrado, la lectura de fuente captura `OSError` y devuelve texto vacío; los snippets pueden contener `code: ""` ([`search.py:789`](src/ken/search.py:789), [`search.py:470`](src/ken/search.py:470)).

**Alcance de la garantía:** esta validación protege el recorrido público descrito. La función inferior `_normalize_index_path` no sustituye esa barrera: incluso ignora algunos errores de normalización ([`search.py:524`](src/ken/search.py:524)). Además, hay una separación temporal entre validar y abrir el archivo: `_read_line_range` usa después `read_text`, sin una apertura que asegure el confinamiento. Por inspección, cambiar un directorio por un enlace entre ambas operaciones podría eludir la comprobación; no he probado esa carrera.

Ejecuté **13 casos, todos satisfactorios**, directamente contra el helper real. Esta comprobación equivalente se reproduce desde la raíz del repositorio, usa solo la biblioteca estándar y elimina sus archivos temporales; el directorio “externo” simulado también queda dentro del repositorio:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from ken._paths import resolve_project_path

with TemporaryDirectory(dir=Path.cwd(), prefix=".path-check-") as tmp:
    base = Path(tmp)
    root = base / "project"
    (root / "src").mkdir(parents=True)
    (root / "src/a.py").write_text("x = 1\n")
    (base / "outside").mkdir()
    for name, target in [
        ("inside", "src"),
        ("escape", "../outside"),
        ("broken-in", "missing.py"),
        ("broken-out", "../absent.py"),
    ]:
        (root / name).symlink_to(target)

    cases = [
        ("src/a.py", "src/a.py"),
        (root / "src/a.py", "src/a.py"),
        ("src/../src/a.py", "src/a.py"),
        ("../outside/a.py", None),
        (base / "outside/a.py", None),
        (base / "project-extra/a.py", None),
        ("inside/a.py", "src/a.py"),
        ("escape/a.py", None),
        ("new/absent.py", "new/absent.py"),
        (root / "new/absent.py", "new/absent.py"),
        ("broken-in", "missing.py"),
        ("broken-out", None),
        (".", "."),
    ]
    for supplied, expected in cases:
        try:
            actual = resolve_project_path(root, supplied)
        except ValueError as exc:
            assert expected is None
            assert str(exc).startswith("path escapes project root: ")
        else:
            assert expected is not None
            assert actual == root / expected
    print(f"{len(cases)} casos OK")
PY
```

El repositorio ya incluye pruebas del helper en [`tests/test_paths.py:72`](tests/test_paths.py:72) y del rechazo desde la CLI en [`tests/test_tools_cli.py:121`](tests/test_tools_cli.py:121). No ejecuté pytest ni el transporte MCP porque este entorno carece de sus dependencias. No modifiqué código del producto, no dejé archivos nuevos y no hice commits.