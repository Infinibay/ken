# `state#state-enum` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-14. Base: `36c70f9` (IR 1.57.0), IR 1.58.0.

## El contrato que la ficha pedía no exigir

La ficha es explícita: *no introducir objetos State ficticios*. La variante es la
misma idea que `state-object` pero con el estado como **valor**, no como objeto con
contrato. La evidencia publicada es:

| Necesidad | Hecho |
|---|---|
| Un campo del contexto guarda el estado | `HAS_FIELD` sobre el `STORAGE` |
| El valor gobierna una rama | `GUARDS_WRITE` — la guarda menciona **ese** campo |
| Una transición lo cambia | ≥2 constantes distintas escritas por el mismo callable |

`GUARDS_WRITE` ya existía y no necesitó cambios. El trabajo real estuvo en la
tercera fila.

## El falso positivo, medido antes de tocar nada

Con la query escrita y corrida sin tocar el IR, los **ocho** lenguajes matcheaban.
Pero al inspeccionar los valores escritos apareció la grieta:

```
cpp   values=['module/CLASS:Machine/VALUE:71', '.../CALLABLE:step/VALUE:154', '.../VALUE:224']
rust  values=['.../CALLABLE:step/VALUE:176', '.../VALUE:254']
```

Son `VALUE` anónimos **por offset de byte**. Es decir: `count distinct` contaba
posiciones de sintaxis, no estados. Medido con una máquina que escribe el *mismo*
estado en ambas ramas:

| Lenguaje | Antes | Después |
|---|---|---|
| python | 0 | 0 |
| javascript | 0 | 0 |
| typescript | 0 | 0 |
| java | 0 | 0 |
| csharp | 0 | 0 |
| **cpp** | **1** (falso positivo) | 0 |
| **rust** | **1** (falso positivo) | 0 |
| go | 0 | 0 |

La causa raíz era mayor que la distinctness: **`enum class State { Idle, Running }`
no producía ninguna entidad** en C++ ni en Rust. La declaración de enum no se
modelaba en absoluto, así que `State::Idle` no tenía a qué resolverse.

Java, C#, TypeScript y JavaScript ya acertaban por nombre, pero por una razón
accidental: en Java, `State.IDLE` se bajaba como `MEMBER` bajo un
`Machine/STORAGE:State` **inventado** — un campo ficticio del contexto, que
preservaba la distinctness por nombre mientras modelaba mal el enum. Ese campo
inventado también desaparece con el cambio. Go (bloque `const` de módulo) y Python
(`class_definition`) ya tenían identidad por nombre.

## La capacidad construida

Las declaraciones de enum se bajan como tipo nominal por la misma vía que una
clase, en las cinco gramáticas que las declaran (`enum_specifier` de C++,
`enum_item` de Rust, `enum_declaration` de Java/C#/TS). Un `enum_specifier` de C++
**sin cuerpo** es una referencia elaborada (`enum State` dentro de una
declaración), no una definición, y no declara nada.

Lo que carga el peso es la **identidad de referencia**: una constante nombrada
tiene **una** identidad por declaración, no una por ocurrencia.

```
State::Idle  ->  …/CLASS:State/MEMBER:Idle      (C++ y Rust)
State.IDLE   ->  …/CLASS:State/MEMBER:IDLE      (Java, C#, TS, Python)
Idle         ->  …/module/STORAGE:Idle          (Go, bloque const)
```

Cuatro referencias colapsan en dos entidades. La resolución cualificada solo se
aplica cuando el cualificador resuelve a un tipo declarado **y** la declaración de
ese tipo lista el nombre, así que `Config::new` y las rutas de módulo conservan su
tratamiento anterior.

La asimetría era en sí misma el defecto: la misma obligación estructural
("se escriben dos valores distintos") se verificaba con fuerza distinta según el
lenguaje. Eso no es una limitación documentable, es una inconsistencia.

## Negativos cubiertos

30 pruebas en `tests/structural/test_state_state_enum.py`:

| Negativo | Por qué se rechaza |
|---|---|
| escribe el mismo estado en dos ramas (8 lenguajes) | `count distinct` cuenta constantes, no ocurrencias |
| dos estados distintos sin ninguna guarda | falta `GUARDS_WRITE` |
| la guarda menciona el campo pero se escribe **otro** campo | `GUARDS_WRITE` es sobre el campo escrito |
| una sola transición guardada | `count distinct >= 2` |

## Límites declarados

`query_claim` no prueba que el conjunto de estados sea exhaustivo, que la máquina
sea total, ni que la transición sea alcanzable en ejecución. `GUARDS_WRITE` es una
relación estructural entre la guarda y el campo, no una prueba de que cada rama
corresponda a un estado concreto.

## Validación

`tests/structural/` completo, sin regresiones, más las 30 pruebas nuevas.
`mypy src/ken` limpio.
