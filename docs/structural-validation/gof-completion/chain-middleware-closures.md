# `chain#middleware-closures` (8 lenguajes) — cerrada

Estado: **cerrada**, sin residuo. La variante es `ready` en sus **ocho** lenguajes
declarados, y su último hueco se cerró en IR 1.61.
Fecha: 2026-09-14. Base: `dbe4ec7` (IR 1.60.0), IR 1.61.0.

## Séptima variante que no necesitó capacidad nueva

`linked-handlers` cubría la forma de objeto: un handler con un sucesor del mismo
contrato y reenvío condicional. Ésta es la forma de cierre, y su contenido entero es
que **capturar `next` no alcanza**: `decorator#callable-wrapper` ya cubre un wrapper
que captura y siempre reenvía. Lo que convierte al cierre en un eslabón de cadena es
que el reenvío esté **guardado por una rama**, de modo que el handler pueda además
devolver sin reenviar.

Todo estaba ya en el grafo:

| Necesidad | Hecho |
|---|---|
| La fábrica recibe el siguiente handler | `HAS_PARAMETER` |
| El handler lo captura | `CAPTURES` |
| Hay una decisión | `HAS_OPERATION` + `operation(kind: branch)` |
| La rama tiene dos desenlaces distintos | dos `CFG_NEXT` + `different` |
| Un desenlace devuelve el resultado del delegado | `RETURN_OPERAND` o `SYNTAX_NODE` |
| El otro devuelve otra cosa | `RETURN_OPERAND` + `different` |

## La expresión de cola de Rust

Siete lenguajes escriben el desenlace que continúa como un `return` explícito, así que
`RETURN_OPERAND` liga el `return` con la llamada al delegado. Rust no: el idioma es la
**expresión de cola**,

```rust
move |request: &str| {
    if request.is_empty() { return "denied".to_string(); }
    next(request)          // sin `return`
}
```

donde la llamada *es* el sucesor de la rama, no el operando de un `return`. Se midió
que `RETURNS` del cierre ya incluye esa llamada, pero también incluye la del otro
ramal, así que no discrimina. Lo que sí la ata a la rama es `SYNTAX_NODE`: la entidad
`CALL` es el nodo sintáctico de ese sucesor concreto. La query acepta las dos grafías:

```kenql
any { require $continuing RETURN_OPERAND $delegate; }
or { require $delegate SYNTAX_NODE $continuing; }
```

## El residuo de la ronda anterior, y cómo se cerró

La primera entrega de esta variante **no** necesitó IR, y dejó un hueco medido: una
rama que delega en **AMBOS** desenlaces matcheaba. Ese handler nunca termina —todos sus
caminos reenvían—, así que estructuralmente es un wrapper y no un eslabón con decisión
real. Se midió en vez de suponerse: el fixture de doble delegación daba **2 matches**.

Se registró como `xfail(strict=True)` con la capacidad faltante nombrada, y esta
entrega la construyó. Hacía falta **completitud de llamadas**: expresar «este ramal no
delega» exige cardinalidad exacta o ausencia acotada, y ambas exigen que el bloque esté
*cerrado*, lo que a su vez requiere una capacidad `complete:<sujeto>:<relación>`.

La cláusula que lo cierra:

```kenql
count distinct $call = 1 {
 require $wrapped HAS_CALL $call;
 where $call.name == $delegate.name;
};
```

Tres detalles costaron iteraciones y quedan como contrato:

1. **El filtro va en `where`, no en un segundo `require`.** `closed()` resuelve el
   sujeto de cada hecho contra la fila **externa**, así que un `require` cuyo sujeto se
   liga *dentro* del bloque nunca puede cerrarse. `where $call.name == …` no añade un
   hecho y por eso sí funciona.
2. **Se filtra por el nombre del delegado, no por el del parámetro.** Java invoca el
   callable capturado como `next.apply(request)`, así que el nombre del callee es
   `apply` y no `next`; el nombre del parámetro habría rechazado Java.
3. **El retorno delegado no es necesariamente sucesor directo de la rama.** Con
   sentencias intermedias (`log(request); audit(request); return next(request)`) el
   sucesor de la rama es la primera de ellas. `path $continuing CFG_NEXT{0,4}
   $arm_return` lo generaliza sin aflojar el contrato.

Las llamadas no relacionadas no cuentan: el conteo está acotado por nombre de callee, y
`test_unrelated_calls_do_not_count_towards_the_delegation` lo fija con dos llamadas
ajenas de por medio.

## Negativos cubiertos

26 pruebas en `tests/structural/test_chain_middleware_closures.py`: 8 positivos (uno
por lenguaje), 8 negativos de wrapper incondicional (uno por lenguaje), 4 negativos
propios de Python, 4 de doble delegación (Python, JavaScript, Java y Go) y 2
comprobaciones del contrato publicado.

| Negativo | Por qué se rechaza |
|---|---|
| wrapper incondicional, en los 8 lenguajes | sin rama no hay eslabón: es `decorator#callable-wrapper` |
| handler que nunca reenvía | no hay llamada al delegado |
| handler que reenvía pero no devuelve su resultado | `RETURN_OPERAND` no liga el delegado |
| handler que no captura `next` | falta `CAPTURES` |
| rama que delega en ambos desenlaces | el conteo exacto por nombre de callee da 2, no 1 |

## Límites declarados

`query_claim` no prueba manejo exclusivo, preservación de la request ni topología de la
cadena. Tampoco prueba que exista un camino que termine: prueba que el reenvío está
**guardado por una rama**, que es lo que la ficha pide distinguir del pipeline
incondicional.

## Validación

`tests/structural/` completo, sin regresiones, más las 26 pruebas nuevas.
`mypy src/ken` limpio. `xfailed` vuelve de 141 a 140: el marcador que esta misma
variante había añadido se retiró al cerrarse la capacidad.
