# Guía del IR y del buscador para implementar GoF

Referencia práctica verificada contra **IR 1.51.0**, `kenql/1` y
`ken-instructions/1`, el 13 de septiembre de 2026. Este documento explica la
implementación actual y dónde extenderla. El trabajo pendiente está en
[PLAN.md](../PLAN.md). Las secciones que dicen **PROPUESTO** no son APIs disponibles.

## 1. Qué leer y qué considerar implementado

| Necesidad | Documento | Cómo interpretarlo |
|---|---|---|
| Orden de tareas y criterios de cierre | [PLAN.md](../PLAN.md) | Trabajo por realizar; no ejecutar todas las fases a la vez |
| Funcionamiento actual del grafo | [Referencia IR](structural-ir.md) | Contratos operativos; leer la tabla inicial y la sección de la relación que se cambie |
| Sintaxis aceptada de búsquedas | [Consultas estructurales](structural-queries.md) | KenQL actual; usar ejemplos de esta guía para consultas ejecutables |
| Instrucciones, regiones, memoria y efectos | [Núcleo de instrucciones](design/structural/instruction-ir.md) | Modelo objetivo y sección de contratos ya implementados, separados |
| Algoritmo de cada GoF y contraejemplos | [Índice de los 23 ejercicios](design/structural/algorithms/README.md) | Leer sólo el patrón que se implemente y sus tests enlazados |
| Estado comprobado del catálogo | [Auditoría](structural-validation/multilanguage/catalog-ir-contracts.md) | 33 TOML, 104 definiciones ejecutables; no prueba cobertura semántica universal |
| Precisión, caché y rendimiento medidos | [Cierre del pipeline](structural-validation/multilanguage/ir147-pipeline-review.md) | Baseline con hashes y limitaciones conocidas |

Los documentos de `docs/design/structural/` incluyen propuestas históricas. En
particular, el formato `ken-rule/2`, `%map`, `%filter`, cuerpos de consulta con
aspecto de programa y `preserve` en KenQL **no están implementados** por aparecer
allí. Los TOML que se distribuyen están en `src/ken/structural/patterns/` y
`src/ken/structural/modern_patterns/`; `docs/design/structural/catalog/` contiene
borradores documentales. No implementar ni modificar el catálogo equivocado.

## 2. Las tres representaciones actuales

```text
archivos fuente
    │ frontend.lower_source(): Tree-sitter, sin ejecutar el programa
    ▼
IR de cada archivo: declaraciones + operaciones fuente + hechos
    │ semantic.link_project(): resolución y pases de análisis
    ▼
IR fuente del proyecto (graph.view == "source")
    ├─ kenql.query_graph() ─→ IR de consulta + FactIndex ─→ Engine/KenQL
    │                       (view == "query")
    └─ lower_instructions() ─→ Program: funciones/regiones/instrucciones
                              (schema == "ken-instructions/1")
```

**Actualmente la búsqueda consume la primera rama.** La exportación de
instrucciones es una segunda vista del mismo código, construida a partir de las
operaciones fuente preservadas. Extender un opcode en esa segunda rama no hace
que los TOML lo puedan consultar automáticamente. Hay que agregar el análisis y
la proyección consultable correspondientes. `lower_instructions` exige la vista
`source`; pasarle la vista `query` produce un error deliberado.

`build_project` en [service.py](../src/ken/structural/service.py) descubre archivos,
aplica límites, usa la caché por contenido y llama al frontend/enlazador. El
buscador público carga los TOML, valida consultas y dependencias antes de escanear,
y ejecuta reglas sobre el grafo preparado.

## 3. Grafo fuente: datos, identidad y evidencia

Las clases están en [model.py](../src/ken/structural/model.py):

| Clase/campo | Significado |
|---|---|
| `IR.entities` | Diccionario ID → `Entity`: clase, callable, parámetro, storage, llamada, valor, módulo, etc. |
| `Entity` | `id`, `kind`, `name`, `path`, `line`, `end_line`, `attrs` |
| `IR.operations` | Lista de `Operation` con ocurrencia fuente, propietario y estructura sintáctica |
| `Operation` | `id`, `kind`, `native_kind`, `parent`, `role`, `start`, `end`, `line`, `owner`, `attrs` |
| `IR.facts` | Lista de `Fact(subject, relation, object, attrs, evidence)` |
| `IR.capabilities` | Garantías explícitas de cobertura, algunas por sujeto/relación |
| `IR.diagnostics` | Errores/limitaciones del parsing/análisis; conservarlos en resultados |
| `IR.relations` | Nombres de relaciones declaradas; pueden existir aunque tengan cero hechos |
| `IR.version`, `IR.view` | Compatibilidad del esquema y separación de vistas |

`graph.add(subject, relation, object, evidence, **attrs)` agrega un hecho y declara
su relación. No inventar un tipo nuevo de nodo sin documentar quién lo crea,
cómo se identifica, cómo se serializa y cómo lo usa una consulta.

Un ID identifica un objeto del IR, no demuestra identidad de un objeto runtime.
`name` sirve para inspección o filtros solicitados por el usuario; no es una
prueba de que exista un GoF. Dos parámetros llamados `value` pueden tener IDs
diferentes. Dos lecturas del mismo storage pueden observar valores diferentes.

No todos los extremos de un hecho son entidades. Algunos son literales/estados,
p. ej. `supported`, o IDs de operaciones. No resolverlos siempre mediante
`graph.entities[id]` sin comprobar su clase de extremo. Los spans `start/end`
son posiciones en bytes fuente; no offsets en caracteres Unicode.

`role` preserva el nombre de campo de Tree-sitter o una cadena vacía. Por ejemplo,
un brazo puede ser `consequence`; no equivale a una arista de dominancia. El
`parent` de una operación es sintáctico, no el predecessor de ejecución.

`FactIndex` toma un snapshot de pertenencia de los hechos y agrupa por relación.
Sus índices de sujeto/objeto son bajo demanda. `rows(relation, subject, object)`
devuelve **un bucket de candidatos**, no la intersección final: el llamador debe
filtrar ambos extremos. No modificar hechos ni buckets durante consultas.

## 4. Proyección de consulta: llamadas, argumentos y valores

[kenql.query_graph](../src/ken/structural/kenql.py) construye una vista sin modificar
el grafo fuente. Conserva relaciones fuente y agrega identidades de ocurrencia:

```text
FUENTE:
    call ─ARGUMENT(position=0)→ operando fuente

CONSULTA:
    call ─ARGUMENT→ ocurrencia del argumento
    ocurrencia ─VALUE→ valor suministrado
    call ─RESULT→ valor resultado de esa llamada
```

Para una lectura de storage/parámetro, la proyección crea un valor de carga:
`loaded_value ─LOADED_FROM→ storage`. Esto no demuestra qué asignación llegó a
esa lectura. La relación histórica `ASSIGNED_FROM` puede producir
`VALUE_FLOW(modality=may)`; **no cambiarla a `must` para conseguir un match**.

Ejemplo que IR 1.48 rechaza en modo estricto dentro del subconjunto soportado:

```python
value = produce()
value = 0
consume(value)
```

El primer resultado no llega al argumento final. Unir sólo el nombre/storage con
sus asignaciones históricas inventaría una coincidencia. También debe rechazarse
`consume(value)` antes de la asignación de `produce()`. Un alias guardado antes de
la reasignación sí puede conservar el valor anterior; no prohibir todos los
aliases para evitar resolver este caso.

IR 1.48 añade `ARGUMENT_ORIGIN`: call fuente → operando, con posición,
IDs exactos de orígenes, casos origen/escritura y modalidad. La proyección añade
flujo must sólo para un único origen vivo demostrado. Dos llamadas al mismo
método son valores distintos; `UNIQUE_BINDING_WRITE` no prueba el flujo.
Se soportan llamadas standalone, RHS, anidadas y retornadas, incluso sin return
explícito en el callable. Los aliases se leen con el estado de esa ocurrencia.
Consultar [contrato actual](structural-ir.md#argument-read-site-provenance-ir-148)
y [entrega P1](structural-validation/gof-completion/P1-argument-occurrences.md).

IR 1.49 resuelve **bindings por bloque léxico**: una declaración dentro de un
bloque es una entidad `STORAGE` distinta de la del mismo nombre en un bloque
envolvente (`<owner>/STORAGE:nombre@<byte>` con atributo `block_scope`), y las
lecturas resuelven a la declaración más cercana. Aplica a `let`/`const` de JS/TS,
`local_variable_declaration` de Java y `variable_declaration` de C#; `var` de
JS/TS es function-scoped y no se separa. Consultar [contrato](structural-ir.md#block-scoped-locals-ir-149)
y [entrega P1.1](structural-validation/gof-completion/P1.1-scope-shadowing.md).

Relaciones existentes que no deben confundirse:

| Relación | Evidencia actual |
|---|---|
| `ASSIGNMENT_TARGET` / `ASSIGNMENT_VALUE` | Operandos de una escritura concreta; no una garantía temporal de que llegue al uso |
| `RETURN_ORIGIN` | Origen capturado por el pase soportado de retornos; consultar `RETURN_FLOW_STATUS` |
| `RETURN_REACHES` | Escritura que alcanza un retorno; no mezclar automáticamente con cualquier origen de otra rama |
| `RETURN_FIELD_STATE`, `FIELD_STATE_ORIGIN`, `FIELD_STATE_WRITE` | Testigo que conserva correlación entre retorno, asignación del objeto y campo |
| `FINAL_BINDING_INPUT` / `FINAL_MEMBER_INPUT` | Última entrada directa soportada del parámetro, bajo las exclusiones del pase |
| `CALL_BINDING`, `BINDING_PARAMETER`, `BINDING_VALUE` | Argumento ligado a parámetro de un destino soportado; `BINDING_VALUE` es operando fuente |
| `DECLARED_TARGET` / `TARGET` | Slot declarado o destino resuelto bajo el modelo disponible; no equivalen a dispatch runtime universal |

Un estado `supported` significa que se aplicó un modelo especificado. No convierte
un modelo de sintaxis lineal en prueba del heap ni de todos los caminos runtime.

## 5. Tutorial ejecutable: consultar y exportar el mismo código

Desde la raíz de Ken, guardar este bloque en un archivo temporal `.py` y ejecutarlo
con `.venv/bin/python`. Sólo se ejecuta el cliente de Ken; la cadena `source` se
parsea, no se importa ni se evalúa.

```python
import json
from ken.structural import lower_source, link_project, evaluate_query, lower_instructions
from ken.structural.instructions import Program

source = '''def produce():
 return 7
def consume(value):
 return value
def process():
 return consume(produce())
'''
graph = link_project([lower_source(source, "python", "sample.py")])
assert not graph.diagnostics
query = '''query direct_handoff {
 call(name: "produce") as $producer;
 require $producer RESULT $value;
 call(name: "consume") as $consumer;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $value;
 emit $producer, $consumer;
}'''
result = evaluate_query(graph, query)
assert result["complete"]
assert len(result["matches"]) == 1
program = lower_instructions(graph)
program.verify()
restored = Program.from_dict(json.loads(json.dumps(program.to_dict())))
assert restored.to_dict() == program.to_dict()
print(program.format())
```

Los filtros por nombre hacen el ejemplo pequeño. Una regla GoF debe usar contratos
y relaciones, con tests que renombren símbolos para evitar detecciones por nombre.
No usar `from ken.structural.kenql import parse_query`: `parse` compila KenQL;
`selectors.parse_query` corresponde al lenguaje de compatibilidad.

## 6. Núcleo de instrucciones: contrato implementado

Clases en [instructions.py](../src/ken/structural/instructions.py), adaptador en
[instruction_lowering.py](../src/ken/structural/instruction_lowering.py).

- `Program(source_version, functions, schema)`: unidad de intercambio JSON.
- `Function(id, name, language, parameters, places, body, status, reasons)`:
  un callable. Los parámetros refieren lugares de `places`.
- `Region(id, kind, instructions, outputs)`: instrucciones ordenadas y valores
  exportados hacia la instrucción contenedora.
- `Instruction(id, opcode, operands, result, source, effects, attrs, regions,
  result_type)`: una ocurrencia; `source` conserva trazabilidad a la operación.
- `Operand(kind, ref, role)`: `value`, `place` o `symbol`. No son intercambiables.

Un `place` es almacenamiento; un `value` es un resultado temporal con una
sola definición; un `symbol` identifica una declaración/callee, sin afirmar
su valor runtime. Un `slot.load` produce un valor nuevo incluso si lee el mismo
place que otra carga. La igualdad de sus contenidos requiere un análisis aparte.

```text
# Pseudocódigo explicativo; el impresor no tiene parser de entrada.
%a = slot.load @items
%k = slot.load @key
%address = index.addr %a, %k
%item = memory.load %address
slot.store @selected, %item
%object = slot.load @selected
%field = field.addr %object, "name"
memory.store %field, %new_name
return %object
```

La escritura del campo no reasigna `@selected`. Reemplazar `@selected` sí cambia
el binding. Una copia de una referencia a un objeto no implica copia profunda
ni independencia de sus campos. Las direcciones son valores del IR; no direcciones
reales obtenidas ejecutando el programa.

| Familia | Opcodes actuales | Precaución |
|---|---|---|
| Valores | `const`, `unary`, `binary`, `compare` | No inventar orden de evaluación o sobrecarga resuelta |
| Storage | `slot.declare`, `slot.load`, `slot.store` | Declaración no implica inicialización ni lectura |
| Memoria | `field.addr`, `index.addr`, `memory.load`, `memory.store` | Receptor, campo/índice y aliases importan |
| Invocación | `call`, `construct` | Callee/receiver/argumentos; efectos `invoke`, `unknown` cuando corresponda |
| Control | `if`, `choose`, `short_circuit`, `loop`, `iterate`, `iteration.value` | Regiones con evaluación condicional/repetida |
| Salida/suspensión | `return`, `throw`, `break`, `continue`, `yield`, `yield.delegate`, `await` | Suspensión no equivale a thread; cleanup no resuelto sigue desconocido |
| Fallback | `native` | Fuente y razón explícita de parcialidad, nunca una operación pura ficticia |

Contratos de regiones:

| Instrucción | Regiones ordenadas | Resultado |
|---|---|---|
| `if` | `consequence`, opcional `alternative` | Sin resultado; brazos sin outputs |
| `choose` | `consequence`, `alternative` | Cada brazo exporta un valor; sólo el seleccionado se evalúa |
| `short_circuit` | `rhs` | Izquierda ya evaluada; derecha condicional; respetar `result_policy` |
| `loop(form=while)` | `test`, `body` | Test exporta condición y se repite |
| `loop(form=do)` | `body`, `test` | Cuerpo antes del test |
| `loop(form=for)` | `init`, `test`, `body`, `update` | Init una vez; continue pasa por update |
| `iterate` | `body` | Iterable se evalúa una vez; cuerpo inicia con exactamente un `iteration.value` |

`verify()` comprueba referencias, unicidad de resultados, visibilidad por región,
firmas estructurales y layouts. No es un verificador de tipos completo ni prueba
alcanzabilidad. `status="lowered"` describe cobertura de traducción; puede seguir
habiendo efectos desconocidos. `partial` y sus razones nunca se deben borrar para
que un test o una query parezca preciso.

Los tipos estructurados viven en [type_refs.py](../src/ken/structural/type_refs.py).
Distinguen `any` (tipo declarado que admite cualquier valor) de `unknown` (sin
conocimiento suficiente), tipos nativos y argumentos de contenedores. Algunos
atributos heredados de la normalización antigua colapsan `Any`/`any` a `unknown`;
no utilizarlos para justificar garantías que requieren el descriptor estructurado.
Tipos básicos/arrays/maps presentes no implican sustitución genérica ni inferencia
completa de tipos asociados.

En 1.47, C++ binarios/comparaciones, optional chaining, expansiones de argumentos,
varias asignaciones compuestas y cuerpos con control no soportado pueden quedar
opacos. Revisar los tests de regiones/auditoría antes de ampliar una forma. Si una
traducción no puede conservar evaluación y efectos, emitir `native/partial`.

## 7. «No se modifica» y ruido permitido

Existe una API Python acotada en
[preservation.py](../src/ken/structural/preservation.py):
`preserve_binding(function, place, after=..., through=..., mode="strict")`.
Comprueba `(after, through]` dentro de una sola región ordenada. Devuelve
`Preservation(status, basis, witnesses, reasons)`, con estado `preserved`,
`violated` o `unknown`.

```python
from ken.structural import lower_source, link_project, lower_instructions
from ken.structural.preservation import preserve_binding

source = "def keep(x, other):\n z=x\n other=x\n return z\n"
fn = lower_instructions(link_project([lower_source(source, "python", "keep.py")])).functions[0]
store = next(i for i in fn.body.instructions if i.opcode == "slot.store")
result = preserve_binding(fn, store.operands[0].ref,
                          after=store.id, through=fn.body.instructions[-1].id)
assert result.status == "preserved"
```

Cambiar el trabajo intermedio por `z=other` invalida la propiedad. Cambiarlo por
`log(x)` hace que el análisis estricto no pueda probarla: el nombre `log` no es un
contrato de pureza. `mode="explicit-writes"` sólo hace un inventario de escrituras explícitas;
es una garantía más débil. No usarlo silenciosamente como prueba de preservación
completa. Proteger binding, identidad de objeto, campo y contenido de colección
son obligaciones diferentes. Su extensión a KenQL/regiones está en PLAN, no en
la gramática actual.

## 8. Cómo se ejecuta y compone KenQL

El parser produce `Query(name, nodes, exports)` y nodos de joins/paths/match/
alternativas. `Engine.validate` valida dependencias y roles; `Engine.execute`
evalúa con un `FactIndex`, presupuesto y modo de evidencia.

- `require`: join entre hechos, con variables `$nombre`; `different` exige IDs
  distintos, no valores runtime distintos.
- `match "id"(rol_publico: $variable)`: reutiliza una consulta nombrada. Todos los
  roles de ese match pertenecen a la misma coincidencia. Dependencias acíclicas.
- `any { ... } or { ... }`: alternativas; no mezclar sus testigos como si fuesen
  simultáneos. `emit nombre=$variable` define el contrato público de roles.
- `path $a RELACION{min,max} $b as $prueba`: límites 0…32. Primer testigo por
  extremo/modalidad; puede incluir ciclos para cumplir el mínimo, sin enumerar
  todos los recorridos convergentes.
- `not exists` y conteos superiores/exactos necesitan cobertura explícita por
  sujeto/relación. Grafo vacío o relación ausente no prueban ausencia runtime.

`strict` es el modo predeterminado. Las obligaciones desconocidas no se presentan
como matches confirmados. `possible` expone candidatos con razones de
incertidumbre. `complete=false` significa presupuesto insuficiente para enumerar;
`complete=true` no significa que el programa esté completamente modelado. Un
`structural_match` certifica la firma exigida por esa consulta, no intención GoF.

`execute_rules` carga/ejecuta consultas guardadas; `query_registry` expone raíces,
variantes y operaciones. El código de [rules.py](../src/ken/structural/rules.py)
reutiliza AST por texto dentro de una petición, sin caché mutable global. Preserva
el presupuesto independiente de cada ejecución y los presupuestos compartidos
con sus dependencias.

## 9. Contrato real de los TOML

Cada GoF conserva su ID corto, p. ej. `builder`, y sus `[[variants]]`.
`status="ready"` exige `query` parseable; `status="design"` no registra la variante.
`requires`, `graph_requirements`, `languages` y `query_claim` son metadata: no
agregan condiciones automáticas al motor. En particular, `languages` no es una
barrera de ejecución que arregle una query demasiado amplia.

`builder#mutable-product` selecciona una variante. `gof.builder` une las variantes
ready con roles públicos comunes. La query raíz corta está escrita en su TOML;
si se agrega una variante, hay que revisar **también esa query raíz** para evitar
que difiera de la unión canónica. El test de catálogo comprueba esta coherencia.

`[[operations]]` publica contratos reutilizables con `id`, `status`, `query`,
`description`, `caveat`. No ponerles campos de variante no aceptados por el loader.
Por ejemplo, `builder.directed_state` se invoca como cualquier otro named match:

```kenql
query directed_builders {
 match "builder.directed_state"(builder:$builder, finish:$finish, product:$product);
 emit $builder, $finish, $product;
}
```

Antes de crear otra variante, comparar con las ready: `command#stored-closure`
y `prototype#derived-clone` ya cubren formas concretas de conceptos más amplios
que todavía tienen variantes `design`. No duplicar la misma query con otro ID
para declarar que se implementó una forma nueva.

## 10. Dónde intervenir y qué no cambiar accidentalmente

| Necesidad | Archivos principales | Prueba inicial útil |
|---|---|---|
| Nueva sintaxis/ocurrencia | `frontend.py`, `syntax_graph.py` | `tests/structural/test_instruction_audit.py` y fixture específico |
| Tipo/contrato genérico | `type_refs.py`, `semantic.py`, módulos nominales | `test_type_refs.py`, `test_cpp_method_contracts.py` si aplica |
| Opcode/región/efecto | `instructions.py`, `instruction_lowering.py` | `test_instruction_ir.py`, `test_instruction_regions.py` |
| Origen temporal de valores | `return_flow.py`, pases de transfers y nuevo análisis planificado | `test_algorithm_facade.py`, `test_returned_query_values.py` |
| Protección de storage | `preservation.py` y futura extensión | `test_preservation.py` |
| Nuevo hecho consultable | Pase semántico + `kenql.py` (`RELATIONS`/proyección/validación) | Test de emisión y test de query, también en un grafo sin filas |
| Nueva variante/operación | TOML + `rules.py` sólo si cambia esquema | `test_catalog_ir_contracts.py`, test del patrón y sus negativos |
| Velocidad/caché | `model.py`, `cache.py`, `service.py`, `rules.py` | Pruebas de índices/caché y runner del pipeline |

Los nombres de módulos de la tabla son relativos a `src/ken/structural/`. Los
nombres de test son relativos a `tests/structural/`. Confirmar existencia antes
de crear otro archivo parecido: hay pruebas especializadas adicionales.

Para un nuevo hecho, documentar sujeto/objeto, tipo de extremo, ocurrencia,
modalidad, basis, condiciones de emisión y estados de análisis no soportado.
No basta con añadir su nombre a `RELATIONS`: debe producirse desde código fuente
real y sobrevivir los round trips fuente/query/JSON. Si modifica semántica
persistida, actualizar `IR_VERSION` y verificar invalidación de caché; cambiar
el esquema de instrucciones tiene además su propia decisión de compatibilidad.

## 11. Caché y rendimiento que hay que preservar

La caché actual de disco guarda unidades y grafo fuente completo comprimidos en
SQLite, con 500 MB decimales configurables por defecto. La clave usa contenido,
ruta/lenguaje, versión del IR y versiones de parsers. Un hit evita parsing/enlace;
no evita JSON, reconstrucción de objetos o proyección de consulta. Los índices
bajo demanda y la compilación por petición ya están implementados.

Una edición reutiliza las unidades sin cambios y vuelve a enlazar el proyecto;
no hay enlace incremental interarchivo ni caché persistente de resultados de
consulta. Nunca guardar Python ejecutable como formato del grafo. El plan no
requiere reescribir en Rust: primero medir el cuello de botella y conservar la
instalación normal de Ken con sus dependencias actuales.

Las mediciones finales están en el [informe de rendimiento](structural-validation/multilanguage/search-pipeline-review.md).
Incluye mejoras de búsqueda completa, una regresión del lote aislado de Flask y
probes descartados. No citar sólo la etapa más favorable ni comparar catálogos,
fuentes, modos, presupuestos o estados de caché distintos.
