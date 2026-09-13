# Auditoría multilenguaje: problemas y posibles causas

Fecha del informe inicial: 2026-09-12. Los números de la tabla son históricos.
Las revisiones posteriores corrigen parte de los hallazgos; IR 1.31.0 documenta
[Builders de producto almacenado y copia Rust](stored-product-builder.md).
Se descargaron cinco proyectos públicos en `/tmp/ken-real-repos/`, se leyeron sus
fuentes y se ejecutaron las 23 consultas GoF actuales. No se ejecutó código de los
proyectos ni se instalaron sus dependencias. Los alcances, exclusiones, commits,
hashes de archivos/motor y resultados se conservan en los JSON.

## Corpus y resultados brutos

| Proyecto / commit | Lenguaje | Archivos | Candidatos GoF | Diagnósticos | Evidencia |
|---|---|---:|---:|---:|---|
| [commons-io](https://github.com/apache/commons-io/tree/f720b24227eb6972d4281d330ddb64c1416f81a4) | Java | 277 | 9 | 0 | [commons-io.json](commons-io.json) |
| [rxjs](https://github.com/ReactiveX/rxjs/tree/54796b38a57e6309f9861e174737479bb3f63f61) | TypeScript | 123 | 4 | 0 | [rxjs.json](rxjs.json) |
| [serilog](https://github.com/serilog/serilog/tree/49b5339ce85385dc52d4d8e8f2b8308becf23506) | C# | 113 | 3 | 300 | [serilog.json](serilog.json) |
| [cobra](https://github.com/spf13/cobra/tree/adbc8813901bba65827259daa8e22ff94ec1f30e) | Go | 19 | 0 | 0 | [cobra.json](cobra.json) |
| [rust-log](https://github.com/rust-lang/log/tree/8034743dd9d7f7583bd9a670271483d176130911) | Rust | 9 | 0 | 0 | [rust-log.json](rust-log.json) |

Total: **541 archivos y 16 candidatos**, sin contar otra vez aliases `gof.*` ni
consultas auxiliares de generadores. Las 23 evaluaciones completaron en cada proyecto;
eso no implica parsing completo (véase Serilog), ni ausencia de patrones donde hubo cero.
Commons IO: `src/main/java/`; RxJS: `packages/rxjs/src/`, excluyendo `*.spec.ts` y
`*/testing/*`; Serilog: `src/Serilog/`; Cobra: archivos admitidos del repo; log: `src/`.
Se aplican además las exclusiones comunes del runner, registradas en cada manifiesto.
Rust puede incluir módulos de test bajo cfg dentro de un mismo archivo: no se preprocesó.

Los corpus son de producción, no colecciones didácticas de patrones. No existe un
oráculo exhaustivo de intención: no se calcula precisión o recall global.

## Hallazgos y estado de las correcciones

Cada entrada separa observación y posible causa, e indica un futuro test reducido.
No se aplicarán filtros por nombres para hacer desaparecer casos incómodos.

### JAVA-01 — Rollover de bloques detectado como Builder

**falso positivo · commons-io · pendiente.** [Fuente fijada al commit](https://github.com/apache/commons-io/blob/f720b24227eb6972d4281d330ddb64c1416f81a4/src/main/java/org/apache/commons/io/input/ReversedLinesFileReader.java#L285).

Observación: FilePart.rollOver construye el bloque anterior usando sobrantes. No es construcción por etapas de un producto solicitado por un cliente.

Posible causa: La query acepta cualquier método que modifique estado luego usado para construir un objeto; no distingue avance de cursor de un protocolo Builder.

Grado de confirmación: Alta sobre la condición demasiado amplia; no se propone filtrar por nombres.

Regresión propuesta: Negativo: lector de bloques que modifica sobrantes y retorna el bloque anterior; positivo: setters + finalización usando los mismos campos.

### JAVA-02 — El mismo rollover aparece como Prototype

**falso positivo · commons-io · pendiente.** [Fuente fijada al commit](https://github.com/apache/commons-io/blob/f720b24227eb6972d4281d330ddb64c1416f81a4/src/main/java/org/apache/commons/io/input/ReversedLinesFileReader.java#L285).

Observación: El nuevo FilePart representa otro bloque (partNumber - 1), no una copia del actual.

Posible causa: Retornar el mismo tipo con algún campo del objeto original es insuficiente para inferir copia.

Grado de confirmación: Alta: se revisó el constructor llamado y el argumento que cambia la identidad del bloque.

Regresión propuesta: Contrastar copia de estado con creación de sucesor del mismo tipo; conservar roles y transformaciones de argumentos.

### JAVA-03 — Jerarquía de streams repartida entre archivos sin enlace

**falso negativo / capacidad ausente · commons-io · pendiente.** [Fuente fijada al commit](https://github.com/apache/commons-io/blob/f720b24227eb6972d4281d330ddb64c1416f81a4/src/main/java/org/apache/commons/io/input/AutoCloseInputStream.java#L39).

Observación: AutoCloseInputStream extiende ProxyInputStream; el probe conserva BASE_NAME pero no produce SUBTYPE_OF, aunque ambas clases se incluyeron. No se detecta la colaboración con hooks de la clase base.

Posible causa: El resolvedor actual busca clases por archivo y sólo tiene modelos de imports Python/JS/TS; faltan paquetes/imports Java y tipos JDK.

Grado de confirmación: Confirmada la arista ausente en ir-probes.json; causa consistente con el resolvedor.

Regresión propuesta: Dos archivos del mismo paquete Java con clase abstracta y override; luego import desde otro paquete e herencia de java.io.FilterInputStream.

### JAVA-04 — Bridge/Strategy en Counters: revisar intención

**candidato ambiguo · commons-io · pendiente.** [Fuente fijada al commit](https://github.com/apache/commons-io/blob/f720b24227eb6972d4281d330ddb64c1416f81a4/src/main/java/org/apache/commons/io/file/Counters.java#L33).

Observación: Se obtienen 3 Bridge y 1 Strategy en tipos de contadores. Hay composición de Counter y operaciones delegadas; falta decidir si representan estrategias independientes o agregación numérica.

Posible causa: La combinación herencia + inyección + dos subtipos describe muchas composiciones que no son decisiones GoF deliberadas.

Grado de confirmación: Hipótesis de sobreclasificación; no se etiqueta como falso positivo confirmado.

Regresión propuesta: Muestra negativa de una estructura que agrega tres contadores; positiva con selección real de algoritmo. Revisar roles ampliados antes de modificar la consulta.

### TS-01 — Subject no detectado como Observer

**falso negativo · rxjs · corregido en IR 1.22.0.** [Fuente fijada al commit](https://github.com/ReactiveX/rxjs/blob/54796b38a57e6309f9861e174737479bb3f63f61/packages/rxjs/src/subject.ts#L10).

Actualización: `snapshot-registry` detecta Subject, AsyncSubject y
PerSubscriptionSubjectBase. Se revisaron nueve llamadas de notificación y los
registros correspondientes. Hay 95 tests nuevos en Python/JS/TS y un nuevo
escaneo de los 123 archivos. [Evidencia, métricas y límites](observer-snapshots.md).
Las observaciones siguientes describen el fallo original.

Observación: La clase registra subscribers en un Set, notifica next/error/complete y elimina suscriptores. Observer devuelve cero.

Posible causa: El alta está en una closure pasada a super, no en un método de alta; next itera Array.from(registro), y error/complete usan un alias local. La query exige identidad directa de colección y propietario.

Grado de confirmación: Confirmado por ir-probes.json: INSERTS_INTO está dentro de la closure y ITERATES_CALLS apunta al call Array.from o a una variable distinta.

Regresión propuesta: Observer con private fields, alta en closure, snapshot Array.from y alias local; negativo con una colección distinta de la registrada.

### CS-01 — Yield de funciones locales atribuido a un método bool

**falso positivo y omisión de las funciones locales · serilog · pendiente.** [Fuente fijada al commit](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/Capturing/PropertyValueConverter.cs#L172).

Observación: TryConvertEnumerable devuelve bool, pero aparece como Iterator. Los yields están en MapToDictionaryElements y MapToSequenceElements, funciones locales de las líneas 189 y 238.

Posible causa: local_function_statement no pertenece al conjunto FUNCTIONS del lowerer, por lo que no establece un nuevo owner de operaciones.

Grado de confirmación: Confirmada en el probe de tree-sitter: ambos nodos están presentes y recognized_callable=false.

Regresión propuesta: Método bool que contiene dos funciones locales IEnumerable con yield: sólo las dos funciones locales deben ser generadoras; repetir con funciones anidadas adicionales.

### CS-02 — Parsing de código condicionado por compilación

**error de cobertura · serilog · pendiente.** [Fuente fijada al commit](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/Capturing/MessageTemplateProcessor.cs#L29).

Observación: El escaneo produce 300 diagnósticos (no 300 archivos). Hay firmas alternativas separadas por #if FEATURE_SPAN, #else y #endif antes de un cuerpo compartido.

Posible causa: El árbol sin configuración de preprocesador no representa limpiamente todos los caminos compilables; también hay sintaxis moderna que requiere evaluación separada.

Grado de confirmación: Confirmada la coincidencia de errores con firmas condicionales; otras causas aún no aisladas.

Regresión propuesta: Fixtures con firmas bajo #if/#else y cuerpo compartido, tanto FEATURE_SPAN activo como inactivo. No eliminar ramas sin declarar configuración.

### CS-03 — LoggerConfiguration no detectado como Builder

**falso negativo con parsing parcial · serilog · pendiente.** [Fuente fijada al commit](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/LoggerConfiguration.cs#L127).

Observación: CreateLogger finaliza una configuración acumulada mediante WriteTo, colecciones de sinks y callbacks. Builder devuelve cero.

Posible causa: Propiedades de configuración, delegación a otros configuradores, callbacks que escriben colecciones, new con tipo inferido y símbolos entre archivos superan el modelo de campo directo. Los errores de parsing impiden aislar todavía la causa dominante.

Grado de confirmación: Hipótesis compuesta; no afirmar que sea un único fallo de query.

Regresión propuesta: Primero fuente válida sin directivas; luego propiedad WriteTo que registra un sink por callback y CreateLogger que consume esa colección.

### CS-04 — ForContext clasificado como Prototype

**candidato ambiguo / probable falso positivo · serilog · pendiente.** [Fuente fijada al commit](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/Core/Logger.cs#L82).

Observación: ForContext retorna otro Logger con un enricher y el logger actual como sink. Es contextualización/composición, no necesariamente clonación.

Posible causa: La query interpreta construir el mismo tipo con campos existentes como copia; ignora que el receptor se usa como dependencia del nuevo objeto.

Grado de confirmación: Revisión de fuente completada; clasificación de intención aún discutible.

Regresión propuesta: Contrastar clone con wrapper del mismo tipo que recibe this y un comportamiento adicional.

### CROSS-01 — Resultados positivos pese a diagnóstico de parsing

**riesgo de confianza · serilog · pendiente.** [Fuente fijada al commit](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/Capturing/PropertyValueConverter.cs#L172).

Observación: Las consultas tienen complete=true aunque el proyecto tiene errores de parsing, y TryConvertEnumerable se emite como structural_match.

Posible causa: complete indica enumeración, no cobertura semántica; falta granularidad por región/owner para degradar evidencia contaminada. No corresponde cambiar complete globalmente ni ocultar todos los hechos válidos.

Grado de confirmación: Confirmado en JSON y definición del API; propuesta de diseño pendiente.

Regresión propuesta: Error en una región y otra región válida: conservar hits válidos y marcar unknown los que dependen del subárbol dañado o de owners no resueltos.

### GO-01 — Command basado en callbacks no detectado

**falso negativo · cobra · pendiente.** [Fuente fijada al commit](https://github.com/spf13/cobra/blob/adbc8813901bba65827259daa8e22ff94ec1f30e/command.go#L1014).

Observación: execute llama RunE(c,args) o Run(c,args); ExecuteC selecciona el comando y llama execute. El catálogo devuelve cero Command.

Posible causa: La variante exige un método sin argumentos, receptor tipado separado e invocador de ese método. Aquí la acción está en campos función y recibe argumentos.

Grado de confirmación: Confirmado el mecanismo en código; el detalle de enlaces de callbacks aún necesita un probe específico.

Regresión propuesta: Command Go con Run/RunE como campos función, selección por subcomando y argumentos; negativo con callback que sólo valida y no ejecuta.

### GO-02 — Árbol de comandos fuera de la variante nominal de Composite

**variante estructural no cubierta · cobra · pendiente.** [Fuente fijada al commit](https://github.com/spf13/cobra/blob/adbc8813901bba65827259daa8e22ff94ec1f30e/command.go#L1342).

Observación: AddCommand establece parent y añade hijos al slice commands; las operaciones recorren el árbol. Composite devuelve cero.

Posible causa: La query requiere SUBTYPE_OF y colección de un contrato base. Go puede expresar la estructura recursiva con un único struct y slices de punteros, sin herencia nominal.

Grado de confirmación: Confirmada estructura padre/hijos; considerarlo candidato Composite-like, no prueba automática de intención GoF.

Regresión propuesta: Tipo Go recursivo con []*Command y una operación que recorra hijos, sin inventar una relación de herencia.

### RUST-01 — Impl con lifetimes pierde métodos del builder

**falso negativo inicial · rust-log · asociación de impl corregida; detección validada en IR 1.31.0.** [Fuente fijada al commit](https://github.com/rust-lang/log/blob/8034743dd9d7f7583bd9a670271483d176130911/src/lib.rs#L1042).

Observación: RecordBuilder y MetadataBuilder tienen setters y build, pero el IR no les asigna ningún HAS_METHOD. Builder devuelve cero.

Posible causa: declare(impl_item) busca el spelling RecordBuilder<'a> como nombre exacto, mientras la declaración se registra como RecordBuilder. Faltan normalización y asociación de tipos genéricos.

Grado de confirmación: Confirmado HAS_METHOD vacío para ambos tipos en ir-probes.json; lookup literal visible en frontend.

Regresión propuesta: struct Builder<'a> + impl<'a> Builder<'a>, incluyendo &mut self, retorno Self y un impl de trait separado.

### RUST-02 — Producto almacenado, estado anidado y finalización con clone

**variante cubierta en IR 1.31.0 · rust-log.** [Fuente fijada al commit](https://github.com/rust-lang/log/blob/8034743dd9d7f7583bd9a670271483d176130911/src/lib.rs#L1235).

Observación: MetadataBuilder modifica self.metadata.level/target y build devuelve self.metadata.clone(); no construye el producto directamente en build.

Posible causa: La variante mutable busca argumento de construcción cargado de un campo directo; faltan rutas de storage anidadas y semántica del producto almacenado/copia.

Validación actual: el enlace de impl ya estaba corregido en IR 1.30, pero Builder
seguía en cero. IR 1.31 añade TYPE_HEAD para anotaciones genéricas, inicializadores
Rust y la variante stored-product con FINAL_MEMBER_INPUT y uso correlacionado de
prototype.derived_copy. El mismo commit y los mismos nueve archivos pasan de cero
a dos Builders: RecordBuilder y MetadataBuilder. Ver [testigos y límites](stored-product-builder.md).

Regresión propuesta: Builder con producto interno y finish por clone, y otro que devuelve/mueve el producto; no asumir que cualquier método llamado clone copia.

### JAVA-05 — Observer con clase plausible pero testigo de notificación incorrecto

**evidencia incorrecta / falso positivo del rol notify · commons-io · pendiente.** [Fuente](https://github.com/apache/commons-io/blob/f720b24227eb6972d4281d330ddb64c1416f81a4/src/main/java/org/apache/commons/io/monitor/FileAlterationMonitor.java#L181).

Observación: Al ampliar los roles de la query, notify se enlaza a start (initialize) y stop (destroy). El método real checkAndNotify usa observers.forEach con una lambda y no aparece como notify.

Posible causa: ITERATES_CALLS incluye ciclos de mantenimiento; la query no distingue notificar de inicializar/destruir. forEach y el cuerpo de la lambda necesitan flujo de callbacks. Proyectar sólo unit oculta que se encontraron testigos equivocados.

Grado de confirmación: Confirmada en commons-io-expanded-roles.json y lectura de start/stop/checkAndNotify.

Regresión propuesta: Una clase con subscribe, start, stop y notify mediante forEach. Sólo notify debe ser testigo de notificación; la versión sin notify no debe pasar por start/stop.

## Coincidencias útiles revisadas

- Commons IO: `Tailer.TailablePath.getRandomAccess` implementa el slot de creación
  y retorna `RandomAccessFileBridge`: compatible con Factory Method.
- Commons IO: `FileDeleteStrategy.delete/deleteQuietly` llaman `doDelete`, sobrescrito
  por `ForceFileDeleteStrategy`: Template Method claro.
- RxJS: cuatro funciones de `observable-async-generators.ts` usan async/yield para
  entregar valores. Coincidencias Iterator razonables, sin comprobar liveness/cancelación.
- Serilog: `MessageTemplateParser.Tokenize` produce tokens con yield: forma Iterator
  razonable, pero el resultado del proyecto debe leerse junto a sus diagnósticos.
- El Observer de `FileAlterationMonitor` tiene **testigos incorrectos confirmados**:
  start/stop, en lugar de checkAndNotify. No se cuenta como un acierto de la evidencia
  aunque el tipo tenga una colaboración Observer; véase JAVA-05.

## Prioridad de corrección propuesta

1. Propiedad de funciones locales C# y cobertura por regiones con errores.
2. Resolución de tipos entre archivos Java y asociación de impl genéricos Rust.
3. Flujo de colecciones: closures, snapshots y aliases de RxJS; callbacks Go.
4. Distinguir copia, sucesor y wrapper del mismo tipo; criterios Builder/Prototype.
5. Variantes con producto almacenado, configuración por callbacks y tipos recursivos.

Antes de corregir cada caso: escribir el positivo y un negativo cercano, fijar
expectativas sobre IR y resultados, luego repetir el mismo corpus con los mismos
presupuestos. No reemplazar todos los ceros por misses confirmados.

## Reproducción

```sh
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/commons-io --prefix src/main/java/ --output /tmp/commons-io.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/rxjs --prefix packages/rxjs/src/ --exclude-glob '*.spec.ts' --exclude-glob '*/testing/*' --output /tmp/rxjs.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/serilog --prefix src/Serilog/ --output /tmp/serilog.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/cobra --output /tmp/cobra.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/rust-log --prefix src/ --output /tmp/log.json
```

[Registro estructurado: 15 casos](issues.json) · [Probes del IR](ir-probes.json) ·
[Roles ampliados de Commons IO](commons-io-expanded-roles.json).
El único cambio al runner fue admitir `--exclude-glob` y registrar exclusiones.
Los hallazgos anteriores de Requests siguen en [su informe](../2026-09-12/requests.md):
Command falso positivo y Prototype omitido por copia mediante asignaciones posteriores.
Son registros históricos: Command se corrigió en IR 1.25 y la copia por campos
en [IR 1.26](prototype-field-copy.md).

### IR127-01 — Document.save aparece como Builder al recuperar el origen del retorno

**Falso positivo de intención · across-languages · pendiente.** Caso
`behavioral/memento/document_editor/typescript/`, mismas fuentes y commit que el
corpus v18. Document.setContent configura content; save construye ConcreteMemento
con ese campo y devuelve un local. Al exponer correctamente el origen de ese
retorno en IR 1.27, la query mutable-product lo acepta como Builder.

La evidencia de flujo es correcta. La firma es insuficiente para separar
construcción por pasos de proyección de estado de un objeto editable. Document
tiene además restore(memento), que recupera estado mediante getState a través
de IMemento. Hasta IR 1.27, la query Memento requería acceso directo a miembro y tipo
nominal exacto, por lo que no reconocía ese protocolo. IR 1.28 incorpora
`accessor-snapshot` y recupera Memento sobre Document; el FP Builder permanece.

No se solucionó filtrando nombres ni ocultando el retorno correcto. Los bindings
de constructor por callsite, getters del snapshot y restauración mediante contratos
ya están implementados en IR 1.28. Sigue pendiente revisar la fuerza de la firma
Builder frente a esa evidencia. Un Builder que
admita snapshots puede implementar ambos patrones, por lo que excluir cualquier
Memento tampoco sería una corrección general.

Ver [auditoría de valores retornados](returned-query-values.md). Las 54 presencias
esperadas del corpus se conservan, pero este match adicional es un FP documentado;
no se lo cuenta como mejora de cobertura.


### IR128-01 — Order aparece como Strategy y falta State

**FP de intención Strategy pendiente / FN State corregido en IR 1.29 · across-languages.** Caso
`behavioral/state/order_processing/typescript/`, commit
`efd075de92e42099e8ae24fc274dc0e7b86ba2f9`. Resolver la interface exportada IOrderState
habilita la firma Strategy: Order almacena un estado sustituible y delega acciones.
La lectura de state.ts confirma transiciones como NewOrderState.processPayment →
order.setState(new PendingPaymentState(order)), y PendingPaymentState.ship →
ShippedState. La intención del ejemplo es State. IR 1.29 lo reconoce mediante context-transition;
la clasificación Strategy previa permanece como ambigua.

La ausencia de transiciones en la evidencia de Strategy no prueba que no existan.
Hay que vincular acciones de estados concretos con cambios del mismo contexto y
comprobar el papel del parámetro-propiedad TypeScript `constructor(public order: Order)`.
Estas son posibles causas y trabajo pendiente, no una corrección ya verificada.
Conservar el match como ambiguo; no usar el nombre del directorio para suprimirlo.

La [auditoría IR 1.28](memento-accessors.md) registra tres casos esperados recuperados,
este match adicional y los testigos de Memento. Ninguna de estas cifras constituye
una matriz global de TP/TN/FP/FN.


### IR129-01 — Parámetros-propiedad revelan firmas Adapter demasiado amplias

**Seis FP de intención / solapamientos estructurales · across-languages · pendientes.**
Tres estados de order_processing y tres comandos de task_scheduler TypeScript
aparecen como Adapter al conservar campos declarados por parámetros de constructor.
Los hechos de campo, tipo y delegación son correctos. object-adapter exige implementar
un contrato y reenviar a un receptor de tipo distinto con otro nombre de método,
pero no exige evidencia suficiente de adaptación de entradas/resultados o de uso
como contrato adaptado. Esta forma también describe acciones State y Command.

No eliminar las propiedades del IR ni excluir un patrón por el nombre del otro.
Mejorar las firmas y exponer la ambigüedad. La [auditoría](state-context-transitions.md)
lista las seis clases y las fuentes exactas.

### IR129-02 — Callback de desconexión aparece como Strategy

**Intención ambigua / firma demasiado amplia · RxJS · pendiente.** Connection,
connectable.ts:27, guarda el callback disconnect recibido y lo invoca desde
unsubscribe. El constructor abreviado antes ocultaba ese almacenamiento.
strategy-callable reconoce correctamente composición mediante callback, pero no
distingue un algoritmo intercambiable de una acción de cierre. Revisar su claim y
modelar operaciones de ciclo de vida/deferred actions; no suprimir todos los callbacks
ni interpretar este match como un TP adicional certificado de Strategy.

### IR129-03 — Command almacenado en colección y ejecutado mediante contrato

**FN revisado · across-languages task_scheduler TypeScript · corregido en IR 1.30.**
SendEmailCommand, GenerateReportCommand y RunDatabaseBackupCommand guardan receiver
y datos. TaskScheduler.addTask(Command) añade comandos a tasks; runPendingTasks
itera esa colección, espera execute y después la vacía. Los campos abreviados ya
se resuelven en IR 1.29. IR 1.30 añade queued-object y la operación pública
architecture.batch-work-queue.drain: vinculan registro, elemento iterado del contrato,
acción concreta y reset posterior de la colección. Se recuperan los tres comandos
y el scheduler como lote de trabajo sobre el mismo commit y fuentes. La
[validación](queued-command.md) conserva los matches Adapter/Observer anteriores
como ambigüedades; un registro one-shot puede compartir la forma y no se declara
exclusividad de intención.

### RUST-03 — Clone estructural no certifica intención Prototype ni configuración

**límite de interpretación · IR 1.31.0 · pendiente de mayor discriminación.**
TYPE_HEAD permite reconocer tres usos derivados de copia: Record, Metadata y
KeyValues. Los dos primeros finalizan builders; el último copia un wrapper de
referencia bajo cfg de kv. Son usos de Clone revisados, no tres TP adicionales
de intención GoF. La operación pública no expande derives, prueba deep copy ni
evalúa cfg. No suprimirlos por nombre: una mejora necesitaría modelar propósito,
escape/consumo y configuración. La modalidad de campos inicializados con atributos
no equivale a un análisis de configuración de todo el programa.

### IR132-01 — Asignaciones históricas en pasos Builder

**Corregido para el contrato de entrada directa lineal.** mutable-product combinaba
WRITES y ASSIGNED_FROM aunque el estado o el parámetro se reemplazaran. Ahora
FINAL_MEMBER_INPUT conserva operación y última escritura, incluyendo campos
directos; cuerpos no soportados no hacen fallback a asignaciones históricas.
La matriz controlada de seis lenguajes mejora de 29 TP/9 TN/33 FP/1 FN a
30 TP/42 TN/0 FP/0 FN. Son 72 fixtures, no precisión/recall en proyectos reales.
La pérdida de parámetros en retornos C++ con puntero causaba el FN del fixture.
Se rechazan también asignaciones múltiples Go que ocultaban rebindings.

Document.save/setContent sigue coincidiendo con Builder y Memento; el problema
IR127-01 de intención no queda resuelto. Ver [auditoría](builder-input-writes.md).
