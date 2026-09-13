# Command: acción representada y retenida

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[diseño de Command](../patterns/command.md) y el
[catálogo ejecutable](../../../../src/ken/structural/patterns/command.toml).

## Algoritmo en palabras

Una entidad prepara una acción encapsulando el receptor y los datos necesarios.
Entrega esa representación a un invocador, que puede almacenarla, encolarla o
transmitirla. Cuando corresponde, el invocador activa la acción sin necesitar
conocer los detalles de la operación del receptor.

En la variante de objeto retenido, el constructor conserva un receptor; otra
operación sin argumentos lo utiliza. El invocador recibe un objeto mediante un
contrato, lo guarda en un campo y dispone de otro método que llama al slot de
ejecución del campo. Un contrato más preciso puede exigir que el objeto activado
sea el mismo que se recibió y que los datos usados sean los capturados al crearlo.

La ejecución puede recibir un contexto explícito —cancelación, transacción o
entorno— además de los datos retenidos. También puede devolver un resultado o
representar un cálculo puro. No se deben imponer cero argumentos, void o efectos
de escritura a todas las variantes de Command.

Undo es opcional y constituye otro algoritmo. Puede registrar estado anterior,
una operación inversa o compensaciones externas. Invocar una función llamada undo
no acredita que revierta execute; la prueba debe relacionar las mismas partes de
estado y especificar qué se restaura ante errores o acciones intermedias.

## Roles e invariantes

| Requisito | Evidencia pertinente |
|---|---|
| Representación de acción | Objeto o closure que conserva operación/receptor/datos |
| Receptor capturado | Entrada del constructor/captura que llega al receiver de trabajo |
| Datos capturados | Campos/valores cerrados que llegan a argumentos de trabajo, si la variante lo exige |
| Invocador | Entidad que recibe/retiene la representación y activa el contrato |
| Retención | Asignación final o captura justificada; otro campo no acredita el campo usado |
| Activación | Llamada al slot correspondiente sobre el objeto seleccionado |
| Ciclo de vida | Orden y estabilidad entre retención y ejecución, cuando la búsqueda lo exige |
| Undo opcional | Relación entre efecto ejecutado y efecto inverso/estado restaurado |

La presencia de setter y execute no demuestra que alguien llame primero al setter.
Dos métodos de una clase pueden pertenecer a instancias diferentes. Un campo
modificado después de configurarlo puede contener otro objeto al ejecutar.
Retención estructural y demostración temporal de identidad son niveles distintos.

## Traducción al IR objetivo

El siguiente pseudocódigo expresa las identidades necesarias, sin introducir una
gramática KenQL nueva. Las funciones representan métodos separados: no afirman un
orden de llamadas observado.

```text
func Job.init(receiver, data) {
  %raddr = field.addr %self, "receiver"
  memory.store %raddr, %receiver
  %daddr = field.addr %self, "payload"
  memory.store %daddr, %data
}

func Job.execute() {
  %receiver = memory.load (field.addr %self, "receiver")
  %payload = memory.load (field.addr %self, "payload")
  call %receiver.work(argument[0]=%payload)
}

func Invoker.store(command) {
  memory.store (field.addr %self, "saved"), %command
}

func Invoker.flush() {
  %selected = memory.load (field.addr %self, "saved")
  call %selected.execute()
}
```

Las conexiones entre init/store y execute/flush requieren resúmenes de campos y
flujo interprocedural. Para afirmar identidad temporal se necesita además unir
instancias y verificar escrituras/aliases entre llamadas, con estados unknown
cuando callbacks, reflexión, concurrencia o código externo impiden hacerlo.

La operación pública existente command.retained_dispatch ya permite componer la
colaboración de retención y activación en otras búsquedas. Expone invoker, setter,
input, storage, invoke, dispatch, contract y slot. Esa operación por sí sola puede
describir un servicio inyectado: no implica intención Command.

Para payload mutable deben separarse captura por alias, copia de valor, copia
superficial y snapshot histórico. Si el comando necesita el texto tal como era al
encolarlo, conservar una referencia a una lista mutable puede romper el contrato;
si necesita leer la versión actual al ejecutarse, ese alias puede ser correcto.

## Variantes por lenguaje

La matriz nueva cubre objetos por contrato en Python, TypeScript, Java, C# y C++.
El resto de formas son requisitos de diseño, no cobertura inferida de esa matriz.

| Lenguaje | Forma representativa | Requisito específico |
|---|---|---|
| Python | Clase o lambda que captura receiver/data | Binding tardío de closure frente a captura por defecto; mutabilidad del payload |
| JavaScript | Closure guardada o encolada | Captura de bindings, this y activación posterior |
| TypeScript | Objeto por interfaz o función tipada | Contrato del slot y argumentos de contexto, además de captura |
| Java | Objeto Command/Runnable/Callable o lambda | Resultado opcional; interfaz retenida no identifica por sí sola el subtipo ejecutado |
| C# | Command, Action/Func y Task | Captura, retorno asíncrono, cancelación y espera de finalización |
| C++ | Objeto con receiver o std::function/lambda | Capturas por referencia/valor y lifetime; inicializadores de constructor |
| Go | Función capturada, objeto o channel de comandos | Valor retenido frente a envío, consumo y ejecución real |
| Rust | Closure move o objeto por trait | Fn/FnMut/FnOnce, consumo único y préstamo del receptor |

Una cola puede conservar orden FIFO, seleccionar por prioridad o ejecutar en
paralelo. La firma de almacenar, recorrer y limpiar no acredita ninguna política
de scheduling ni exactamente una ejecución. Encolar trabajo y esperar su término
son operaciones diferentes; yield/await separan etapas y permiten efectos ajenos.

## Pruebas y resultados

[test_algorithm_command.py](../../../../tests/structural/test_algorithm_command.py)
reutiliza las fuentes de
[retained-contract](../../../../tests/structural/test_retained_contract_command.py),
pero ejecuta la regla pública Command para detectar interferencias entre variantes.
No ejecuta las fuentes inspeccionadas.

| Casos nuevos | Estado | Evidencia |
|---|---|---|
| 30 positivos con ruido | Pasan | Setter/constructor; trabajo en acción/invocador/ambos; cinco lenguajes |
| 20 negativos | Pasan | Otro slot, entrada sobrescrita, receptor sobrescrito, acción sin trabajo |
| 3 payloads retenidos | Pasan | Receptor y datos guardados desde constructor y usados en trabajo |
| 5 campos vaciados antes de activar | xfail estricto | Falta prueba temporal de identidad en flush |
| 5 acciones con contexto | xfail estricto | Variante válida excluida por aridad cero |
| 3 payloads descartados | xfail estricto | Falta contrato fuerte que une datos capturados con argumentos |

En C++, el ruido es aritmética y descarte local; en los otros cuatro lenguajes
incluye logging de valores primitivos. Los negativos conservan trabajo en el
invocador cuando la llamada está presente. Los xfail son aserciones de requisitos
pendientes, no cobertura satisfecha; XPASS exige revisión explícita.

La nueva matriz suma **53 passed, 13 xfailed**. Con las regresiones existentes de
retención, acciones y GoF: **229 passed, 13 xfailed, 264 deselected**, en 17.70 s:

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_command.py tests/structural/test_retained_contract_command.py tests/structural/test_command_actions.py tests/structural/test_gof_executable.py -k command
```

## Estado de las variantes y necesidades del IR

El catálogo ya distingue command-object, stored-closure, retained-object,
queued-object y retained-contract. Sus contratos son diferentes: unos exigen
descarte/efecto observado; retained-object admite cálculos puros; queued-object
reutiliza una búsqueda de lote; retained-contract relaciona el slot nominal con
una implementación que conserva un receptor desde el constructor.

No se modificó el TOML en esta revisión. Un requisito de identidad temporal para
todas las variantes no puede derivarse de la mera existencia de una asignación,
y exigir el argumento capturado podría excluir comandos que usan defaults o
calculan dinámicamente su entrada. La aridad cero debe ampliarse mediante una
variante con contexto explícito y binding comprobado, no quitando la restricción
sin evidencia adicional.

El núcleo necesita poder expresar captura/retención, lectura de campo por
instancia, llamadas entre fases y estados de memoria. Para contratos de datos:
reaching definitions hasta el argumento; para undo: efectos e historia; para
colas/threads: envío, selección, activación y finalización separados. La ausencia
de esos hechos produce evidencia parcial, no una promesa de ejecución correcta.
