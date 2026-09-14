# `singleton#module-shared` (6 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **seis** lenguajes declarados.
Fecha: 2026-09-14. Base: IR 1.56.0 (`proxy#lazy-subject`), IR 1.57.0.

## Dos formas, y cuál de las dos es dueña del slot

| Forma | Lenguajes | Dueño del slot |
|---|---|---|
| binding de módulo | python, javascript, typescript, go, rust | el módulo |
| static local de función | cpp | el accessor |

El contrato publicado es el esqueleto común —un callable devuelve un slot escrito
una vez desde una construcción del tipo que ese slot contiene— más una disyunción:
o el slot lo declara el módulo y el accessor está exportado, o el slot lleva la
clase de almacenamiento `static`.

## El defecto real que había debajo (Go y Rust)

Go y Rust no podían expresar la forma de módulo, y la causa no era una capacidad
faltante exótica sino un **defecto de atribución**: una declaración de ámbito de
fichero no se bajaba en absoluto.

```go
var instance = Config{value: 1}

func GetConfig() Config { return instance }
```

`return instance` no podía resolver el nombre —no existía binding—, así que
`value()` **inventaba un `STORAGE`** con la misma grafía bajo el callable. El
resultado medido, antes del cambio:

```
module/CALLABLE:GetConfig  --DECLARES-->  module/CALLABLE:GetConfig/STORAGE:instance
```

El módulo no declaraba nada, y la inicialización y la lectura apuntaban a dos
entidades distintas que compartían un nombre. Rust tenía exactamente el mismo
comportamiento con `static INSTANCE: Config = ...`.

El arreglo es general y no específico de GoF: una declaración de fichero
(`var_declaration`, `const_declaration`, `static_item`, `const_item`) liga ahora un
slot del módulo **mientras se declara**, no en la primera lectura que no lo
resuelve. Así la identidad del slot no depende de si el fichero lee o declara el
nombre primero.

Una consecuencia útil: la query se protege sola. `$module DECLARES $storage` no
podía satisfacerse con el slot inventado, así que el defecto se habría visto como
un falso negativo — el peor modo de fallo posible.

## `static` en C++ es lo que separa las dos formas

La forma de C++ es el static local de función:

```cpp
Config& get_config() { static Config instance = Config(); return instance; }
```

Sin la clase de almacenamiento, la misma sintaxis es un objeto nuevo por llamada:

```cpp
Config& get_config() { Config instance = Config(); return instance; }
```

Una vez que el slot existe, las dos son indistinguibles aguas abajo, así que el
hecho hay que registrarlo en la declaración: una `declaration` de C++ con
`storage_class_specifier` `static` marca su slot `static: True`. La variante exige
esa marca en su rama de static local, y `test_the_storage_class_is_what_admits_the_function_local_shape`
verifica que el local simple se rechaza.

El motivo por el que C++ entra por esta rama y no por la de módulo es que C++ no
tiene un `EXPORT` de módulo en el IR: un `static` local es la forma canónica de
singleton compartido sin garantía de orden de inicialización entre unidades.

## Lo que se dejó sin resolver a propósito

Una declaración agrupada de Go (`var ( a = 1; b = 2 )`) y una multi-target
(`var a, b = 1, 2`) quedan **sin resolver**. Un nodo de declaración no puede llevar
dos ocurrencias de asignación independientes sin inventar qué operando llegó a qué
nombre. Se rechazan en vez de adivinar.

## Negativos cubiertos

32 pruebas en `tests/structural/test_singleton_module_shared.py`:

| Negativo | Por qué se rechaza |
|---|---|
| accessor no público (python/js/ts/go/rust) | la rama de módulo exige `EXPORT` del accessor |
| el accessor devuelve una construcción nueva | `RETURNS_STORAGE` liga el slot, no una construcción |
| el slot no se inicializa con una construcción | exige `ASSIGNMENT_VALUE` → `ALLOCATES_TYPE` |
| local simple de C++ (sin `static`) | falta la marca de almacenamiento |
| static de C++ que devuelve una construcción nueva | `RETURNS_STORAGE` liga el slot |

Rust no tiene un negativo de "sin inicializar": un `static` de Rust siempre lleva
inicializador, así que esa forma no existe en el lenguaje y no se construye.

## Límites declarados

`query_claim` no prueba thread safety, ni que el loader se alcance una vez por
proceso, ni que ningún otro escritor fuera del grafo analizado repita la
construcción. El scope (módulo, proceso, instanciación) queda explícito en la forma
elegida, no inferido del entorno de ejecución.

## Validación

`tests/structural/` completo, sin regresiones, más las 32 pruebas nuevas. `mypy
src/ken` limpio.
