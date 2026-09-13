# Memento mediante getters y contratos

Estado: variante `accessor-snapshot` implementada en IR 1.28.0, además de
`snapshot-object`. [Query declarativa](../../../src/ken/structural/patterns/memento.toml).

## Recorrido que exige la query

La variante conecta el mismo estado a través de estos pasos:

1. Un método del originador devuelve una construcción de snapshot que recibe su campo.
2. Un binding de esa construcción relaciona el argumento con un parámetro de su constructor.
3. El constructor guarda directamente ese parámetro en un campo del snapshot.
4. Un getter sin argumentos devuelve ese mismo campo.
5. Un método distinto del originador recibe el snapshot, llama al getter y escribe
   su resultado directamente al campo original.

Los [bindings y transferencias](call-bindings.md) conservan identidad de llamada,
argumento, parámetro, campo y escritura. Dos llamadas que reciben el mismo valor
no permiten mezclar pruebas. Tampoco basta un método llamado `save` o `getState`:
renombrar todos los roles conserva los positivos y sustituir la conducta los elimina.

## Variaciones por lenguaje

| Lenguaje | Construcción y captura | Restauración |
|---|---|---|
| Python | `Snapshot(self.state)` → `__init__(self, value)` → `self.value = value` | `restore(self, s: Snapshot)` → `self.state = s.get()`; también contratos nominales. |
| JavaScript | `new Snapshot(this.state)` → `constructor(value)` → `this.value = value` | Sin anotación: exige además un caller observado que pase un snapshot al parámetro de restore. |
| TypeScript | Constructor explícito y campo de instancia | Tipo concreto o interface/base; `get()` se vincula con su implementación mediante `OVERRIDES`. |
| Java | Constructor explícito único | Tipo concreto o contrato nominal; no se seleccionan sobrecargas ambiguas. |
| C# | Constructor explícito único, argumentos posicionales/nombrados | Tipo concreto o interface; getters como métodos explícitos, no cualquier propiedad calculada. |

Son fragmentos ilustrativos; los [fixtures completos propios](../../../tests/structural/test_memento_accessors.py)
son parseados y consultados por los tests, sin ejecutar ni compilar los programas.
Los contratos nominales admiten un camino `SUBTYPE_OF` de hasta ocho pasos. El
getter invocado debe ser el mismo slot o uno sobrescrito por el getter del snapshot.
La variante dinámica requiere un parámetro con `type_state=unknown`, evidencia de
un caller que aporte el tipo de snapshot y coincidencia de nombre con su getter
cuando el destino de la lectura sigue sin resolver. Esa evidencia no resuelve todos
los posibles callers, monkey patches ni despachos dinámicos del programa.

## Qué se descarta y qué no se demuestra

Se descartan restauraciones a otro campo, getters constantes o de otro campo,
entradas reemplazadas, escrituras posteriores que matan el valor, parámetros
reasignados y snapshots que no participan en la ida y vuelta. Los cuerpos de
constructor/getter/restauración deben cumplir el modelo `linear-fields/1`.
Defaults omitidos no se convierten en argumentos explícitos. Variádicos, spreads,
constructores implícitos/heredados, overloads y control no soportado no se infieren.

La query identifica una estructura compatible con guardar y restaurar estado.
No garantiza encapsulación, deep copy, snapshot inmutable, historial de undo/redo,
ausencia de efectos ocultos ni seguridad entre threads. El directorio puede contener
otras implementaciones válidas de Memento que esta variante no detecta.

## Caso externo y ambigüedad pendiente

En el ejemplo TypeScript Document de `design-patterns-across-languages`, save
construye ConcreteMemento(content) y restore(IMemento) recupera getState().
IR 1.28 reconoce este recorrido y corrige el enlace de interfaces TypeScript
exportadas e importadas entre archivos. La corrección también recupera ejemplos
Strategy y Visitor; la [auditoría](../../structural-validation/multilanguage/memento-accessors.md)
separa esos resultados del cambio de la query Memento.

El falso positivo Builder sobre Document sigue pendiente: su firma acepta una
proyección configurable de estado. Detectar Memento no implica que Builder sea
imposible; un Builder puede admitir snapshots. La solución necesita fortalecer la
evidencia de construcción y uso, sin excluir arbitrariamente todos los Mementos.
