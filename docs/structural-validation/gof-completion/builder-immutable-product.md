# `builder#immutable-product` — cerrada (IR 1.52)

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-13. Base: `56da827`.

## Qué pide la ficha

> Cada paso recibe un estado de construcción, crea un sucesor que conserva los
> campos pertinentes y modifica uno de ellos. Seguir el sucesor hasta finish y
> demostrar que el producto usa ese estado. Positivo: copia de builder con un
> campo cambiado; incluir encadenamiento y variables intermedias.

Los contraejemplos de la ficha son concretos: sucesor descartado, finish sobre el
original, pérdida del estado acumulado, y **fluent self del mismo tipo tratado
como typestate**.

## La única capacidad que faltaba: resolución del constructor de C++

En cinco lenguajes (python, javascript, typescript, java, csharp) la query
funcionó sin tocar el IR. Go y Rust necesitaron **usar la forma correcta** del
grafo, no una capacidad nueva: los literales con clave no producen `ARGUMENT`
sino `HAS_INITIALIZER` + `STORES_VALUE`.

C++ sí fallaba, y la causa era real:

```cpp
struct Builder {
  int name; int size;
  Builder(int name, int size) : name(name), size(size) {}
  Builder with_name(int name) const { return Builder(name, this->size); }
};
```

`with_name` no producía `RETURNS_NEW`, así que el sucesor era invisible. La
cadena era:

1. En C++, el constructor es un `CALLABLE` **con el mismo nombre que su clase**.
2. `semantic.resolve` tiene una guarda: una llamada cuyo nombre coincide con un
   binding local (`STORAGE`, `PARAMETER` o `CALLABLE`) **no** es una construcción
   — evita que una función local que sombrea un nombre de tipo se lea como
   construcción.
3. Esa guarda descartaba el constructor de C++, que es exactamente un `CALLABLE`
   con el nombre de su clase.

Corrección: la guarda no se aplica cuando el binding coincidente es un `CALLABLE`
marcado `constructor`. Ningún otro lenguaje nombra un constructor igual que su
clase, así que el cambio queda acotado a C++.

Con eso, `Builder(...)` vuelve a resolver a `CLASS:Builder` y se emiten
`ALLOCATES_TYPE` y `RETURNS_NEW`.

## Contrato publicado

```kenql
query immutable_builder {
 type_decl() as $builder;
 require $builder HAS_FIELD $state;
 require $builder HAS_METHOD $step;
 callable(constructor: false) as $step;
 require $step HAS_PARAMETER $input;
 parameter(receiver: false) as $input;
 require $step RETURNS_NEW $builder;          # el sucesor es de la MISMA clase
 require $step HAS_CALL $copy;
 any { ... $changed ... } or { ... }          # el valor nuevo llega al constructor
 any { ... $state ... } or { ... }            # y un campo del original también
 different $input $state;
 require $builder HAS_METHOD $finish;
 callable(constructor: false) as $finish;
 require $finish RETURNS_NEW $product;
 different $product $builder;
 require $finish HAS_CALL $final;
 any { ... $state ... } or { ... }            # finish vuelve a consumir el campo
 emit $builder, $finish, $product;
}
```

El `any { } or { }` acepta las dos formas de construcción porque el grafo las
representa distinto y ambas significan lo mismo:

| Forma | Lenguajes | Hechos |
|---|---|---|
| Posicional | python, javascript, typescript, java, csharp, cpp | `ARGUMENT` → `VALUE` → `LOADED_FROM` |
| Con clave / llaves | go, rust | `HAS_INITIALIZER` → `STORES_VALUE` |

**Lo que no prueba** (declarado en `query_claim`): copia profunda, alias residual
del estado compartido, y el orden real de una cadena de pasos.

## Positivo y negativos, en los ocho lenguajes

Positivo: exactamente **1 match** por lenguaje, con `$builder = CLASS:Builder`,
`$product = CLASS:Product` y `$finish` un método del builder.

| Negativo | Por qué no hay match |
|---|---|
| Paso que muta y devuelve el receptor (`return self` / `this` / `&mut self`) | no hay `RETURNS_NEW $builder` |
| Sucesor que **descarta** el otro campo (`Builder(name, 0)`) | el constructor no recibe `$state` |
| Sucesor construido y descartado | ya cubierto por el primero: sin `RETURNS_NEW` no hay match |

El negativo de mutación es el que la ficha pide explícitamente: **fluent self del
mismo tipo no es un sucesor inmutable.**

## Archivos

- `src/ken/structural/semantic.py`: guarda de `resolve` para constructores.
- `src/ken/structural/model.py`: `IR_VERSION` 1.51.0 → 1.52.0.
- `src/ken/structural/patterns/builder.toml`: variante `ready` con query; raíz con
  unión.
- `tests/structural/test_builder_immutable_product.py`: 27 tests.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_builder_immutable_product.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz nueva + catálogo: **292 passed**.
- Suite estructural completa: **6.700 passed, 143 xfailed**, sin fallos
  (baseline previo: 6.671 / 146). Los 3 xfail que menos son exactamente los de
  esta variante, convertidos en regresión normal.
- `mypy src/ken`: 108 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/semantic.py` | `0c28f33c9700d6927d549e92de8ee42d205916388d6a64085151f5f0699f0628` |
| `src/ken/structural/return_flow.py` | `bcca3f9b170d4bbc6aac7db7d228493a00c45dd28103f2884e0fe013ae0a8d18` |
| `src/ken/structural/model.py` | `a92a287f8cd3c62ec7d8b9afcd0845d9d3c2a9bc90f4fc9367ac425597ea2fa8` |
| `src/ken/structural/patterns/builder.toml` | `48680051fe3ea14306f69d523642401dc991303b9bf1ac5141f12d0388717c40` |
| `tests/structural/test_builder_immutable_product.py` | `03db9ffc781fe1412945236bc625924a92a272814c3e6ce57ed848632d48f82c` |

## Inventario

**49 ready / 28 design** (antes 48 / 29).
