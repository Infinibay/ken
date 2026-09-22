# Contratos de código con KQL 2

Implementación en `src/ken/checks/`, publicada por el MCP existente y por
`ken tools`. Las consultas describen propiedades del código capturado; no
ejecutan ese código ni llaman a un modelo. El agente interpreta la pregunta
humana y entrega una consulta KQL 2 explícita.

## Interfaz

| Tool | Uso |
| --- | --- |
| `ken_rule` | Crear, inspeccionar, actualizar, validar, habilitar o deshabilitar contratos. |
| `ken_check` | Comprobar contratos, conservar recibos y comparar resultados. |
| `ken_find` | Ejecutar consultas KQL 2 o buscar con las reglas registradas. |
| `ken_who` | Documentación, llamadas, retornos y un mapa de roles hipotéticos entre archivos. |
| `ken_related` | `impact` sigue consumidores; `roles` explica cadenas; `available` ofrece accesos Python; `checks` muestra contratos y recibos. |
| `ken_remember` / `ken_recall` | Vincular una conclusión a un recibo y revisar sus dependencias sin repetir consultas. |

Compacto por defecto; `full=True` / `--full` conserva el detalle. La excepción
histórica es `ken_recall`, que mantiene `detail="full"` por defecto y ofrece
`summary` y `answer`. Comenzar con `answer` permite reutilizar una conclusión
con sus fuentes, supuestos y vigencia; `full` amplía la evidencia cuando hace falta.

## Ejemplo: el wrapper debe devolver el identificador

Código correcto:

```python
def save():
    return 42

def save_user():
    return save()
```

Regresión:

```python
def save_user():
    save()
    return 0
```

El agente escribe una consulta que captura el resultado de esa llamada y su
retorno. No se deduce el significado de `save` únicamente por su nombre; el
contrato declara qué forma concreta del wrapper estamos comprobando.

```python
definition = {
    "id": "storage.return-id",
    "description": "save_user devuelve el valor de la llamada save",
    "path": "src",
    "expectation": "some_match",
    "query": '''language "kql/2"; module project.storage;
query returned_identifier {
  callable $owner { name: "save_user"; body {
    let $value = call $save { name: "save"; };
    return $value;
  } }
  select $owner;
}''',
    "examples": [
        {
            "name": "conserva resultado",
            "files": {"src/store.py": "def save():\n return 42\ndef save_user():\n return save()\n"},
            "expect": "pass",
        },
        {
            "name": "descarta resultado",
            "files": {"src/store.py": "def save():\n return 42\ndef save_user():\n save()\n return 0\n"},
            "expect": "fail",
        },
    ],
}

ken_rule(action="create", definition=definition)
ken_rule(action="validate", rule_id="storage.return-id")
ken_rule(action="enable", rule_id="storage.return-id")

before = ken_check(rules=["storage.return-id"])
# Después de editar:
after = ken_check(rules=["storage.return-id"], compare=before["run_id"])
```

Si el primer caso pasa y el segundo falla, la comparación informa `regression`.
Al restaurar la propiedad informa `resolved`. Una ejecución desconocida no se
presenta como una corrección.

`some_match` exige **al menos un testigo** en el alcance declarado. No significa
que todos los adaptadores, llamadas o caminos satisfagan una propiedad. Para
comprobar ausencia de violaciones se usa `expectation="no_matches"` y una consulta
que encuentre violaciones. Cuando KQL no admite la construcción necesaria, el
compilador la rechaza: no se sustituye por una propiedad más débil.

Por ejemplo, esta consulta reutiliza la detección existente de argumentos
mutables Python:

```kql
language "kql/2";
module project.bugs;
query mutable_defaults {
  edge HAS_HAZARD($site, "mutable-default-argument");
  select $site;
}
```

Una regla `no_matches` sobre esa consulta pasa sin coincidencias y falla al
encontrarlas, siempre que la ejecución sea completa y la cobertura suficiente.
Los testigos del perfil de grafo pueden ser IDs; seleccionar entidades fuente
permite devolver ubicaciones más detalladas.

## Reglas y validación

Una definición contiene `id`, `query`, `description`, `path`, `expectation`,
`examples` y, opcionalmente, `libraries` (mapa módulo → fuente KQL).

- `create` crea un borrador; no sobrescribe otra regla.
- `update` requiere la definición completa y elimina su habilitación/validación.
- `validate` analiza ejemplos aislados, incluyendo al menos un `pass` y un `fail`.
  Se pueden añadir casos `unknown` y casos similares válidos. No ejecuta los
  programas de ejemplo.
- `enable` exige que todos los ejemplos hayan pasado con esa definición y esa
  implementación del engine.
- `disable` conserva el conocimiento y lo excluye de la ejecución habitual.
- `show(full=True)` permite revisar consulta, ejemplos y resultado de validación.

La validación demuestra discriminación sobre esos ejemplos, no precisión general
ni corrección del contrato elegido. Los cambios de regla, bibliotecas y engine
invalidan la validación. Las escrituras usan publicación atómica y comprueban
que la definición no haya cambiado durante una operación concurrente.

Los archivos revisables viven en `.ken/checks/rules/<id>.json`. Los recibos viven
en `.ken/checks/runs/<run_id>.json`. No se guardan ternas ni se depende de
`experiments/`. Es una capa de contratos sobre el ejecutor KQL existente; no
implementa otro parser ni otro evaluador de comportamiento.

## Comprobaciones y comparación

```python
ken_check()                           # reglas habilitadas y validadas
ken_check(rules=["storage.return-id"]) # también permite diagnóstico de borradores
ken_check(scope="changes")           # reglas relevantes al diff y archivos nuevos
ken_check(path="src/store.py")        # selecciona reglas relacionadas
ken_check(compare="last")             # compara con el último recibo
ken_check(run_id="...", full=True)    # lee historia, sin ejecutar
```

`path` y `changes` seleccionan **reglas**, sin reducir su dominio de evaluación.
Una regla declarada sobre `src` se comprueba sobre `src`, aunque el cambio se
haya localizado en un único archivo. Esto evita certificar ausencia después de
haber eliminado precisamente los archivos necesarios de la búsqueda.

`changes` requiere un worktree Git con HEAD e incluye cambios staged, unstaged,
archivos nuevos y rutas borradas/renombradas. El estado interno de Ken se excluye.
La selección incorpora dependencias por imports; si no puede excluir una regla
con seguridad la incluye y explica el motivo en `selection_evidence`. Cada
comprobación conserva también las huellas de imports fuera del alcance de la
consulta. Estos archivos no pasan a ser lugares adicionales donde satisfacerla.
Recall vuelve a descubrir los imports: un destino antes ausente que aparece
después también invalida la comprobación. La vigencia incluye resultados por
regla y rutas cambiadas; para detalle por adaptador conviene una regla por adaptador.

Estados: `pass`, `fail`, `unknown`, `not_applicable`. Un análisis incompleto,
truncado, con candidatos desconocidos o cobertura incompleta produce `unknown`.
No seleccionar reglas no produce un éxito vacío. Las reglas habilitadas que
requieren revalidación aparecen como omitidas y mantienen estado desconocido.

El worker acota captura, preparación y consulta con un timeout del proceso. El
presupuesto se reparte entre consultas; por defecto 10 s y 100 filas. Los límites
de procesos, índices y memoria son los del engine actual: no hay una garantía
nueva de límite global de RAM. El recibo conserva la consulta, bibliotecas,
revisión, inventario fuente, evidencia y cobertura. La captura se comprueba antes
y después, pero no equivale a un snapshot atómico del sistema de archivos.

La comparación exige la misma definición, alcance y engine. Cambios incompatibles
se etiquetan `not_comparable`; incertidumbre produce `inconclusive`. No realiza
matching semántico de renombres ni prueba equivalencia de programas.

## Búsqueda, responsables y memoria

```python
ken_find(scope="structure", rules=["storage.return-id"])
ken_who(question="Who saves a user and returns the identifier?", path="src")
ken_related(target="src/store.py", relation="checks")

ken_remember(
    topic="storage-return-contract",
    content="El wrapper observado conserva el identificador del almacenamiento.",
    check_run=before["run_id"],
    anchor_file="src/store.py",
)
ken_recall(topic="storage-return-contract", detail="summary")
```

La búsqueda por reglas registradas utiliza sus consultas y mantiene su alcance;
no guarda un nuevo recibo. Los selectores de contratos y los del catálogo se
ejecutan en llamadas separadas.

`ken_who` comparte una adquisición entre candidatos y sus imports, con presupuesto
total de 3 s. `responsibility_map` muestra entrada candidata, coordinación candidata,
delegación y ejecutor candidato, como hipótesis estructurales. Las ubicaciones
corresponden a las declaraciones reales. No cambia el score documental ni lo
convierte en probabilidad. `verify=False` omite la observación. Módulos y clases
pueden aportar métodos al mapa sin perder su propia documentación.
Ver [inspección entre archivos y recorridos completos](code-inspection.md).

Una memoria puede referenciar recibos `pass`, `fail` o `unknown`, conservando ese
estado. Guardarla exige que los inputs sigan coincidiendo. Recall comprueba
contenido, pertenencia al ámbito, regla y engine; los archivos nuevos también
invalidan la memoria. Usa un presupuesto de lectura y devuelve `unknown` si no
puede comprobar la vigencia. No vuelve a ejecutar KQL ni acredita que el texto
de la nota se deduzca de la consulta. Un recibo histórico sigue siendo histórico
después de realizar comprobaciones nuevas.

## Automatización

```python
ken_rule(action="enable", rule_id="storage.return-id", automatic=True)
```

Se reutilizan los hooks de Ken instalados. Un daemon actualizado agrupa ediciones
durante 0,5 s y comprueba reglas automáticas pertinentes en un único worker de
fondo, con 3 s por lote de sesión. El final del turno permite recoger cambios de
shell que no tengan rutas explícitas. Los avisos se entregan en el siguiente
prompt y se omiten si no cambió el resultado relevante. El inicio de sesión
muestra el último recibo y su vigencia, sin ejecutar consultas.

No se habilita automáticamente ninguna regla nueva ni se instala otro watcher.
MCP y daemon abiertos antes de actualizar el código necesitan reiniciarse para
cargar estas funciones. Sin hooks, todas las operaciones bajo demanda funcionan.

## CLI

```sh
ken tools rule
ken tools rule --action show --rule-id storage.return-id --full
ken tools rule --action validate --rule-id storage.return-id
ken tools rule --action enable --rule-id storage.return-id --automatic
ken tools check --rules storage.return-id
ken tools check --scope changes --compare last
ken tools related src/store.py checks
ken tools remember storage-return-contract --content "Contrato observado" --check-run RUN_ID
```

`ken tools rule --action create --definition '<objeto JSON>'` recibe la definición
completa. Para otro proyecto, usar `ken tools --path /proyecto ...`. El JSON de
stdout conserva el estado del contrato; un `fail` es un resultado válido de la
tool, no un error de protocolo. Una integración CI debe interpretar ese estado.
El adaptador `python scripts/check_contracts_ci.py --root .` devuelve código 0
para `pass`, 1 para `fail`, 2 para `unknown` y 3 para `not_applicable`.
No habilita reglas ni instala un workflow automáticamente.

## Verificación

Las suites `test_checks.py`, `test_check_tools.py` y `test_check_automation.py`
cubren el ciclo completo, MCP stdio real, CLI, memoria, invalidación, cobertura,
timeouts y eventos del daemon. Las pruebas de responsabilidad y memoria anteriores
siguen comprobando sus contratos. La validación de KQL se ejecuta por separado;
no se presenta esta integración como conformidad completa de todos los perfiles.
