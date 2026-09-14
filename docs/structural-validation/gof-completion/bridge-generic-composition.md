# `bridge#generic-composition` (6 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **seis** lenguajes declarados.
Fecha: 2026-09-14. Base: `042cf56` (IR 1.63.0), IR 1.64.0.

## Qué la separa de `strategy#static-policy`

Las dos leen **la misma forma**: un tipo liga un parámetro de tipo, un campo suyo está
tipado por él, y un método delega en el campo por receptor. La diferencia es una sola y
es el corazón de Bridge: el parámetro tiene que estar **compartido por al menos dos
tipos**. Un contexto con una política es una estrategia; el mismo parámetro fluyendo por
una abstracción y sus refinamientos es un puente.

Se comprueba en las dos direcciones, y en una sola clase genérica los dos veredictos son
opuestos: `strategy#static-policy` matchea y `generic-composition` no.

La ficha además prohíbe exigir dispatch virtual (*no exigir virtual dispatch*), así que
la query **no** pide subtipo, ni interfaz, ni implementaciones múltiples. Esa es la
diferencia con `runtime-composition`, la vecina.

## Un detalle del conteo que costó dos negativos

El conteo de «≥2 tipos que ligan el parámetro» incluía, en la primera versión, a **toda
entidad** que lo liga. Pero el constructor y los métodos de una clase genérica también
ligan el parámetro:

```
CLASS:Abstraction                   BINDS_TYPE_PARAMETER I
CALLABLE:Abstraction@49             BINDS_TYPE_PARAMETER I     <- constructor
CALLABLE:operation@95               BINDS_TYPE_PARAMETER I     <- método
```

Con eso, **una sola clase** satisfacía el `>= 2`, y dos negativos que había escrito
—una única clase genérica y un refinamiento con otro nombre de parámetro— matcheaban.
La corrección es acotar el conteo a tipos con `type_decl()`, que selecciona
CLASS|INTERFACE. El `query_claim` lo dice explícitamente, porque es una trampa fácil de
reintroducir.

## La capacidad: cuatro gramáticas no ligaban nada

Hasta IR 1.62 solo Rust (y luego C++) ligaban parámetros de tipo, aunque los seis
lenguajes los escriben. Ahora los seis, y cada gramática los escribe distinto:

| Lenguaje | Grupo | Miembros |
|---|---|---|
| Rust, TypeScript, Java | campo `type_parameters` | `type_parameter` |
| Go | campo `type_parameters` | `type_parameter_declaration` |
| C++ | campo `parameters` del `template_declaration` | `type_parameter_declaration` |
| C# | hijo `type_parameter_list` **sin campo** | `type_parameter` |

C# es el raro: deja el grupo como hijo sin nombre de campo, así que hay que buscarlo por
tipo de nodo entre los hijos propios de la declaración. Y Java no da campo `name` en su
`type_parameter`, así que el nombre cae al hijo identificador.

**Go necesitó además un arreglo distinto y por la misma razón.** Un receptor genérico
escribe sus argumentos de tipo —`func (a *Abstraction[I]) Operation()`— mientras la
declaración se llama sin ellos, así que el método no resolvía a ningún tipo y quedaba
**propiedad del módulo** en vez de `Abstraction`. Se quitan los argumentos de tipo del
receptor antes de la búsqueda. Sin eso, `$abstraction HAS_METHOD $operation` era falso
en Go y la variante no podía cerrarse allí.

## Negativos cubiertos

25 pruebas en `tests/structural/test_bridge_generic_composition.py`: 6 positivos, 6 de
renombrado, 3 negativos, 2 de separación con `strategy#static-policy`, 2 de la capacidad
en los seis lenguajes y las comprobaciones del contrato publicado y del receptor de Go.

| Negativo | Por qué se rechaza |
|---|---|
| una sola clase genérica | el parámetro no está compartido: es `strategy#static-policy` |
| el refinamiento liga **otro** nombre de parámetro | ídem |
| el campo tiene un tipo concreto | no hay parámetro que ligar |
| el método no delega en el campo | falta la llamada con ese receptor |

## Límites declarados

`query_claim` no prueba sustitución de tipos ni que la instanciación del sitio de uso sea
la elegida. Prueba que la implementación se elige **en compilación** y que el parámetro
no está atado a una sola abstracción. El renombrado se verifica con fixtures construidos
por lenguaje y no por sustitución de cadenas: una cadena de `replace` sobre seis
lenguajes y dos sintaxis produce fuente inválida —lo hice y falló en cinco— antes de
producir un fixture renombrado.

## Validación

`tests/structural/` completo, sin regresiones, más las 25 pruebas nuevas.
`mypy src/ken` limpio.
