# `proxy#remote-subject` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados
(`python`, `javascript`, `typescript`, `java`, `csharp`, `cpp`, `go`, `rust`).
Fecha: 2026-09-14. Base: IR 1.71.0. **Sin cambio de IR**: la query se escribe con hechos
que ya existían. Con ella el catálogo queda **77 `ready` / 0 `design`**.

## Qué se publica

La segunda alternativa que la ficha permite —"implementación local visible que serializa
la llamada y devuelve su respuesta"—, sin tabla de nombres de API:

```
String call(String payload) {
    String response = client.post("/api", codec.encode(payload));
    return codec.decode(response);
}
```

Cuatro piezas, y las cuatro son necesarias:

| Rol | Hecho |
|---|---|
| Representación local del contrato | `$unit SUBTYPE_OF $contract`, o `$unit IMPLEMENTS $contract` (Go satisface la interfaz por method set) |
| Cliente de **otro** contrato | `$unit HAS_FIELD $client`, `$client TYPE $client_type`, `different $client_type $contract` |
| Serializa la llamada | `$method HAS_CALL $transport`, `$transport RECEIVER $client`, `$transport ARGUMENT $argument` —`VALUE`→ `$encoder RESULT $encoded`, `call() as $encoder`— y el argumento del codificador carga del **propio parámetro** |
| Devuelve su respuesta | `$method RETURNS_CALL $decoder`, `different $transport $decoder` |

La unión `SUBTYPE_OF`/`IMPLEMENTS` es la única forma de cubrir los ocho. `different
$transport $decoder` no es cosmética: sin ella la propia línea del decodificador se colaba
como transporte y Java devolvía **dos** matches, el segundo espurio. Y la traza del
parámetro es lo que rechaza `other-payload`.

## El tipo del cliente, que es lo que cuesta en JavaScript

El contrato exige que el cliente esté **tipado** y que su tipo no sea el contrato; sin eso
aceptaría cualquier decorador que casualmente serialice. Siete lenguajes lo alcanzan por
declaración (anotación de Python, campos de java/csharp/cpp/go/rust, campo de TypeScript),
y **JavaScript no declara tipos de campo**. Lo que sí tiene es la **construcción**: medido,
`this.client = new HttpClient()` produce `TYPE client -> HttpClient`, mientras
`this.client = client` no produce nada. El fixture de JavaScript usa esa forma, que además
es idiomática (el proxy construye su transporte).

## Limitación registrada (C++)

El fixture de C++ usa `int` como payload. La resolución de `OVERRIDES` de C++ no resuelve
**grafías de tipo cualificadas** en la firma virtual: medido, `virtual std::string
call(std::string)` no produce `OVERRIDES`, y `virtual int call(int)` sí. Es una limitación
previa y general de C++ (no de esta variante): la query exige `OVERRIDES` como evidencia de
que el método implementa un slot del contrato, y el fixture la satisface con tipos
primitivos. Queda anotada para quien aborde el resolutor de firmas virtuales de C++.

## Lo que se dejó sin resolver a propósito

* **Que el transporte sea remoto.** No hay modelo RPC: la variante acepta la
  *implementación local visible*, y la otra alternativa de la ficha (una tabla de nombres
  de API RPC por lenguaje) **no** se implementa. La medición de por qué la tabla es
  incómoda está en
  [bloqueos medidos](P9-remaining-variants-blockers.md): el nombre del cliente viaja en el
  **receptor** (`requests`), no en `CALLEE_NAME` (`post`), que por sí solo es demasiado
  genérico.
* **Que el códec serialice de verdad**, que el cliente no se reasigne, que la respuesta se
  consuma entera y que ningún camino de excepción salte el decodificado.
* **Alcance por lenguaje.** Los ocho son los validados; la query no filtra por lenguaje.

## Validación

* `tests/structural/test_proxy_remote_subject.py`: 65 tests. Positivo y renombrado en los
  ocho lenguajes, cuatro negativos por lenguaje (`no-codec`, `same-contract-client`,
  `no-decode`, `other-payload`) derivados del positivo con **ediciones explícitas por
  lenguaje** y parseados en `build()`, la consulta raíz `proxy` en los ocho, los metadatos
  y la comprobación de que el tipo del cliente es lo que separa la variante de un
  decorador.
* Suite estructural completa: **7617 passed / 140 xfailed** (antes: 7551 / 140; los 66
  nuevos son los 65 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`). Ningún test existente cambió de expectativa.
* `mypy src/ken`: limpio (109 ficheros).
* Medición contra el catálogo anterior: los **65** tests fallan, porque la variante era
  `design` y `named_rule` no la registra.
