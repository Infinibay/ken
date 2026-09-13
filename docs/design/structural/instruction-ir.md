# Núcleo de instrucciones del IR

Diseño previo al código, 13 de septiembre de 2026. Este capítulo sustituye la
idea de usar una bolsa de relaciones como representación principal del cuerpo.
Las relaciones siguen siendo una vista útil para búsqueda; no constituyen por
sí solas un lenguaje de implementación.

Estado: el adaptador inicial está implementado en IR 1.46.0 y se inspecciona con
`ken structural ir --view instructions --format text`. La
[auditoría](../../structural-validation/multilanguage/instruction-core.md) distingue
esa entrega del modelo objetivo y de la migración pendiente del buscador.

IR 1.47 añade resultados condicionales choose/short_circuit, elementos por
iteración, for clásico/do, elif, cuerpos de constructores Java y receptores this
C#. La [revisión de los 23 GoF](gof-algorithm-contracts.md) explica qué necesidades
motivaron las extensiones. La [referencia operativa](../../structural-ir.md#instruction-core-and-algorithm-contracts)
mantiene el contrato exacto y las formas que todavía quedan opacas.

## Modelo objetivo

Un programa contiene declaraciones y funciones. Cada función tiene parámetros,
lugares de almacenamiento, tipos y una región de entrada. Una región contiene
instrucciones ordenadas; las instrucciones de control contienen otras regiones.
Los resultados temporales tienen identidad por ocurrencia y una sola definición.
Los bindings y el heap son memoria mutable: no se confunden con esos resultados.

```text
func rename(key, new_name) {
  %0 = slot.load @records
  %1 = slot.load @key
  %2 = index.addr %0, %1
  %3 = memory.load %2
  slot.store @item, %3
  %4 = slot.load @item
  %5 = field.addr %4, "name"
  %6 = slot.load @new_name
  memory.store %5, %6
  %7 = slot.load @item
  return %7
}
```

El ejemplo distingue la variable item del objeto al que apunta y de su campo
name. No modifica item al escribir name. La coincidencia entre los valores
cargados %4 y %7 requiere análisis de reaching definitions; compartir un nombre
o una dirección no basta para demostrar igualdad de contenidos.

## Vocabulario para describir algoritmos

Las siguientes preguntas forman parte del contrato de diseño y deben tener
evidencia independiente, sin deducir unas de otras:

| Pregunta | Evidencia requerida |
|---|---|
| ¿Se declara una variable? | Declaración de lugar, ámbito, tipo y fuente; un parámetro también tiene declaración propia |
| ¿Se asigna o modifica? | slot.store frente a memory.store; operador de actualización y valor anterior cuando corresponda |
| ¿Permanece sin modificación? | Intervalo explícito, propiedad protegida y efectos conocidos; ausencia de una escritura encontrada no basta |
| ¿Se pasa como argumento? | Ocurrencia del argumento, callee, posición/nombre/expansión y valor suministrado |
| ¿Se copia? | Copiar un valor a otro binding, alias del mismo objeto, copia superficial y copia profunda son hechos distintos |
| ¿Se pasa por referencia o por valor? | Convención del lenguaje y parámetro destino: no confundir una referencia a un objeto copiada por valor con un alias de la variable del llamador |
| ¿Cambia una colección? | Identidad de colección, insert/remove/replace/clear, elemento/clave y orden; distinguir reemplazo del binding de mutación de la colección |

No se convertirá indiscriminadamente x=y en deep_copy ni push/remove en una
operación de colección por su nombre. Las APIs modeladas conservarán basis y
certeza. Python y Java requieren describir valores que referencian objetos;
referencias C++, ref/out de C# y préstamos Rust requieren información adicional.
El adaptador inicial conserva argumentos posicionales y efectos desconocidos,
pero las convenciones de paso, copias y mutaciones de colecciones completas siguen
siendo pasos de migración. Los hechos existentes del grafo no se promocionan a
garantías más fuertes al exportarlos al núcleo.

## Familias de instrucciones

| Familia | Operaciones | Contrato |
|---|---|---|
| Valores | const, unary, binary, compare | Resultado por ocurrencia; operador nativo conservado, sin resolver sobrecargas |
| Bindings | slot.declare, slot.load, slot.store | Declaración separada de lectura/escritura; lugar léxico distinto del valor |
| Objetos | field.addr, index.addr, memory.load, memory.store | Dirección derivada de un receptor y campo/índice; no equiparar campos de todas las instancias |
| Invocación | call, construct | Callee, receptor y argumentos explícitos; efectos desconocidos salvo modelo justificado |
| Control | if, choose, short_circuit, loop, iterate, iteration.value, return, break, continue, throw | Regiones separadas; selección de resultados; elemento por iteración y orden test/body/update explícitos |
| Suspensión | yield, yield.delegate, await | Operandos conservados; un await puede permitir efectos concurrentes |
| Superficies nativas | native | Nodo fuente conservado y motivo de análisis parcial; nunca pureza implícita |

Los tipos serán descriptores, con any distinto de unknown, contenedores,
parámetros de tipo y spelling nativo. La ausencia de tipo es información parcial.
Los contratos del núcleo no deben depender de nombres de GoF, bugs o frameworks.

## Invariantes y efectos

preserve pertenece al lenguaje de búsqueda: no es una instrucción ejecutada por
el programa inspeccionado. Delimita un intervalo y una propiedad: binding, objeto
o campo. El motor debe entregar preserved, violated o unknown, junto con los
testigos. Una llamada desconocida, un alias o un await pueden impedir probar
preservación de un objeto. Un nombre como log no acredita pureza.

Los efectos del núcleo distinguen read/write de binding, read/write de memoria,
invoke, suspend y unknown. Una asignación a un parámetro no equivale a modificar
su objeto; una referencia C++ o un setter puede añadir efectos no resueltos.
Las escrituras directas de bindings permiten un primer análisis explícito y
acotado de intervalos. No se presentará como prueba general del heap o de aliases.

## Representación y migración

El núcleo tendrá esquema propio, serialización estructurada, impresor textual y
verificador de referencias/definiciones. El texto será inicialmente una vista
para inspección, no un parser alternativo ni una máquina virtual. El adaptador
parte de los nodos Tree-sitter ya preservados, sin volver a parsear con otro motor.
Cada instrucción conserva path, span de bytes y operación de origen.

Primera entrega: exportación de cuerpos a instrucciones para las formas comunes,
regiones y efectos explícitos, verificación, inspección desde CLI y tests de
fuente en varios lenguajes. Los nodos sin lowering seguro quedan native y marcan
la función como partial. Este adaptador aún no sustituirá todos los pases del
grafo: evita cambiar silenciosamente las queries existentes durante la migración.

Siguientes entregas necesarias: bindings por bloque totalmente resueltos,
reaching definitions/joins sobre el núcleo, efectos de llamadas y aliases,
regiones completas de excepciones y suspensión, contratos de evaluación por
lenguaje, gramática de cuerpos/preserve en KenQL y migración de los detectores.
Hasta entonces, no se debe afirmar que una exportación de instrucciones convierte
las firmas antiguas en pruebas del comportamiento completo.

La validación debe comprobar diferencias reales: reasignación frente a escritura
de campo; leer índices distintos; retorno anterior/posterior a una escritura;
logging intermedio; ramas mutuamente excluyentes; operadores con cortocircuito;
argumentos expandidos; funciones anidadas; cualquier opacidad produce partial.
No basta con tests de impresión: comprobar operandos, efectos y regiones reales.

## Contratos regionales implementados en 1.47

| Opcode | Entradas | Regiones / salida | Evaluación |
|---|---|---|---|
| choose | Un valor condición | consequence y alternative; cada una exporta un valor | Se evalúa sólo un brazo y ese valor define el resultado de choose |
| short_circuit | Valor izquierdo | rhs exporta un valor | Se evalúa rhs según and/or/nullish; el resultado respeta result_policy |
| iterate | Valor iterable | body empieza con iteration.value y no exporta resultado | Iterable una vez; obtención de elemento y cuerpo por vuelta |
| loop, form=while | Ninguna entrada directa | test exporta condición; body sin salida | test → body → test |
| loop, form=do | Ninguna entrada directa | body y test | body → test → body |
| loop, form=for | Ninguna entrada directa | init, test, body, update | init una vez; test → body → update → test |

Las salidas de regiones son referencias a valores definidos en su ámbito o en un
ámbito exterior visible. Un valor definido sólo en un brazo no se usa desde otro
ni desde la región padre: el padre consume el resultado de choose. Los bindings
son memoria mutable compartida por las regiones de esa función; esta tabla no
introduce automáticamente phi ni reaching definitions para sus lecturas.

iteration.value pertenece sólo al principio del body de un iterate. Captura el
valor suministrado por el protocolo de esa vuelta, no una constante ni una copia
profunda. Un slot.store posterior enlaza la variable del cuerpo; otra asignación
a ese slot sigue visible. Los contratos de borrow, lifetime, cierre y mutación
concurrente de la colección continúan desconocidos.

El presupuesto de anidamiento se comparte entre helpers de expresiones y
sentencias: encadenar accesos a miembros o llamadas no lo reinicia. Al agotarse,
la exportación conserva un nodo native con motivo nesting-limit; no certifica
la parte que no analizó.
