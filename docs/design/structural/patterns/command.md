# Command

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/command.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** representación de acción, receptor/capturas, invocador y ejecución
diferida; undo opcional. **Grafo:** callable/objeto encapsula operación y datos;
se almacena o transmite a un invocador que la activa. Admitir argumentos en execute.

| Lenguaje | Fragmento de encapsulación e invocación |
|---|---|
| P | `queue.append(lambda: doc.insert(text))` / `queue.pop(0)()` |
| JS | `queue.push(() => doc.insert(text)); queue.shift()();` |
| TS | `const cmd: () => void = () => doc.insert(text); queue.push(cmd);` |
| J | `Runnable cmd = () -> doc.insert(text); queue.add(cmd);` |
| CS | `Action cmd = () => doc.Insert(text); queue.Enqueue(cmd);` |
| CPP | `std::function<void()> cmd = [&doc, text]{ doc.insert(text); }; queue.push(cmd);` |
| G | `cmd := func(){ doc.Insert(text) }; queue = append(queue, cmd)` |
| R | `let cmd = move \|\| doc.insert(text);` seguido de almacenamiento como `FnOnce` compatible |

**Portabilidad:** closures y modos de captura esenciales; en Rust la acción puede
consumirse una sola vez. **Negativo:** helper que delega inmediatamente, sin
encapsulación observable como valor/objeto de acción. **Límite:** no todo callback
es Command; interfaz de invocación, payload y uso diferido refuerzan la interpretación.

## Discriminación de acciones y consultas

La firma de delegación sin argumentos también acepta clones y getters. Requests
PreparedRequest.copy consume copias de campos para construir otro objeto; Cobra
getUsageTemplateFunc devuelve una plantilla encontrada en el padre. Ninguno de
esos testigos acredita una acción Command aunque exista un invocador separado.

La revisión implementada en IR 1.25.0 conserva el invocador tipado y exige uso de acción: una
llamada al receptor como sentencia, con resultado descartado, o el retorno de
una llamada resuelta cuyo método escribe estado del receptor. El IR distingue
el descarte en una sentencia de llamadas usadas como argumentos, asignaciones,
retornos, condiciones o expresiones compuestas. Paréntesis y await transparentes
conservan ese uso; un tail expression Rust no equivale a descartar su valor.

No se exige void ni un nombre execute/run. Un comando puede devolver el resultado
de una acción o tener un método copy adicional sin que ese método sea su ejecución.
Getters con efectos y llamadas puras descartadas pueden compartir esta forma;
las firmas siguen requiriendo revisión de intención. Comandos que retornan valores
con efectos externos no modelados necesitan evidencia adicional, no exclusión
por nombres de métodos o por construir objetos dentro de su implementación.

La variante adicional `retained-object` admite también cálculos puros: exige
que un invocador almacene el objeto Command recibido y lo invoque desde otro
método. No presupone que todo Command tiene efectos. Una query almacenada puede
compartir esa firma; la distinción de intención sigue requiriendo revisión.
La relación temporal de almacenamiento/ejecución y la estabilidad de aliases
no están probadas por el resumen de asignaciones actual.


## Comandos en lotes de trabajo — IR 1.30.0

`queued-object` reconoce almacenamiento mediante un contrato, activación del elemento
iterado y vaciado posterior del mismo campo, con receiver retenido por la implementación.
Admite también entrada sin tipo cuando un caller observado suministra el tipo concreto.
Reutiliza la operación pública de la regla moderna `architecture.batch-work-queue`.
Ver [diseño, variantes y límites](../queued-command.md). No prueba orden FIFO,
exactamente una vez ni exclusividad frente a callbacks one-shot.

## Retención por contrato nominal — IR 1.38.0

`retained-contract` conecta el contrato almacenado por el invocador con el slot
sobrescrito por el comando concreto. La operación pública `command.retained_dispatch`
expone invoker, setter, input, storage, invoke, dispatch, contract y slot; exige
retención final soportada y despacho desde otro método de la misma clase.
La variante añade un receptor retenido desde el constructor y una llamada al
receptor con resultado descartado en la acción. Tiene tests en Python, TypeScript,
Java, C# y C++; en C++ contempla inicializadores con paréntesis y braces.

La operación pública también sirve para buscar servicios inyectados: por sí sola
no establece intención Command. Tampoco identifica qué subtipo se seleccionará
en ejecución ni prueba que el cliente configure antes de invocar. Las variantes
anteriores conservan sus contratos; este requisito de última escritura no debe
atribuirse automáticamente a todas. Ver [contrato y evaluación](../cpp-constructor-initializers.md).
