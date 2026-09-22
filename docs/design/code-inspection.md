# Inspección del programa y contexto reutilizable

El concepto central es una vista parcial del programa. Cada archivo conserva
sus símbolos y ubicaciones; KQL conecta identidades mediante declaraciones e
imports. No se concatenan archivos ni se ejecuta el código analizado.

## Interfaz

```sh
ken tools who 'Who writes vector manifests?' --path src/ken
ken tools related 'src/ken/checks/report.py::query_view' impact --path src/ken/checks --depth 3
ken tools related 'src/ken/vectors.py::_atomic_write' roles --path src/ken/vectors.py --depth 2
ken tools related 'src/ken/checks/report.py::query_view' available \
  --from-path src/ken/checks/integration.py --path src/ken/checks
```

`file::qualname` desambigua símbolos homónimos. `path` delimita el alcance de
análisis; `depth` limita el recorrido; `timeout_ms` limita el worker completo.
`--full` conserva observaciones KQL y snapshot. Los defaults siguen siendo
compactos. `who --no-verify` permite buscar sólo por documentación.

La adquisición empieza por el objetivo y pide vecinos bajo demanda. Una consulta
sobre `src` no necesita construir el comportamiento de todos sus archivos. Sigue
siendo útil delimitar el subsistema: se lee su estructura de imports para descubrir
llamadores, y los objetivos con muchos vecinos pueden agotar el presupuesto.
`unknown` no significa que no haya consumidores.

## Responsabilidades

| Componente | Rol |
| --- | --- |
| `inspection/queries.py` | Declarar las observaciones en KQL. |
| `inspection/exploration.py` | Coordinar las consultas desde el objetivo, dentro del presupuesto. |
| `inspection/observations.py` | Acumular evidencia coherente y conservar sus límites. |
| `inspection/imports.py` | Seleccionar dependencias para adquirir código. |
| `structural/python_imports.py` | Resolver ubicaciones explícitas de módulos Python, compartidas con el engine. |
| `inspection/graph.py` | Normalizar testigos y navegar identidades. |
| `structural_store/node_locations.py` | Recuperar ubicaciones canónicas sólo para las identidades proyectadas. |
| `inspection/roles.py` | Interpretar hipótesis de rol y explicar su base. |
| `inspection/impact.py` | Seguir consumidores de resultados. |
| `inspection/availability.py` | Ofrecer expresiones candidatas de acceso y sus obligaciones pendientes. |
| `checks` | Validar contratos, conservar evidencia y decidir cuándo repetirlos. |

Las queries comparten un worker, comprobación de consistencia y caches del engine.
Primero se localiza la declaración; después se consultan llamadas por identidad
exacta y usos de esas ocurrencias. `available` sólo necesita declaraciones. `who`
recorre salidas de sus candidatos, `roles` ambas direcciones e `impact` entradas.
KQL sigue siendo el único evaluador de semántica de programas.

## Frontera de imports

En Python se siguen imports explícitos, alias, imports relativos y disposición
`src/`. Un homónimo sin import no establece conexión. El planner puede leer la
estructura de imports sin construir el grafo de comportamiento de todos los
archivos. Un import nominal debe incluir el símbolo solicitado; un import de
módulo debe tener una referencia estática compatible. Compartir una dependencia
no conecta a todos sus usuarios. La siguiente frontera de `impact` sólo se adquiere
cuando se observa que el llamador retorna el mismo resultado. Transformaciones,
ambigüedad y ciclos detienen esa propagación. Los símbolos ocultados por parámetros
o variables no se conectan por nombre. Un import alternativo no adquirido o no
resuelto conserva la incertidumbre del binding; no convierte el candidato conocido
en un destino cierto.

Cuando la cobertura de imports de otro frontend no está declarada, la adquisición
conserva todo el alcance solicitado. KQL sigue siendo el responsable de resolver
las llamadas. Falta de información, presupuesto agotado y código no soportado
aparecen como incertidumbre; no como ausencia acreditada.

El argumento interno `kql2.service.search(source_paths=[...])` permite adquirir
una lista explícita sin copiar archivos. La respuesta declara `source_scope` y
su lista. La selección debe permanecer dentro del alcance; el inventario forma
parte del snapshot y del resultado de caché.

`acquisition` informa archivos adquiridos, estructuras de imports leídas, símbolos
expandidos y límite de profundidad. `--full` añade cada paso y consulta. Los
contadores `coverage.*.evaluations` distinguen consultas ejecutadas de observaciones
no solicitadas; la cobertura se refiere a las consultas y fronteras declaradas,
no a un inventario global. Nombres computados, imports dinámicos y dispatch de
runtime quedan fuera del seguimiento estático.

Si una consulta termina incompleta, se conserva la evidencia coherente obtenida.
Si el código cambia entre consultas, se descartan sus hechos para no mezclar
versiones. Un corte por el watchdog del proceso puede perder toda la evidencia;
si interrumpió una publicación, un reintento inmediato también puede encontrar
su lease pendiente. Los resultados conservan el motivo de incertidumbre.

## Roles y resultados

`who` y `related(..., "roles")` publican `entry_candidate`,
`coordinator_candidate`, `delegates` y `executor_candidate`. Son hipótesis
derivadas de llamadas observadas, no prueba de responsabilidad de negocio.
No observar llamadores no demuestra que una función sea pública.

`impact` observa usos como argumento, asignación, condición, operando y retorno
que el perfil KQL pueda acreditar. Propaga hacia los llamadores cuando el resultado
se retorna conservando su identidad; una transformación no es el mismo valor.
Cada ocurrencia de llamada tiene identidad propia. Un argumento se informa como
uso, sin prometer seguimiento arbitrario dentro del receptor. Los tests aparecen
por llamadas/usos observados, no como garantía de cobertura de assertions.

## Disponibilidad contextual

`available` devuelve expresiones candidatas como `backend.save` o `persist`
cuando hay declaración/import explícito en un contexto Python. No certifica
visibilidad en cualquier punto, inicialización, compatibilidad de tipos ni
equivalencia de efectos. Imports condicionales y métodos que necesitan instancia
no se presentan como disponibilidad cierta. Las obligaciones acompañan cada
expresión. No hay autofix.

## Recorridos

* **Debugging:** `who` localiza candidatos; `related(..., "impact")` presenta
  consumidores y tests; `read` permite inspeccionar el símbolo preciso. Las
  conexiones inciertas se conservan para decidir qué investigar después.
* **Refactor/migración:** guardar un `check` anterior, editar y comparar con su
  `run_id`. `matches_before` y `matches_after` muestran progreso incluso si una
  regla sigue fallando; las ubicaciones actuales muestran qué queda por revisar.
  No se infiere equivalencia de programas.
* **Contexto arquitectónico:** el mapa de roles resume un vecindario observado.
  Una conclusión revisada puede guardarse con fuentes en `remember`. `recall`
  muestra por regla qué entradas cambiaron, sin ejecutar KQL otra vez.
* **CI:** `python scripts/check_contracts_ci.py --root .` ejecuta las reglas
  adoptadas y devuelve 0/1/2/3 para pass/fail/unknown/not_applicable.

Una memoria útil conserva la explicación revisada y sus fuentes, además de la
comprobación. Un contrato que sólo demuestra presencia de `chmod` no demuestra
la expresión del modo o su éxito en ejecución; esos detalles deben atribuirse
al análisis de fuente correspondiente. Las pruebas con agentes conservan ambas
variantes para medir el costo de recuperar versus releer esa explicación.
`recall(detail="answer")` devuelve primero conclusión, fuentes, supuestos y vigencia.
Para un tópico exacto evita recuperar también sus vecinos. Si las entradas siguen
iguales y la pregunta coincide con el alcance y los supuestos de la conclusión,
el agente puede reutilizarla con atribución. Si falta evidencia, puede ampliar esa
memoria con `detail="full"` o leer el símbolo concreto. No se exige volver a recorrer
el grafo en cada sesión. `summary` añade explicación breve y más detalle de vigencia.
Ambos modos conservan la conclusión y sus supuestos completos
cuando caben en el presupuesto global. Si no caben, muestra `conclusion_omitted`
y una referencia `expand`, sin cortar silenciosamente una advertencia al final.

## Reproducción

```sh
python scripts/evaluate_historical_contracts.py --output /tmp/ken-history
python scripts/evaluate_contract_agent.py --output /tmp/ken-agent-evaluation --run-agents
python scripts/evaluate_contract_agent.py --output /tmp/ken-staged-evaluation --run-agents --case both
python scripts/evaluate_inspection.py --output /tmp/ken-inspection-evaluation --baseline
python scripts/evaluate_source_contracts.py --output /tmp/ken-contract-cycle
```

La evaluación histórica usa blobs exactos anteriores/posteriores a tres fixes
de Ken y variantes distractoras. Produce reglas JSON importables con
`ken tools rule --action create --definition "$(cat /tmp/ken-history/ken.manifest-permissions/rule.json)"`.
Son guardas estructurales específicas: sus límites se guardan junto con cada caso.
La evaluación con agentes necesita Codex CLI y acceso al modelo; trabaja en una
copia del código actual, deja trazas y métricas por sesión y no modifica el original.
