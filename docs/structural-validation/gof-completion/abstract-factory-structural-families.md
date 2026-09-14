# `abstract-factory#structural-families` (3 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **tres** lenguajes declarados
(`javascript`, `typescript`, `go`).
Fecha: 2026-09-14. Base: IR 1.68.0 (`composite#higher-order-traversal`), IR 1.69.0.

## Qué se publica

Dos tipos nominales **sin base común** que declaran el mismo conjunto de slots de
creación, cada slot devolviendo una construcción distinta, y el producto del mismo slot
distinto entre las dos familias:

```
%first_slot  --MATCHES_SIGNATURE--> signature:<nombre>/<aridad>
%second_slot --MATCHES_SIGNATURE--> signature:<nombre>/<aridad>     (misma entidad)
%first_slot  --RETURNS_NEW--> %product_a
%second_slot --RETURNS_NEW--> %product_b        different %product_a %product_b
%first_other --RETURNS_NEW--> %product_c
%second_other --RETURNS_NEW--> %product_d       different %product_c %product_d
                                                different %product_a %product_c
                                                different %product_b %product_d
```

Las dos últimas son la correlación de familia: los productos del mismo slot difieren
entre familias y los dos productos de una familia difieren entre sí. Es el mismo
contrato que `associated-products` (Rust) ya publicaba, y por eso comparten el rol
`unit`.

## La capacidad, y por qué el join tenía que ser por identidad

`abstract-factory#structural-families` era el **único caso medido** en el que la query
directa no servía: relacionar dos proveedores por su conjunto de operaciones obliga a unir
por el *nombre* del método, y eso empareja cada método de un tipo con cada método del
otro. En un corpus de 30 tipos la medición dio `budget:max_states`. La ficha lo decía con
precisión: "necesita una capacidad de IR que agrupe operaciones por firma compartida para
que el join sea por identidad".

IR 1.69 la agrega:

```
<callable> --MATCHES_SIGNATURE--> signature:<nombre>/<aridad>
```

Una entidad `SIGNATURE` por par `(nombre, aridad)` que **dos o más** tipos nominales
declaran. Decisiones, y por qué:

* **Constructores fuera.** Todos los tipos tienen uno, así que agruparían tipos no
  relacionados; además un constructor es una declaración, no un slot de creación.
* **Aridad, no tipos de parámetro.** `f(int)` y `f(string)` cuentan como el mismo slot.
  Es una firma **sintáctica**; el `query_claim` lo dice.
* **Entidad compartida entre ficheros y lenguajes.** Es lo que permite que un proveedor
  de un fichero empareje con otro proveedor de otro fichero, que es el caso real.
* **Solo pares con dos o más declarantes**, así que un método que declara un solo tipo no
  es slot. `test_shared_slot_is_one_entity_for_both_providers` lo comprueba con un tipo
  suelto.

## Qué NO se resuelve

* **La forma de objeto literal de JavaScript/TypeScript.**
  `const ocean = { createButton: () => new OceanButton(), createPanel: () => new OceanPanel() }`
  es la forma que la ficha nombra primero ("objetos JavaScript con funciones"), y **no se
  resuelve**: el IR modela el literal como una `COLLECTION` de tipo `record`, no como un
  tipo con miembros, así que las funciones flecha quedan declaradas por el módulo y sin
  nombre de miembro. Medido: en ese fixture no hay `HAS_METHOD` ni `IN_TYPE` para
  `createButton`. La forma que sí se resuelve —clases JS/TS sin herencia— también es un
  objeto JavaScript con funciones y sin base común, que es la propiedad que la variante
  prueba.
* **El contrato de los productos.** No se exige que los productos implementen el mismo
  contrato ni que pertenezcan a una categoría declarada; sólo que sean tipos distintos y
  que la construcción sea real (`RETURNS_NEW`, que exige un sitio de asignación resuelto).
* **La intención de familia.** Como el resto del catálogo, la firma es estructural.

## Cambio de expectativa en el catálogo, y su medición

Promover la variante cambia lo que responde la regla **raíz** `abstract-factory`, que es
la unión de las variantes `ready`. En
`tests/structural/test_algorithm_abstract_factory.py`, la mutación `same-category`
(rompe la categoría declarada del producto) y la mutación `no-contract`
(`class Ocean(Provider)` → `class Ocean`) rompen la obligación **nominal** pero dejan a
Ocean con los mismos dos slots devolviendo dos productos distintos: la variante
estructural lo reporta, con razón. La mutación `no-second-product` quita una construcción
y ningún variante la reporta.

El test ahora comprueba **las dos cosas**: que `abstract-factory#nominal-families` sigue
rechazando al proveedor mutado (`{'Land'}`) en las tres mutaciones, y que la raíz devuelve
`{'Land', 'Ocean'}` sólo en las dos mutaciones estructuralmente válidas. Medido con el
catálogo anterior, donde la variante era `design`: **6 tests fallan** (las dos mutaciones
por lenguaje) y las comprobaciones de la variante nominal **siguen pasando**, así que el
cambio es atribuible a la promoción y no a una expectativa acomodada.

## Validación

* `tests/structural/test_abstract_factory_structural_families.py`: 25 tests. Positivo y
  renombrado en los tres lenguajes, cuatro negativos por lenguaje
  (`no-shared-slot`, `single-slot`, `same-product-across`, `same-product-within`), la
  consulta raíz y la comprobación de identidad de la firma.
* Suite estructural completa: **7297 passed / 140 xfailed** (antes: 7271 / 140; los 26
  nuevos son los 25 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`).
* `mypy src/ken`: limpio (109 ficheros).
* El fichero completo **no corre** contra el catálogo anterior: la variante era `design`
  y `named_rule` no la registra.
