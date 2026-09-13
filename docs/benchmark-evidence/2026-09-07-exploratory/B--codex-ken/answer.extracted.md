El descubrimiento habitual sube desde el subdirectorio hasta encontrar `.ken/meta.json`. **Hay una excepción: `ken rank` y `ken explain` no hacen esa búsqueda**, lo que puede provocar un intento de arranque en el subdirectorio equivocado.

1. **Cómo localiza el estado**

   [`find_project_root`, `_paths.py:69`](src/ken/_paths.py:69) aplica este orden:

   - Si `KEN_PROJECT_ROOT` tiene valor, expande `~`, resuelve la ruta y exige que allí exista `.ken/meta.json`. Si falta, devuelve `None`; no continúa buscando.
   - En otro caso, resuelve `start` o el directorio actual y examina esa ruta y sus padres. Devuelve el primer candidato con `.ken/meta.json`, o `None`.

   No busca `.git`, no lee el contenido del marcador y no exige una base de datos. Un `meta.json` vacío o inválido basta para descubrir la raíz, aunque falle después.

   Desde esa raíz compone `.ken/ken.db`, `daemon.port`, `daemon.pid` y `daemon.log` ([`_paths.py:18`](src/ken/_paths.py:18)). La preparación corresponde a `install`: crea o reutiliza los metadatos —identificador y token— y después inicializa SQLite ([`install.py:113`](src/ken/install.py:113)).

2. **Qué entradas usan esa raíz**

   Los hooks descubren desde el directorio actual **antes de leer el evento**; el `cwd` del payload no dirige la búsqueda ([`hook.py:33`](src/ken/hook.py:33)).

   `serve`, MCP y `tools` buscan desde la ruta recibida y, si el descubrimiento devuelve `None`, prueban esa misma ruta resuelta. MCP fija `_PROJECT_ROOT` una vez y arranca el transporte stdio ([`serve.py:13`](src/ken/serve.py:13), [`mcp/server.py:91`](src/ken/mcp/server.py:91), [`cli.py:1693`](src/ken/cli.py:1693)). Arrancar MCP no arranca inmediatamente el daemon: algunas herramientas acceden directamente a SQLite; ranking llama al cliente HTTP ([`mcp/server.py:319`](src/ken/mcp/server.py:319), [`mcp/server.py:838`](src/ken/mcp/server.py:838)).

   **La excepción comprobada:** `_rank_cli` y `_explain_cli` pasan `project_path.resolve()` directamente a `client.post` ([`cli.py:719`](src/ken/cli.py:719)). El cliente tampoco descubre la raíz. Desde `proyecto/a/b`, puede buscar `a/b/.ken/daemon.port` y crear allí el log de un intento de arranque. Además, fuerza `KEN_PROJECT_ROOT=a/b` al hijo, impidiendo que este encuentre el proyecto superior.

3. **Cómo reutiliza o arranca el servicio**

   [`client.py:83`](src/ken/daemon/client.py:83) implementa la decisión:

   | Situación | Acción |
   |---|---|
   | Puerto legible y POST exitoso | Devuelve la respuesta; no hace un `/health` previo. |
   | Archivo ausente, ilegible o no convertible a entero | Arranca un daemon. |
   | POST lanza `URLError`, `ConnectionRefusedError` u otro `OSError` | Borra el puerto, arranca y reintenta una vez. |
   | POST lanza específicamente `TimeoutError` | Registra una advertencia y devuelve `None`, conservando el puerto y sin arrancar otro proceso. |

   Los POST normales tienen 3 segundos de timeout; `/prompts`, `/rank` y `/explain`, 60 segundos. La clasificación es por excepción: un `HTTPError`, al ser un `URLError`, también entra en la rama de rearranque.

   Las solicitudes van a `http://127.0.0.1:<puerto>` con un Bearer token leído de `meta.json` ([`client.py:162`](src/ken/daemon/client.py:162)); el servidor comprueba ese token ([`server.py:391`](src/ken/daemon/server.py:391)).

   El arranque ejecuta el mismo intérprete con `-m ken serve <raíz> --background`, proceso separado, `cwd` y variable de entorno fijados a la raíz, y stdout/stderr enviados a `.ken/daemon.log`. Sondea cada 50 ms durante un presupuesto de 5 segundos y exige una respuesta verdadera de `/health` ([`client.py:109`](src/ken/daemon/client.py:109)).

   El servidor abre e inicializa SQLite, configura el modelo, escucha en un puerto libre de localhost y escribe puerto/PID. Empieza a atender HTTP antes del mantenimiento y la indexación inicial. Al cerrar limpia esos archivos ([`server.py:78`](src/ken/daemon/server.py:78), [`server.py:1054`](src/ken/daemon/server.py:1054)). En este recorrido no hay una comprobación del PID ni un bloqueo que garantice un único daemon; `serve` arranca directamente.

4. **Proyecto ausente, incompleto y comunicación de errores**

   | Caso | Dónde se comunica |
   |---|---|
   | Hook sin raíz | `stderr`: `ken: no .ken project at or above cwd, skipping hook`; salida **0** ([`hook.py:34`](src/ken/hook.py:34)). |
   | `serve` sin marcador | `stderr`, recomienda `ken install .`; salida **1** ([`serve.py:15`](src/ken/serve.py:15)). |
   | MCP sin marcador | `stderr`, visible en los logs del host MCP; salida **1** ([`mcp/server.py:95`](src/ken/mcp/server.py:95)). |
   | `tools` sin marcador | `stderr`: `error: no .ken project…`; salida **1** ([`cli.py:1695`](src/ken/cli.py:1695)). |
   | `status` sin raíz | Texto en `stderr`, o informe JSON en stdout con `--json`; salida **1** ([`status.py:33`](src/ken/status.py:33)). |
   | Metadatos presentes, DB ausente | `status` devuelve `ok: true`, `installed: false`; muestra que falta instalar la DB y termina con **0** ([`status.py:58`](src/ken/status.py:58)). |
   | Arranque o petición fallidos | `client.post` registra advertencia/excepción y devuelve `None` ([`client.py:53`](src/ken/daemon/client.py:53)). Los hooks conservan salida **0**; ranking CLI imprime `error: daemon unreachable` en `stderr` y sale **1**; ranking MCP devuelve `{ok: false, error: "daemon unreachable"}` ([`cli.py:750`](src/ken/cli.py:750), [`mcp/server.py:846`](src/ken/mcp/server.py:846)). |

   Hay otra defensa en `server.run`: si falta el marcador, imprime en **stdout** y devuelve **2** ([`server.py:1059`](src/ken/daemon/server.py:1059)). En el arranque automático, ese stdout queda en el log. Un JSON inválido o sin `auth_token` no recibe el diagnóstico «proyecto ausente»: falla al leer los metadatos; el proceso hijo deja el traceback en el log y el cliente acaba informando que no pudo alcanzarlo.

**Comprobación reproducible.** Ejecuté comprobaciones con los módulos reales y transporte/proceso simulados: pasaron el ascenso, el override inválido, la salida del hook, las cuatro ramas del cliente y la excepción de `rank`. No levanté servicios ni descargué dependencias; no había `pytest` disponible. Esta versión compacta reproduce las decisiones principales desde la raíz del repositorio:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 - <<'PY'
import os, tempfile
from pathlib import Path
from unittest.mock import patch
from ken import _paths
from ken.daemon import client
from ken.cli import _rank_cli

with tempfile.TemporaryDirectory(dir=".") as d:
    root = Path(d).resolve()
    sub = root / "a/b"
    sub.mkdir(parents=True)
    (root / ".ken").mkdir()
    (root / ".ken/meta.json").write_text("{}")
    with patch.dict(os.environ, {}, clear=True):
        assert _paths.find_project_root(sub) == root
        with patch.dict(os.environ, {"KEN_PROJECT_ROOT": str(sub)}):
            assert _paths.find_project_root(sub) is None

    cases = [
        ("existente", 12345, [{"ok": True}], False),
        ("ausente", None, [{"ok": True}], True),
        ("obsoleto", 12345, [ConnectionRefusedError(), {"ok": True}], True),
        ("timeout", 12345, [TimeoutError()], False),
    ]
    for name, port, replies, expected in cases:
        with (
            patch.object(client, "_read_port", return_value=port),
            patch.object(client, "_request", side_effect=replies),
            patch.object(client, "_spawn_and_wait", return_value=23456) as spawn,
            patch.object(client, "_clear_port_file") as clear,
        ):
            client._post_with_spawn(root, "/rank", {})
            assert spawn.called == expected
            assert clear.called == (name == "obsoleto")
            print(name, "OK")

    with patch.object(client, "post", return_value={"ok": True}) as post:
        _rank_cli(sub, "q", 1, max_chars=None, as_json=False, stats=False)
        assert post.call_args.args[0] == sub
    print("descubrimiento y excepción de rank: OK")
PY
```

No modifiqué código del producto, no dejé archivos de comprobación y no hice commits.