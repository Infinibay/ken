# Visitor: despacho ligado al elemento recibido

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[contrato general](../gof-algorithm-contracts.md#23-visitor), el
[diseño de variantes](../patterns/visitor.md) y la
[regla ejecutable](../../../../src/ken/structural/patterns/visitor.toml).

## Algoritmo en palabras

Un elemento recibe un visitante elegido por su cliente. El elemento selecciona
la operación de ese visitante que corresponde a su tipo y la invoca pasando su
propia identidad. El comportamiento reside en el visitante. Otra implementación
del visitante puede realizar una operación distinta sobre la misma familia de
elementos sin modificar cada clase de elemento.

En una variante que calcula un resultado, accept devuelve el resultado producido
por esa invocación, quizá después de registrar métricas independientes. En una
variante que acumula estado, accept puede devolver void y el visitante mantiene
el acumulador. No se debe exigir reenvío del resultado a todas las variantes.

El recorrido de una estructura es una colaboración adicional: puede residir en
el cliente, en un visitor o en los elementos compuestos. Visitor no implica por
sí mismo que accept recorra todo un árbol ni que visite cada nodo exactamente
una vez. La cobertura exhaustiva de tipos exige conocer la familia completa.

## Identidades y contratos

| Requisito | Prueba necesaria |
|---|---|
| Visitante recibido | Valor de entrada del parámetro de accept, conservado hasta el receptor de dispatch |
| Elemento actual | Identidad de self/this o préstamo/referencia correspondiente; otra instancia del mismo tipo no es suficiente |
| Operación seleccionada | Target/slot de la misma ocurrencia de llamada que recibe el elemento |
| Correspondencia de tipo | Parámetro pertinente del target corresponde al tipo del elemento; resolver overloads cuando los haya |
| Resultado, variante de cálculo | Resultado de esa llamada llega al return sin reemplazo ni mezcla no admitida |
| Familia | Contratos de varios elementos y visitantes cuando la búsqueda exige el patrón completo |

Un objeto callback que recibe self para logging sólo prueba una llamada. La
separación entre familia de elementos y operaciones externas, y el despacho
correspondiente, son condiciones más fuertes. Los símbolos pueden llamarse apply,
evaluate y Term: los nombres accept, visit y Visitor no acreditan el algoritmo.

## Traducción al IR objetivo

Este pseudocódigo combina instrucciones del núcleo con anotaciones de contrato
propuestas. `self.identity`, `target_slot` y `preserve` aquí explican obligaciones;
no constituyen una nueva gramática KenQL ya disponible.

```text
func Element.accept(visitor) {
  %received = slot.load @visitor
  %element = self.identity
  %answer = call %received.visit_element(argument[0]=%element)
            [target_slot=Visitor.visit_element(Element)]
  slot.store @answer, %answer
  %metric = binary +, 2, 3
  call @trace(argument[0]=%metric)
  %returned = slot.load @answer
  return %returned
}
```

La búsqueda une receptor, argumento y target sobre **esa misma ocurrencia call**.
Luego prueba que %received procede del parámetro de entrada y que %element es
la identidad del elemento actual. Para la variante de cálculo añade la relación
entre resultado y return. Un slot llamado visitor puede contener otro visitante
después de una asignación; que siga teniendo tipo Visitor no preserva su valor.

La formulación en palabras `congelar(visitor)` se traduce aquí a preservar el
valor recibido durante un intervalo, no a prohibir mutaciones de todo el objeto
visitor: un visitante acumulador necesita poder modificar sus propios campos.
Igualmente, proteger el binding answer no demuestra que un objeto resultado
mutable no haya cambiado internamente.

El núcleo ya representa slot.load/store, argumentos por ocurrencia, regiones y
efectos. Se necesitan reaching definitions para estas igualdades de valores,
contratos de identidad del receiver y resolución de dispatch para tipos/slots.
La query actual aún consume hechos del grafo, no un contrato de cuerpo sobre
estas instrucciones.

## Variantes por lenguaje

Los esquemas siguientes definen requisitos, no certifican soporte en todos los
lenguajes. La matriz nueva ejecuta sólo Python, Java y TypeScript.

| Lenguaje | Forma representativa | Diferencia relevante |
|---|---|---|
| Python | v.visit_number(self) | Nombre específico por elemento; tipos incompletos y overrides dinámicos pueden impedir resolver el contrato |
| JavaScript | v.visitNumber(this) | Identidad dinámica sin anotaciones; presencia del método no implica familia completa |
| TypeScript | v.visitNumber(this) con interfaz Visitor | Contrato estructural de método; sobrecargas/anotaciones no sustituyen el flujo de valores |
| Java | v.visit(this), con overload por elemento | La selección de overload y el despacho virtual del visitor son decisiones diferentes |
| C# | v.Visit(this), visitor con resultado o estado | ref/out y overloads necesitan modelar la ubicación del argumento, no sólo su valor |
| C++ | v.visit(*this), virtual o visitor genérico | Distinguir this puntero, *this objeto y referencia; evitar tratar dereferencia como copia del elemento |
| Go | v.VisitNumber(n) | Receiver por valor puede copiar el elemento; la variante debe aceptar identidad por valor o exigir puntero explícitamente |
| Rust | v.visit_number(self), traits y resultado asociado | Préstamo compartido/mutable o consumo del elemento; enum match sin visitor separado es otra organización |

Una implementación asíncrona puede devolver una promesa/future de la operación;
devolverla directamente y esperar su resultado son dos contratos distintos. Un
visitor generador puede producir yield por nodo: la creación del generador no
prueba que se haya ejecutado el recorrido. Estas variantes requieren consumo y
suspensión explícitos y no están cubiertas por la firma named-dispatch actual.

## Pruebas y mutaciones

[test_algorithm_visitor.py](../../../../tests/structural/test_algorithm_visitor.py)
crea y parsea fuentes, y ejecuta la regla pública gof.visitor con el registro
actual. No compila ni ejecuta las fuentes analizadas.

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_visitor.py
30 passed, 6 xfailed
```

| Casos | Estado | Qué verifican |
|---|---|---|
| 18 positivos | Pasan | Logging y aritmética antes/después/ambos; con y sin renombrado; tres lenguajes |
| 9 negativos básicos | Pasan | Otro elemento, otro receptor o parámetro de operación sin contrato del elemento |
| 3 reasignaciones del visitante | xfail estricto | El detector mantiene evidencia aunque se reemplace el visitante recibido |
| 3 cruces entre llamadas | Pasan tras corregir la query | Self se pasa en audit, pero el target tipado visit recibe null |
| 3 resultados reemplazados | xfail estricto | Falta el contrato fuerte de reenvío del resultado; no son FP del Visitor amplio |

Los negativos mantienen el contexto tipado y modifican una relación concreta.
Los xfail conservan la aserción deseada: XPASS exige revisar el test al corregir
la limitación. No se contabilizan como requisitos satisfechos ni como métricas
globales de precisión.

## Fallencias concretas y prioridad

La query ready usaba PASSES_SELF_TO sobre el método accept y enlazaba por separado
HAS_CALL, RECEIVER y TARGET. El frontend agrega PASSES_SELF_TO a ese método.
Por ello, las dos llamadas siguientes aportaban fragmentos incompatibles
de evidencia que terminaban combinados:

```text
visitor.audit(self)  // audit admite Object, no el contrato concreto Element
visitor.visit(null)  // visit requiere Element, pero no recibe self
```

Se corrigió únicamente visitor.toml, usando relaciones existentes:

```text
require $unit INSTANCE_RECEIVER $self;
require $dispatch ARGUMENT $self_argument;
require $self_argument VALUE $self;
```

Esto correlaciona la identidad del elemento con la ocurrencia dispatch concreta.
La vista KenQL representa el argumento como una ocurrencia intermedia: en el IR
fuente ARGUMENT apunta directamente al valor, pero en esta vista necesita VALUE.
No se modificó frontend ni se creó una relación nueva.

Se ejecutaron además las regresiones Visitor existentes de la matriz GoF y los
contratos C++: **54 passed, 6 xfailed, 434 deselected**, en 4.21 segundos. La selección
fue `test_algorithm_visitor.py test_gof_executable.py test_cpp_method_contracts.py
-k visitor`. No es una corrida de toda la suite.

La query aún requiere resolver la correspondencia entre la posición del argumento
self y el parámetro concreto tipado Element cuando una operación tiene varios
parámetros. Compartir ocurrencia de llamada mejora la precisión, pero no prueba
por sí solo ese binding ni la selección completa de overloads.

La segunda limitación es temporal: `visitor = new Visitor()` antes del dispatch
conserva el símbolo parámetro pero rompe el vínculo con el visitante elegido por
el cliente. Se necesita una definición de entrada y el flujo hasta la llamada,
permitiendo aliases seguros en vez de aceptar o rechazar por nombres.

Finalmente, los contratos named-dispatch, overloaded-dispatch, stateful-visit y
result-forwarding deberían ser operaciones consultables separadamente. La
presencia de un return no define Visitor y el retorno de una constante no lo
refuta cuando el objetivo era acumular efectos en el visitante. El lenguaje debe
permitir pedir esa precisión adicional sin endurecer de forma incorrecta todas
las variantes del catálogo.
