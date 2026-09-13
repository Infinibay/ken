El estado se localiza mediante **`.ken/meta.json` en el directorio actual o en un antecesor**. Sin embargo, hay una inconsistencia: **`rank` y `explain` no hacen esa búsqueda**, por lo que pueden fallar desde un subdirectorio aunque el proyecto padre esté preparado.

1. **Localización del estado**

   `find_project_root()` resuelve la ruta inicial —por defecto, el `cwd` real del proceso— y recorre primero ese directorio y después sus padres. Devuelve el primer directorio con `.ken/meta.json`; no necesita `.git`, no valida el contenido del JSON y no comprueba que exista la base de datos. En proyectos anidados gana el marcador más cercano. Véase [_paths.py:69](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/_paths.py:69).

   `KEN_PROJECT_ROOT`, si tiene un valor no vacío, prevalece incluso sobre `start`. Si apunta a un lugar sin el marcador, devuelve `None` **sin intentar el ascenso**. Algunos llamadores usan después `find_project_root(...) or start.resolve()`, de modo que pueden aceptar el directorio inicial si este contiene su propio marcador.

   Las rutas del estado se construyen bajo esa raíz: `.ken/ken.db`, `daemon.port`, `daemon.pid` y `daemon.log`. La preparación mediante `install` crea los metadatos —incluido `auth_token`— y el esquema SQLite. Véanse [_paths.py:18](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/_paths.py:18) e [install.py:113](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/install.py:113).

2. **Del comando al cliente**

   Los hooks buscan la raíz **antes de leer el evento**: el campo `cwd` del JSON no determina dónde encuentran el proyecto. Después envían el evento mediante `client.post()`. Véase [hook.py:33](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/hook.py:33).

   MCP resuelve y guarda `_PROJECT_ROOT` al iniciar; sus herramientas de ranking usan posteriormente esa raíz. Iniciar MCP abre el transporte `stdio`; el arranque del daemon se solicita al ejecutar una herramienta que use `post()`. Véanse [mcp/server.py:91](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/mcp/server.py:91) y [mcp/server.py:838](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/mcp/server.py:838).

   **La excepción es la CLI `rank`/`explain`:** pasa `project_path.resolve()` directamente al cliente. Desde `raíz/a/b`, busca el puerto en `raíz/a/b/.ken`, no en `raíz/.ken`. Si intenta arrancar, también fija `KEN_PROJECT_ROOT=raíz/a/b`, impidiendo que el hijo encuentre el proyecto padre. Véase [cli.py:719](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/cli.py:719).

3. **Conectar o arrancar**

   El comportamiento efectivo de [_post_with_spawn(), client.py:83](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/daemon/client.py:83) es:

   | Situación | Decisión |
   |---|---|
   | Puerto legible y entero | Intenta directamente el POST; no hace un `/health` previo. |
   | POST satisfactorio | Reutiliza ese servicio. |
   | `TimeoutError` | Registra advertencia y devuelve `None`; conserva el puerto y no relanza. |
   | `URLError` u otro `OSError` capturado | Borra el puerto y arranca otro daemon; reintenta el POST una vez. |
   | Puerto ausente, ilegible o no entero | Arranca el daemon. |

   La decisión no consulta `daemon.pid`. Además, `HTTPError` deriva de `URLError`: esa rama puede relanzar ante un error HTTP, no solamente ante una conexión rechazada.

   El arranque ejecuta `[sys.executable, "-m", "ken", "serve", raíz, "--background"]`, separado mediante `start_new_session=True`, con `cwd` y `KEN_PROJECT_ROOT` fijados a la raíz. Redirige stdout y stderr a `.ken/daemon.log`. Sondea el puerto cada 0,05 segundos, durante un plazo nominal de 5 segundos, y exige una respuesta verdadera de `/health` antes de reintentar el POST. Las peticiones van a `127.0.0.1` con el token Bearer leído de los metadatos. Véase [client.py:109](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/daemon/client.py:109).

   `serve` resuelve y valida la raíz y llama al servidor. Este abre/inicializa SQLite, escucha en un puerto local libre y publica puerto y PID. Empieza a atender HTTP antes del mantenimiento del índice; al apagarse limpia ambos archivos. **Ejecutar `serve` directamente no comprueba si ya hay otro daemon**. Véanse [serve.py:13](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/serve.py:13), [daemon/server.py:78](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/daemon/server.py:78) y [daemon/server.py:1054](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/daemon/server.py:1054).

Los errores se comunican de manera distinta según la entrada:

| Caso | Resultado y canal |
|---|---|
| Hook sin proyecto | `ken: no .ken project at or above cwd, skipping hook`, por **stderr**, salida **0**. |
| `serve` sin marcador | Recomienda `ken install .`, por **stderr**, salida **1**. Si fue lanzado por el cliente, queda en `daemon.log`. |
| Entrada interna del servidor sin marcador | `ken: no .ken/meta.json at …`, por **stdout**, retorno **2**. |
| MCP sin proyecto | `ken mcp: no .ken project at …`, por **stderr**, retorno **1**. |
| Cliente sin poder arrancar/conectar | Registra advertencia o excepción en el logger `ken.client` y devuelve `None`; el hook termina con **0**. |
| CLI `rank`/`explain` recibe `None` | `error: daemon unreachable`, por **stderr**, salida **1**, incluso con `--json`. |
| Herramientas MCP de ranking reciben `None` | Devuelven `{"ok": false, "error": "daemon unreachable"}` como resultado de la herramienta. |

Las conversiones de fallos del cliente están en [client.py:53](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/daemon/client.py:53); las de la CLI, en [cli.py:750](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/cli.py:750).

Hay dos matices de “proyecto preparado”:

- **Sin base de datos:** el marcador basta para descubrir el proyecto. `status` devuelve `ok: true, installed: false` y termina con 0; otros comandos que necesitan la base muestran `error: no .ken project at …` y terminan con 1. Véanse [status.py:33](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/status.py:33), [cli.py:1810](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/cli.py:1810) y [cli.py:832](/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-explore-8posxwwb/src/ken/cli.py:832). `status` solo consulta salud: no arranca el servicio.
- **Metadatos corruptos o incompletos:** superan el descubrimiento, pero pueden fallar al leer JSON o `auth_token`. No hay una validación uniforme: `post()` captura esos fallos; el arranque del servidor puede propagarlos como excepción.

**Comprobación reproducible.** Ejecuté comprobaciones con directorios temporales dentro del repositorio y dobles de HTTP/proceso: pasaron el ascenso, el override inválido, las cinco decisiones de la tabla, los parámetros de arranque y los canales de error. No arranqué un daemon real. Este extracto reproduce los hallazgos principales desde la raíz, usando solo Python:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
import contextlib, io, os, tempfile
from pathlib import Path
from unittest.mock import patch
from ken import _paths, cli
from ken.daemon import client

with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
    root = Path(tmp).resolve()
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / ".ken").mkdir()
    (root / ".ken/meta.json").write_text("{}")

    with patch.dict(os.environ):
        os.environ.pop("KEN_PROJECT_ROOT", None)
        with contextlib.chdir(sub):
            assert _paths.find_project_root() == root
        os.environ["KEN_PROJECT_ROOT"] = str(sub)
        assert _paths.find_project_root(root) is None
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.main(["hook", "session-start"]) == 0
        assert "skipping hook" in err.getvalue()

    for port, replies, launches in [
        (12345, [{"ok": True}], 0),
        (None, [{"ok": True}], 1),
        (12345, [ConnectionRefusedError(), {"ok": True}], 1),
        (12345, [TimeoutError()], 0),
    ]:
        with patch.object(client, "_read_port", return_value=port), \
             patch.object(client, "_request", side_effect=replies), \
             patch.object(client, "_spawn_and_wait", return_value=23456) as spawn:
            client.post(root, "/rank", {})
            assert spawn.call_count == launches

    with contextlib.chdir(sub), \
         patch.object(client, "post", return_value={"ok": True}) as post, \
         contextlib.redirect_stdout(io.StringIO()):
        for command in ("rank", "explain"):
            assert cli.main([command, "consulta"]) == 0
            assert post.call_args.args[0] == sub
    print("OK: descubrimiento, errores, conexión y excepción rank/explain")
PY
```

No modifiqué código del producto ni hice commits. Los temporales se eliminaron; la comprobación final no mostró cambios respecto al índice ni archivos nuevos sin seguimiento.