## Resumen

El estado es **local a cada proyecto, bajo `.ken/`**. La regla de descubrimiento no busca `.git`: busca un archivo **`.ken/meta.json`**, empezando en el directorio de ejecución y ascendiendo. Una vez conocida la raíz, el cliente intenta usar el puerto anunciado en `.ken/daemon.port`; si falta o la conexión falla, arranca un daemon.

Hay una excepción importante: **la CLI de `rank` y `explain` no hace ese recorrido ascendente**; pasa la ruta recibida directamente al cliente. Por tanto, no todas las entradas se comportan igual desde un subdirectorio.

## 1. Cómo encuentra el estado

`find_project_root(start=None)` sigue este orden ([src/ken/_paths.py:69-85](src/ken/_paths.py#L69)):

1. Si `KEN_PROJECT_ROOT` tiene un valor no vacío, expande `~`, resuelve la ruta y devuelve esa carpeta **solo si contiene `.ken/meta.json`**. Si no lo contiene, devuelve `None`: no intenta buscar en los ancestros.
2. Sin ese override, resuelve `start`, o el directorio actual si no se proporcionó.
3. Comprueba esa carpeta y después sus padres, devolviendo la primera que contenga el archivo marcador.
4. Si no encuentra ninguna, devuelve `None`.

Esto selecciona el proyecto preparado más cercano en proyectos anidados. El override prevalece incluso sobre un `start` explícito. **Encontrar el marcador no valida su JSON ni demuestra que exista una base de datos completa.**

Las rutas canónicas son `.ken/meta.json`, `.ken/ken.db`, `.ken/daemon.port`, `.ken/daemon.pid` y `.ken/daemon.log` ([src/ken/_paths.py:18-48](src/ken/_paths.py#L18)). La instalación prepara la ruta explícita, crea `.ken/`, genera identificador y token si no hay metadatos y crea/inicializa la base de datos; no descubre una instalación ancestral ([src/ken/install.py:113-143](src/ken/install.py#L113)).

### Qué entradas usan ese descubrimiento

| Entrada | Comportamiento |
|---|---|
| Hooks | Buscan desde el directorio actual, **antes de leer el evento**. El `cwd` del JSON no decide la raíz. Después envían el evento al cliente. [src/ken/hook.py:33-71](src/ken/hook.py#L33) |
| `serve` | Busca desde la ruta proporcionada; si no encuentra raíz, toma esa misma ruta y comprueba el marcador. [src/ken/serve.py:13-17](src/ken/serve.py#L13) |
| `status` | Busca ascendiendo y distingue «sin proyecto» de «metadatos pero sin DB». [src/ken/status.py:49-85](src/ken/status.py#L49) |
| MCP | Resuelve una raíz al inicio y la conserva para ese servidor de un solo proyecto. [src/ken/mcp/server.py:82-106](src/ken/mcp/server.py#L82) |
| Búsqueda CLI | Busca ascendiendo, pero exige que exista `ken.db`. [src/ken/cli.py:790-806](src/ken/cli.py#L790) |
| `rank` / `explain` CLI | **Solo hacen `project_path.resolve()`**, sin buscar ancestros. El cliente tampoco corrige esa raíz. [src/ken/cli.py:719-747](src/ken/cli.py#L719), [src/ken/daemon/client.py:83-102](src/ken/daemon/client.py#L83) |

Por ello, pasar un subdirectorio a `rank`/`explain` no equivale a pasar la raíz instalada: el cliente busca el puerto y los metadatos bajo ese subdirectorio. En cambio, las implementaciones MCP de esas operaciones utilizan la raíz fijada al inicio ([src/ken/mcp/server.py:840-868](src/ken/mcp/server.py#L840)).

## 2. Cómo decide reutilizar o arrancar el servicio

La decisión está en `_post_with_spawn` ([src/ken/daemon/client.py:83-106](src/ken/daemon/client.py#L83)):

- **Puerto legible:** intenta directamente el POST. No hace un `/health` previo ni decide a partir del PID.
- **POST satisfactorio:** devuelve la respuesta; reutiliza el servicio.
- **`TimeoutError` directo:** registra una advertencia y devuelve `None`, **sin borrar el puerto ni arrancar otro daemon**, porque la petición podría seguir ejecutándose.
- **`URLError`, `ConnectionRefusedError` u otro `OSError`:** considera el puerto obsoleto, elimina `daemon.port`, arranca un daemon y reintenta el POST una vez.
- **Archivo de puerto ausente, ilegible o no convertible a entero:** entra directamente en el arranque ([src/ken/daemon/client.py:145-159](src/ken/daemon/client.py#L145)).

La distinción del timeout depende de la excepción concreta: un error envuelto en `URLError` entra en la rama de recuperación, no en la de `TimeoutError` directo.

Las peticiones van a `http://127.0.0.1:<puerto>` y llevan `Authorization: Bearer <auth_token>`, leído de los metadatos de la raíz recibida. Los límites son 1 segundo para salud, 3 para POST ordinario y 60 para `/prompts`, `/rank` y `/explain` ([src/ken/daemon/client.py:33-44](src/ken/daemon/client.py#L33), [162-185](src/ken/daemon/client.py#L162)).

**Consultar salud no arranca nada:** `health()` solo lee el puerto e intenta un GET. `status` usa esa consulta ([src/ken/daemon/client.py:69-77](src/ken/daemon/client.py#L69), [src/ken/status.py:187-193](src/ken/status.py#L187)).

## 3. Recorrido del arranque

`_spawn_and_wait` ([src/ken/daemon/client.py:109-142](src/ken/daemon/client.py#L109)):

1. Crea el directorio del log y abre `.ken/daemon.log` en modo append.
2. Ejecuta el mismo intérprete Python con `-m ken serve <raíz> --background`.
3. Fija el directorio de trabajo y `KEN_PROJECT_ROOT` a esa raíz, desconecta stdin y redirige stdout/stderr al log. `start_new_session=True` permite que el daemon sobreviva al hook.
4. Sondea el puerto cada 50 ms, con presupuesto de 5 segundos. Solo declara éxito cuando obtiene una respuesta verdadera de `/health`.
5. Si no llega, lanza `DaemonUnreachable`.

`serve` valida los metadatos y configura el registro a archivo en background o a stderr en primer plano ([src/ken/serve.py:13-34](src/ken/serve.py#L13)). El servidor carga el token y prepara su estado; abre/inicializa la DB, por lo que no exige una DB preexistente ([src/ken/daemon/server.py:78-95](src/ken/daemon/server.py#L78)). Después:

- se enlaza a un puerto libre de `127.0.0.1`;
- publica puerto y PID;
- empieza a atender HTTP **antes** del mantenimiento en segundo plano, para que el trabajo inicial no impida responder a salud;
- al apagarse cierra recursos y elimina puerto/PID.

Referencias: [src/ken/daemon/server.py:1054-1110](src/ken/daemon/server.py#L1054), [1167-1177](src/ken/daemon/server.py#L1167).

La reutilización descrita pertenece al **cliente**: invocar `serve` directamente no pasa por esa decisión de reutilización; llama a `run_server(root)`.

## 4. Proyectos no preparados y comunicación de errores

| Caso | Comunicación y resultado |
|---|---|
| Hook sin raíz reconocida, incluido override inválido | stderr: `ken: no .ken project at or above cwd, skipping hook`; salida **0**, para no bloquear al agente. [hook.py:33-37](src/ken/hook.py#L33) |
| Hook sin `session_id` | stderr: `ken: hook payload missing session_id; skipping`; salida **0**. [hook.py:39-43](src/ken/hook.py#L39) |
| `serve` sin metadatos en la raíz resultante | stderr: `no ken project at … — run \`ken install .\` first`; salida **1**. En un arranque del cliente, ese stderr queda redirigido a `daemon.log`. [serve.py:13-17](src/ken/serve.py#L13), [client.py:118-127](src/ken/daemon/client.py#L118) |
| Entrada interna del servidor sin metadatos | stdout: `ken: no .ken/meta.json at …`; devuelve **2**. La entrada pública `serve` normalmente lo detecta antes. [server.py:1058-1062](src/ken/daemon/server.py#L1058) |
| MCP sin metadatos | stderr: `ken mcp: no .ken project at …`; salida **1**, antes del bucle stdio. [mcp/server.py:91-106](src/ken/mcp/server.py#L91) |
| `status` sin raíz | Error y sugerencia de instalación en stderr; con JSON, objeto de error en stdout. Salida **1**. [status.py:33-56](src/ken/status.py#L33) |
| Metadatos presentes, DB ausente | `status` devuelve `ok: true`, `installed: false`; en texto dice `(no DB yet — run \`ken install .\`)`. **No es un error de salida**. [status.py:58-94](src/ken/status.py#L58) |
| Búsqueda CLI sin DB | stderr: `error: no .ken project at …`; salida **1**. [cli.py:802-806](src/ken/cli.py#L802) |
| Daemon inalcanzable | El cliente registra warning y devuelve `None`; otros errores del POST se registran con excepción y también devuelven `None`. [client.py:53-66](src/ken/daemon/client.py#L53) |
| Ese `None` en `rank`/`explain` CLI | stderr: `error: daemon unreachable`; salida **1**, también con la opción JSON. [cli.py:750-765](src/ken/cli.py#L750) |
| Ese `None` en MCP rank/explain | Resultado estructurado `ok: false`, `error: "daemon unreachable"`. [mcp/server.py:840-868](src/ken/mcp/server.py#L840) |

Los hooks terminan con **0** aunque falle el envío; su protección adicional imprime `ken: hook error (…)` a stderr si escapa una excepción. Stdout queda reservado para el contexto que devuelve el daemon ([src/ken/hook.py:45-91](src/ken/hook.py#L45)).

Dos matices: una carpeta `.ken/` sin `meta.json` no identifica un proyecto; y un `meta.json` corrupto sí supera el descubrimiento, pero puede fallar después al leer JSON o claves. No hay una validación central que convierta todos esos fallos en el mismo mensaje amistoso. Además, aunque el descubridor no tiene fallback con un override inválido, `serve` y MCP hacen por su cuenta `find_project_root(...) or start.resolve()` y luego validan esa ruta.

## 5. Comprobación reproducible

Lucía ejecutó esta comprobación y revisé sus aserciones contra el código citado: **salida 0**, con los seis mensajes siguientes. Usa los módulos reales, archivos temporales dentro del repositorio y simulaciones de HTTP/arranque; no instala dependencias ni inicia servicios.

Desde la raíz del repositorio:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import os, sys, tempfile, types
from pathlib import Path
from unittest.mock import patch
repo = Path.cwd().resolve()
ken = types.ModuleType('ken')
ken.__path__ = [str(repo/'src/ken')]
sys.modules['ken'] = ken
from ken import _paths
from ken.daemon import client

with tempfile.TemporaryDirectory(dir=repo, prefix='.verify-') as d:
    root = Path(d)
    (root/'.ken').mkdir()
    (root/'.ken/meta.json').write_text('{}')
    nested = root/'a/b'
    nested.mkdir(parents=True)
    with patch.dict(os.environ, {}, clear=True):
        os.chdir(nested)
        try:
            assert _paths.find_project_root() == root
        finally:
            os.chdir(repo)
        with patch.dict(os.environ, KEN_PROJECT_ROOT=str(root)):
            assert _paths.find_project_root(nested) == root
        with patch.dict(os.environ, KEN_PROJECT_ROOT=str(nested)):
            assert _paths.find_project_root(nested) is None
        with patch.object(Path, 'is_file', return_value=False):
            assert _paths.find_project_root(nested) is None
    print('PASS raiz desde cwd, override valido/invalido y ausencia simulada')

    port = _paths.port_path(root)
    for scenario in ('existente', 'ausente', 'obsoleto', 'timeout'):
        port.write_text('12345')
        if scenario == 'ausente':
            port.unlink()
        effects = (
            [ConnectionRefusedError(), {'ok': True}] if scenario == 'obsoleto'
            else [TimeoutError()] if scenario == 'timeout'
            else [{'ok': True}]
        )
        with patch.object(client, '_request', side_effect=effects) as req, \
             patch.object(client, '_spawn_and_wait', return_value=23456) as spawn, \
             patch.object(client.logger, 'warning'):
            result = client._post_with_spawn(root, '/rank', {})
            assert result == (None if scenario == 'timeout' else {'ok': True})
            assert spawn.call_count == int(scenario in ('ausente', 'obsoleto'))
            assert req.call_count == (2 if scenario == 'obsoleto' else 1)
            assert port.exists() == (scenario in ('existente', 'timeout'))
        print('PASS puerto ' + scenario)
print('PASS limpieza automatica; HTTP y spawn simulados')
PY
```

Salida observada:

```text
PASS raiz desde cwd, override valido/invalido y ausencia simulada
PASS puerto existente
PASS puerto ausente
PASS puerto obsoleto
PASS puerto timeout
PASS limpieza automatica; HTTP y spawn simulados
```

**Límites:** esto comprueba las decisiones de control, no una conexión HTTP real, autenticación ni el arranque integrado. La ausencia global se simula para no inspeccionar ancestros externos al repositorio. No se ejecutó pytest. Una comprobación adicional de las funciones CLI confirmó que `rank`/`explain` pasan el subdirectorio absoluto sin llamar al descubridor.

No se modificó código del producto ni se hicieron commits; los temporales se eliminaron automáticamente. Había archivos staged y untracked previos, por lo que no presento el repositorio como «limpio».