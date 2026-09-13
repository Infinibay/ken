# Bindings de llamadas y transferencias de campos — IR 1.28.0

Estado: subconjunto implementado en Python, JavaScript, TypeScript, Java y C#.
Estas relaciones son públicas y genéricas; Memento es una consulta que las utiliza,
no un caso especial dentro del IR. Ver la [guía operativa](../../structural-ir.md).

## Por qué hace falta una ocurrencia de binding

`BINDS_TO` relaciona un valor con un parámetro, pero no identifica la llamada que
aportó esa evidencia. Con `Pair(x, y)` y `Pair(y, x)`, unir esos hechos sin conservar
la llamada permite atribuir el argumento correcto al constructor equivocado.
IR 1.28 introduce un nodo de binding por llamada y posición de argumento explícito.
Repetir el mismo valor en dos argumentos o dos llamadas conserva nodos diferentes.

| Relación | Origen → destino | Contrato actual |
|---|---|---|
| `CONSTRUCTOR_TARGET` | construcción → constructor | Única declaración explícita en el tipo resuelto; `basis=unique-declaration`. No reemplaza `TARGET`. |
| `MAY_CONSTRUCTOR_TARGET` | construcción → candidato | Alternativas cuando existen varios constructores; `modality=may`. No se elige una sobrecarga por cantidad o tipos de argumentos. |
| `CONSTRUCTOR_STATUS` | construcción → estado | `resolved` o `unsupported`, con causa. Resolver la declaración no prueba que los argumentos sean admisibles. |
| `BINDING_STATUS` | llamada → estado | `supported` o `unsupported`, `analysis=explicit-arguments/1`, con causa. Una llamada sin destino resuelto puede carecer de estado. |
| `CALL_BINDING` | llamada → binding | Atributos `position`, `kind`, `name`, `mode=direct`; posición del argumento en el código, no del parámetro formal. |
| `BINDING_PARAMETER` | binding → parámetro | Formal asociado a esa ocurrencia. Excluye el receptor implícito. |
| `BINDING_VALUE` | binding → operando fuente | Identidad original: puede ser storage, parámetro, llamada o literal. No es automáticamente un valor SSA ni una lectura normalizada de KenQL. |
| `BINDING_TARGET` | binding → callable | Identidad del destino usada para resolver ese binding. |

La identidad serializada del binding contiene la identidad de llamada y su posición
(`…/binding/0`). Es una identidad del snapshot; editar el archivo puede cambiarla.
La evidencia conserva la localización del argumento. Los bindings son nodos de
relaciones; no son declaraciones `PARAMETER` ni `CALLABLE`.

```kenql
query explicit_constructor_input {
  require $creation CONSTRUCTOR_TARGET $constructor;
  require $creation CALL_BINDING $binding [mode: direct];
  require $binding BINDING_TARGET $constructor;
  require $binding BINDING_PARAMETER $parameter;
  require $binding BINDING_VALUE $operand;
  require $constructor HAS_PARAMETER $parameter [position: 0];
  emit $creation, $constructor, $parameter, $operand;
}
```

Este ejemplo distingue la posición formal de la posición real. En Python,
`Pair(second=y, first=x)` sitúa `x` en posición real 1 y formal 0.
`Pair(first=x)` con un segundo parámetro por defecto produce únicamente el binding
de `x`: el analizador no evalúa defaults ni inventa una ocurrencia de argumento.
C# conserva también defaults que Tree-sitter representa sin un campo nombrado.

## Resolución y límites de argumentos

Se admiten argumentos posicionales y los nombrados de Python/C#, con comprobación
de nombres, duplicados, parámetros requeridos, positional-only y keyword-only.
Los nombrados deben seguir a los posicionales en este subconjunto conservador.
Algunas formas legales de C# que mezclan posiciones quedan fuera; `unsupported`
no significa que el programa sea inválido. Tampoco se modela toda la permisividad
de JavaScript respecto de argumentos faltantes o adicionales.

Se rechazan spreads y firmas variádicas completas, incluso si una parte de sus
argumentos parece resoluble: `*args`, `**kwargs`, rest y parámetros `ref/out/params`
necesitan modelos de elementos, claves o referencias. Su sintaxis sigue preservada
en el IR. No se añaden bindings parciales que una consulta pudiera tratar como una
prueba completa. Los constructores implícitos/heredados y los `__new__` explícitos
de Python quedan fuera de la resolución inicial. C++, Go y Rust necesitan modelos
propios; una función que devuelve un struct no se convierte en constructor nominal.

Los destinos ordinarios `TARGET` ya resueltos también pueden producir bindings.
Esto no añade despacho dinámico general ni propagación de valores entre todas las
llamadas. `BINDS_TO` se conserva por compatibilidad. Con diagnósticos de parseo en
el grafo, este pase no deriva hechos nuevos; la ausencia de hechos no prueba ausencia
de uso ni de argumentos.

## Transferencias lineales de campos

Un segundo pase ofrece evidencia restringida de escrituras y getters de instancia:

| Relación | Origen → destino | Evidencia |
|---|---|---|
| `FIELD_FLOW_STATUS` | método → estado | `supported`/`unsupported`, `analysis=linear-fields/1` y causa. Se examinan métodos candidatos con escrituras/retornos y, desde IR 1.29, constructores con parámetros-propiedad. |
| `FINAL_FIELD_VALUE` | escritura → operando | Última asignación directa observada a ese campo antes del primer retorno o del fin del cuerpo. |
| `FINAL_FIELD_INPUT` | escritura → parámetro | La misma escritura toma directamente un parámetro que no se reasigna explícitamente. |
| `RETURNS_FIELD` | método → campo | El retorno directo lee un campo propio que no tiene asignaciones explícitas en el cuerpo. |
| `CALL_RECEIVER_INPUT` | llamada → parámetro | Receptor directo correspondiente a un parámetro sin reasignación explícita. |

Las cuatro relaciones derivadas llevan `basis=linear-syntax`. Se mantienen las
identidades de escritura, callable y campo; `RETURNS_FIELD` conserva además
`return_operation`. No son equivalentes a un análisis interprocedural del heap.

```python
class Snapshot:
    def __init__(self, value):
        self.value = value       # FINAL_FIELD_INPUT hacia el parámetro value
    def get(self):
        return self.value        # RETURNS_FIELD hacia el campo value
```

Reemplazar la escritura con `self.value = 0` elimina el testigo de entrada original.
Reasignar el parámetro también lo elimina. Una restauración `self.value = s.get()`
puede vincular `FINAL_FIELD_VALUE` con la llamada y `CALL_RECEIVER_INPUT` con `s`.
El pase no sigue un resultado por un local intermedio: es un subconjunto directo.

Se requieren cuerpos lineales: se rechazan ramas, bucles, try/throw, yield/await,
scopes de recursos, funciones anidadas, escrituras indirectas no representadas y
actualizaciones compuestas. El escape explícito del receptor, incluidas aliases y
publicaciones en contenedores, invalida el modelo. También se rechazan operaciones
dinámicas conocidas como eval/exec. Sólo participan campos de instancia propios.

`linear-syntax` **no prueba pureza**, inmutabilidad de objetos almacenados, ausencia
de efectos ocultos de llamadas/getters/setters, ni estabilidad frente a threads.
Una escritura a elementos de un contenedor no es una reasignación de su binding.
Las relaciones describen el recorrido sintáctico directo dentro de estas restricciones;
no deben usarse como certificado de deep copy, ausencia de races o snapshot inmutable.

## Validación y evolución

[Tests de bindings](../../../tests/structural/test_call_bindings.py) comprueban
correlación por ocurrencia, posiciones, defaults, imports, ambigüedad y serialización.
[Tests de Memento](../../../tests/structural/test_memento_accessors.py) ejercitan las
transferencias con positivos y negativos cercanos en cinco lenguajes.
La [auditoría externa](../../structural-validation/multilanguage/memento-accessors.md)
registra resultados y fuentes exactas.

Próximas extensiones deben conservar estos contratos: bindings expandidos necesitan
procedencia por elemento/clave; sobrecargas necesitan resolución explícita;
transferencias con ramas necesitan estados correlacionados. Añadir una arista más
amplia sin declarar su modalidad o su alcance volvería a introducir pruebas mezcladas.


IR 1.29 agrega `CONSTRUCTOR_FIELD_INPUT` (campo → parámetro) y considera
inicializaciones implícitas de parámetros-propiedad TypeScript antes del cuerpo.
También expone `INSTANCE_RECEIVER` y `DECLARED_TARGET` sin convertir una anotación
en certeza sobre el destino runtime. Ver el [contrato de esta extensión](state-context-transitions.md).
