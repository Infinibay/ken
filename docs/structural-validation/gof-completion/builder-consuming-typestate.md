# `builder#consuming-typestate` (3 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **tres** lenguajes declarados.
Fecha: 2026-09-14. Base: `c26fa0d` (IR 1.64.0), IR 1.65.0.

## La disyunción de la ficha, y qué lado se implementó

La ficha dice: *el paso cambia parámetros de estado **o** mueve el builder; la
finalización recibe un estado admitido*. Son dos lados, y elegí el primero porque es el
único **uniforme en los tres lenguajes**:

| Lenguaje | ¿Puede expresarse el movimiento? |
|---|---|
| C++ | sí: `ref_qualifier: '&&'` ya está en el método |
| Rust | **no**: la propiedad del receptor (`self` vs `&self`) no se registra |
| TypeScript | no tiene ownership |

Así que el contrato exige que el paso devuelva **otra instanciación del propio builder**
cuyo argumento difiere del nombre del parámetro de estado. El lado del movimiento no se
exige, y `query_claim` dice explícitamente que no se prueba.

## Dos estados, no uno

Exigir que el paso devuelva `Builder<...>` con un argumento distinto es insuficiente por
sí solo: un builder fluido genérico que devuelve `Builder<State>` pasaría. Por eso hay un
segundo requisito: **al menos dos argumentos de estado distintos**, contados sobre los
métodos del builder. Eso convierte el contrato en una *transición* —hay un estado inicial
y uno admitido— en vez de un retorno genérico.

## El ruido del producto cruzado, y cómo se fijó la finalización

La primera versión no fijaba la finalización: `$finish` era «cualquier método que no sea
el paso», así que los matches eran el producto cruzado paso × finalización —nueve filas
en Rust para un fixture con tres pasos y un `finish`—. Se arregló **positivamente**,
exigiendo que la finalización devuelva el slot acumulado del builder
(`$finish RETURNS $storage`), con lo que queda ligada a un único método. Las tres
lenguas quedan en **dos** matches, uno por estado admitido.

Ese arreglo tiene una consecuencia que declaro: el rol `product` que la query raíz de
builder exige es **ese slot acumulado**, no un tipo construido. Probé la alternativa —que
la finalización construyera un producto real— y **no funciona en los tres**: C++ no emite
`RESULT`/`ALLOCATES_TYPE` de la misma forma para `return Product{accumulated}`, y Rust y
TypeScript volvían al producto cruzado porque la finalización dejaba de estar fijada. El
`query_claim` lo dice: esta variante no exige que la finalización construya nada.

## Una colisión de nombres en el fixture, que no es de esta variante

La primera versión de los fixtures de Rust y C++ llamaba `value` **al campo y a un
método**. `finish` devolvía `self.value` y el grafo lo resolvía al **método**, no al
campo, así que `$finish RETURNS $storage` fallaba. Separé los nombres
(`accumulated` para el campo, `with_value` para el método) y funcionó. Lo anoto porque es
un comportamiento real del resolvedor —un campo y un método homónimos colisionan— y no
algo que esta variante introduzca.

## Negativos cubiertos

16 pruebas en `tests/structural/test_builder_consuming_typestate.py`: 3 positivos, 3 de
«los dos estados se reportan», 3 de renombrado, 4 negativos, 3 de la capacidad y las
comprobaciones del contrato.

| Negativo | Por qué se rechaza |
|---|---|
| builder fluido que nunca cambia de estado (Rust, C++, TS) | el paso devuelve `Builder<State>`: no hay transición |
| builder no genérico | no hay parámetro de estado |
| finalización que no devuelve el slot acumulado | `RETURNS $storage` no se satisface |

## Límites declarados

`query_claim` no prueba que la finalización **solo** sea alcanzable desde un estado
admitido: la especialización no se modela —`impl Builder<Pending>` e `impl Builder<Ready>`
resuelven al mismo tipo—, así que «la finalización recibe un estado admitido» queda
cubierto solo en el sentido débil de que existe una finalización. Tampoco prueba
sustitución de tipos, ni que el argumento del retorno corresponda a una declaración
existente. El renombrado usa fixtures construidos por lenguaje, no sustitución de cadenas.

## Validación

`tests/structural/` completo, sin regresiones, más las 16 pruebas nuevas.
`mypy src/ken` limpio.
