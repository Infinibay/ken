# Entradas de configuración de Builder

Implementado en **IR 1.32.0**, después de revisar el diseño y los contraejemplos.
La [auditoría](../../structural-validation/multilanguage/builder-input-writes.md)
fija resultados, fuentes y límites de la medición.

## Problema y contrato

La variante mutable-product combinaba WRITES y ASSIGNED_FROM de todo el cuerpo.
`state=value; state=0` conservaba una asignación histórica al parámetro y producía
un Builder aunque esa entrada no configurara el estado final del paso. Una
reasignación del parámetro cambiaba el significado de la lectura sin cambiar
su identidad de declaración.

La query ahora reutiliza FINAL_MEMBER_INPUT con identidad de operación. El pase
incluye campos directos de instancia además de miembros anidados. El paso del
builder debe contener esa escritura; su destino debe ser el mismo estado usado
como argumento de construcción del producto. No basta que exista una asignación
a ese campo en otro método o antes de una sobrescritura.

```kenql
query configured_storage {
  require $builder HAS_FIELD $state;
  require $builder HAS_METHOD $step;
  callable(constructor: false) as $step;
  require $step HAS_OPERATION $write;
  require $write FINAL_MEMBER_INPUT $input [basis: linear-syntax];
  require $write ASSIGNMENT_TARGET $state;
  emit $builder, $step, $state, $input, $write;
}
```

La variante completa `builder#mutable-product`, en su TOML, añade la construcción,
su argumento leído de ese estado y la finalización que devuelve el producto.
La operación de asignación es evidencia pública, no una condición oculta en Python
reservada para Builder. El contrato de análisis sigue siendo `linear-members/1`;
el cambio de versión del IR invalida las cachés anteriores.

## Ejemplos y negativos

Ejemplo propio Python:

```python
class Product:
    def __init__(self, value):
        self.value = value

class Assembly:
    def configure(self, value):
        self.state = value

    def finish(self):
        return Product(self.state)
```

El paso puede devolver self/this o no devolver nada. La configuración puede
renombrarse: no se buscan nombres como configure, Builder o Product.

| Cuerpo del paso, en pseudocódigo | Evidencia final |
|---|---|
| `state=value` | Entrada directa conservada. |
| `state=0; state=value` | Entrada de la última escritura conservada. |
| `state=value; state=0` | No conserva la entrada. |
| `value=0; state=value` | Parámetro reasignado; no acredita entrada original. |
| `state=value; value=0` | También se excluye: el pase exige ausencia de reasignación en todo el cuerpo. |
| `return; state=value` | No acredita escritura posterior a la salida. |
| `state=value; return; state=0` | La escritura muerta no sustituye la anterior. |
| `state+=value` | No es una transferencia directa. |
| `if flag: state=value` | El pase lineal no soporta esa rama. |

Son garantías sintácticas acotadas. Retener una referencia recibida no demuestra
que el objeto referido sea inmutable, y una llamada posterior puede tener efectos
que este pase no conoce.

## Diferencias por lenguaje

El pase de miembros cubre ocho gramáticas: Python, JavaScript, TypeScript, Java,
C#, C++, Go y Rust. Los campos directos pueden representarse como storage nominal
sin arista MEMBER_OF, incluido un acceso con receptor implícito en Java/C#/C++.
Los campos estáticos no se incorporan a este conjunto de campos de instancia.

Go interpone statement_list entre el bloque y sus sentencias. Ese nodo es un
contenedor de orden, no una región de control adicional. Las asignaciones múltiples
siguen sin descomponerse como escrituras escalares precisas: si coexisten con una
escritura candidata, producen MEMBER_FLOW_STATUS=unsupported/unmodeled-write.
Esto impide ocultar un rebinding dentro de `value, other = 0, 0`. Las asignaciones
a destinos que no son miembros conocidos, STORAGE o PARAMETER también se rechazan.
Un miembro anidado puede tener identidad VALUE y sigue admitido por MEMBER_OF.

C++ envuelve el declarador de función cuando devuelve punteros o referencias.
El frontend recorre esa cadena para conservar nombre y parámetros de la callable,
sin confundir la lista de parámetros de un callback recibido con la lista exterior.
Hay pruebas con valores, punteros, dobles punteros, const, referencias y rvalue
references, tanto en funciones libres como en métodos. Esto no reconstruye por
completo el tipo de retorno C++ ni resuelve sobrecargas o tipos dependientes.

La finalización por argumentos de construcción y la finalización mediante campos
de literales Rust/Go siguen siendo formas distintas. Las pruebas del pase de
escrituras en ocho lenguajes no certifican automáticamente la variante completa
mutable-product en Rust/Go; la matriz de esa query cubre seis lenguajes.

## Estados y límites

Cuerpos no soportados no aportan evidencia precisa; la query no vuelve a la
asignación histórica. Las ramas, bucles, suspensión, funciones anidadas, operaciones
de ámbito dinámico conocidas, escrituras compuestas y eventos no modelados
conservan las restricciones del pase. Ausencia de MEMBER_FLOW_STATUS puede indicar
que no hubo una escritura candidata o que hubo diagnósticos: no significa supported.

Se conservan los límites de aliasing, efectos ocultos y flujo entre invocaciones.
Los estados de otras variantes y otros pases no se reinterpretan: FIELD_FLOW_STATUS
y RETURN_FLOW_STATUS tienen sus propios alcances.

Document.save del ejemplo Memento sigue compartiendo la firma con Builder.
setContent escribe directamente el parámetro y save construye ConcreteMemento con
ese campo. Excluir todos los Mementos no sería una solución fundamentada: un
objeto puede cumplir varias firmas. La corrección temporal reduce evidencia
incorrecta; no certifica intención ni pretende eliminar ese falso positivo.
