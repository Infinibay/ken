# Escaneo de Requests con Ken

Se descargó [Requests](https://github.com/psf/requests), commit `dae7ef63b4df6eded86637f251fc4e3a06c3b479`,
en `/tmp/ken-real-repos/requests` y se analizaron **19 archivos Python de `src/`**.
No se instaló ni ejecutó código de Requests. Se utilizó el motor existente sin
modificar consultas para ajustarlas al repositorio.

## Resultado

Las 23 consultas GoF completaron con los presupuestos registrados en el JSON.
No hubo diagnósticos de parsing. El IR contiene 4,301 entidades y
80,857 hechos. Su construcción tardó aproximadamente 0.56 s;
las 23 evaluaciones sumaron unos 19 ms, sin incluir normalización del grafo de consulta
ni carga del catálogo. Son tiempos de una ejecución, no un benchmark controlado.

| Consulta | Candidatos | Revisión manual |
|---|---:|---|
| Iterator | 8 | Recorrido o producción incremental de elementos en los ocho casos. |
| Template Method | 1 | Colaboración base/subclase confirmada en `SessionRedirectMixin`. |
| Command | 1 | Falso positivo: identifica `PreparedRequest.copy` como ejecución. |
| Las otras 20 | 0 | Sin coincidencias de las variantes disponibles; no demuestra ausencia. |

## Evidencia revisada

Los ocho generadores son `iterkeys`, `itervalues`, `iteritems`, `generate` (anidado en
`iter_content`), `iter_lines`, `resolve_redirects`, `iter_slices` y
`stream_decode_response_unicode`. Producen cookies, pares, chunks, líneas,
respuestas/redirecciones, slices o texto decodificado. El generador anidado se cuenta
como callable propio, no como otro resultado para su función externa.
Véanse [cookies.py](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/cookies.py#L250),
[models.py](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/models.py#L935),
[sessions.py](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/sessions.py#L186) y
[utils.py](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/utils.py#L594).

El oráculo independiente de `ast` encuentra 10 generadores; los 10 están en el IR,
sin omisiones ni coincidencias inesperadas. El catálogo excluye correctamente
`atomic_open` y `set_environ`: usan `contextlib.contextmanager` para manejar recursos,
no para ofrecer iteración. [Decoradores y scopes](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/utils.py#L328).

En Template Method, `SessionRedirectMixin.resolve_redirects` llama al slot `send`
de la clase base; `Session.send` lo implementa en la subclase. La evidencia enlaza
el método plantilla, el slot y su override, no sólo sus nombres.
[Template](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/sessions.py#L292) ·
[Override](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/sessions.py#L752).

El candidato Command es un falso positivo revisado: `PreparedRequest.copy()` llama
`headers.copy()` y `resolve_redirects(req: PreparedRequest)` llama `req.copy()`.
Eso satisface receptor + operación sin argumentos + invocador, pero la operación
es una copia, no la ejecución de una acción encapsulada.
[Copia](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/models.py#L456) ·
[Invocación](https://github.com/psf/requests/blob/dae7ef63b4df6eded86637f251fc4e3a06c3b479/src/requests/sessions.py#L205).

Además hay una **omisión de Prototype**: `PreparedRequest.copy()` construye un objeto
vacío, copia sus campos y lo retorna. La variante actual exige pasar estado al
constructor del objeto retornado y no cubre esta secuencia de asignaciones. No se
modificó el motor en esta tarea para ocultar la omisión o el falso positivo.

Estas observaciones no estiman precisión/recall global de GoF: no se etiquetaron
todos los patrones posibles del repositorio. Los ocho Iterator y el Template Method
se validaron como formas de colaboración; no se certifica su corrección en ejecución.

## Reproducción y artefactos

```sh
git clone --depth 1 https://github.com/psf/requests.git /tmp/ken-real-repos/requests
# Para repetir exactamente el corpus, obtener y usar el commit registrado arriba.
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/requests --prefix src/ --output /tmp/requests.json
```

[Resultados completos](requests-canonical.json): manifest de archivos y SHA-256,
commit, hashes del motor y catálogo, estadísticas por consulta, roles localizados,
resultados del oráculo y presupuestos. La descarga está fuera del repositorio Ken;
no se incorporó código de Requests al proyecto.
