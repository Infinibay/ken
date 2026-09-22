# Eager Singleton: constructores aprobados; construcciones pendientes

## Aprobado e implementado

El usuario aprobó esta sintaxis, ahora ejecutable:

```kql2
require exists constructor of $type;
require every constructor of $type { visibility: private; }
```

Son cuantificadores generales de declaraciones. No preguntan si un tipo es un
Singleton. La primera condición exige un constructor de instancia explícito; la
segunda exige que todos los constructores de instancia explícitos sean privados.
Se mantienen separadas: sobre un inventario cerrado vacío, `every` es verdadero
y `exists` es falso. Los inicializadores estáticos no pertenecen al dominio.

El primer dominio soportado es `constructor`. El bloque de `every` admite la
propiedad existente `visibility` con un valor literal; no se implementaron por
anticipado nuevos bloques de métodos/campos, restricciones BODY ni conteos de
construcciones. El propietario debe ser un `TypeDecl` previamente seleccionado.
Las formas no soportadas fallan al compilar, antes de consultar el proyecto.

Cada cuantificador baja a un operador relacional general con dominio,
propietario, cuantificador y restricciones. La enumeración se memoiza por tipo
durante la ejecución. Un constructor presente basta para `exists`; uno cuya
visibilidad acreditada contradice la restricción basta para refutar `every`.
Sin testigo decisivo se requiere un inventario cerrado: C# `partial`, tipos
importados sin declaraciones, inventarios ausentes/inconsistentes y visibilidad
no interpretada mantienen `unknown`, nunca una aprobación por ausencia.

`singleton#eager-shared` ya utiliza esas dos cláusulas. La expresión inicial del
campo, el accessor y su BODY permanecen en `singleton.shared_instance`.
La condición de construcciones aún conserva su forma interna; no se borró para
aparentar una migración completa.

## Pendiente de aprobación: contar construcciones resueltas

Falta expresar en sintaxis fuente que hay exactamente un sitio de construcción
resuelto al tipo en el snapshot. No se requiere que ese sitio se ejecute una sola
vez, ni se afirma unicidad global frente a reflexión o código no analizado.

Una propuesta concreta pendiente es seleccionar el tipo construido como una
propiedad de la ocurrencia y reutilizar una cuantificación explícita:

```kql2
count distinct $allocation == 1 {
  call $allocation { constructs: $type; }
};
```

La sintaxis `count distinct` y la propiedad `constructs` de este ejemplo **no
están aprobadas ni implementadas**. El backend ya tiene un `tally` interno; el
objetivo sería exponer un conteo de participantes fuente, con comprobación de
cierre, sin un helper de Singleton. Una alternativa es completar `count(Call
$c | $c.constructed_type == $type | $c)` del lenguaje de expresiones. Esa
alternativa tampoco está aprobada para esta migración.

La política de llamadas con múltiples tipos posibles debe definirse antes:
contar evidencia posible no equivale a acreditar un único tipo construido.
Los límites del conteo deben describirse como sitios resueltos del snapshot,
no como prueba de que no existan construcciones fuera del proyecto.

## Validación y contraejemplos

Los tests nuevos verifican Java/C#/TypeScript, visibilidad privada/pública y
protegida, varios overloads, constructor ausente, comentarios, inicializadores
estáticos, C# `partial`, visibilidad desconocida, inventario eliminado,
miembros ausentes, tipos importados y visibilidades compuestas C#.
También prueban verdad vacía, propietarios por identidad, aliases de queries,
backend de referencia/optimizado, persistencia y caché pública.

La base existente `test_construction_access.py` y `test_eager_singleton.py`
sigue verificando factories, resets, campos adicionales, construcciones de otro
tipo, nombres engañosos y ruido intermedio. Los tests del cuantificador además
funcionan sobre clases sin almacenamiento estático ni accessor: no dependen de
la estructura del patrón Singleton.
