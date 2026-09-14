# Flyweight: del algoritmo en palabras al IR

El [patrón ejecutable](../../../../src/ken/structural/patterns/flyweight.toml)
reconoce pooling indexado. Eso es evidencia candidata de Flyweight: todavía hay
que distinguir el estado compartido de los datos específicos de cada uso. Una
cache que guarda resultados o entidades mutables no se convierte automáticamente
en Flyweight porque tenga lookup, inserción y retorno.

## Algoritmo en palabras

1. Separar estado intrínseco compartible de contexto extrínseco de cada uso. En el
   ejemplo, la fuente del glifo es intrínseca y su posición es extrínseca.
2. Construir o recibir una clave que identifique la equivalencia de estado
   intrínseco relevante dentro del ámbito del pool.
3. Buscar esa clave en el pool. Si existe un representante, reutilizarlo.
4. Si falta, crear un representante con ese estado y retenerlo bajo la misma
   clave/pool. Devolver el representante retenido.
5. En cada uso, suministrar el contexto extrínseco al representante. Evitar que
   ese contexto sobrescriba el estado que otros usos esperan compartir.

Este contrato no exige que todos los bytes del objeto sean inmutables: puede haber
memoización interna compatible con el estado lógico. Sí exige que el estado
compartido conserve las propiedades en las que se apoyan los clientes. Tampoco
promete identidad eterna si el pool usa referencias débiles o eviction: el ámbito
y la política de retención forman parte del contrato.

## Identidades e invariantes

| Elemento | Obligación |
| --- | --- |
| Clave | Lookup, construcción, inserción y retorno corresponden a la misma clave lógica |
| Pool | Las operaciones usan el mismo contenedor dentro del ámbito seleccionado |
| Objeto creado | Es el que se inserta, no una creación incidental abandonada |
| Objeto devuelto | Es el representante retenido o recuperado |
| Estado intrínseco | Procede de la clave/configuración y permanece válido para los usos compartidos |
| Contexto extrínseco | Llega desde el cliente en cada uso; no corrompe estado intrínseco |
| Identidad temporal | Se conserva durante el intervalo de retención declarado |

Dos lecturas del mismo binding `key` pueden tener valores distintos si hay una
asignación entre ellas. Dos claves distintas pueden ser equivalentes tras
normalización. Se necesitan identidad de valores y política de equivalencia, no
sólo coincidencia de nombres o del hash calculado.

## IR objetivo

Notación de diseño, no sintaxis nueva ya ejecutable por el matcher:

```text
function obtain(%pool, %key) {
  %lookup = map.lookup %pool, %key [absence = explicit]
  %representative = choose present(%lookup) {
    present { output lookup.value(%lookup) }
    absent {
      %created = construct @Glyph(%key)
      map.insert %pool, %key, %created
      output %created
    }
  }
  return %representative
}

function draw(%glyph, %position) {
  %font = memory.load (field.addr %glyph [field = font])
  %output = call @render(%font, %position)
  return %output
}
```

`map.lookup`/`map.insert` y la política de ausencia son necesidades semánticas de
este contrato. El núcleo tiene direcciones indexadas, memoria, valores y regiones;
no debe reinterpretar indiscriminadamente cualquier indexación como mapa seguro
con ausencia. Una indexación de array puede fallar por rango y un acceso de mapa
puede lanzar, devolver un sentinel o producir un optional.

El buscador debe preservar pool, clave y representante entre eventos. Logging de
un número independiente puede intercalarse. Un `key = 0`, una sustitución del pool
o una llamada que recibe aliases relevantes requieren análisis adicional. El
resultado de la rama miss debe ser el objeto insertado; el de hit debe ser el
recuperado. Puede haber variables temporales o retornos separados sin cambiar el
algoritmo.

Para probar uso Flyweight, componer otro contrato: el resultado de `obtain` llega
al receiver de `draw`, el cliente aporta la posición y las escrituras no alteran
el estado intrínseco protegido. La query actual no evalúa todavía ese refinamiento.

## Variantes y límites por lenguaje

| Variante | Lenguajes / ejemplo | Necesidad del IR |
| --- | --- | --- |
| Índice explícito | Python dict, Java arrays/mapas, JS/TS objetos/arrays | Contenedor, clave, valor insertado y política de ausencia |
| API get/put | Java/C#/Python | Resolver receptor/API y correlacionar argumentos/resultados |
| Entry/get-or-add | Rust `entry`, Java `computeIfAbsent`, C# `GetOrAdd` | Callback diferido, valor retenido y semántica de concurrencia |
| Interning de strings | Muchos runtimes | Contrato de API y ámbito de canonicalización |
| Pool de referencias débiles | Java/Python/JS y bibliotecas | Retención condicionada, recolección y nueva creación posterior |
| Clave compuesta | Tuplas, structs, records | Equivalencia seleccionada, hashing y componentes inmutables relevantes |
| Flyweight sin pool explícito | Tablas preconstruidas/constantes | Compartición observada y contexto extrínseco sin exigir inserción lazy |

Las APIs de entry no deben reducirse a “factory exactamente una vez”: la garantía
real depende de la API resuelta y su contrato. La variante `entry-api` pasó a `ready`
**sin cambio de IR**: el API de entrada ya se reconoce por nombre (`computeIfAbsent`,
`GetOrAdd`, `try_emplace`, `insert_or_assign`, `entry`), su receptor tiene que ser el
campo pool —no un local ni un parámetro— y el objeto retenido lo devuelve el método,
en las tres formas que midió la implementación (la propia llamada, una cadena
`MEMBER_OF` sobre el `pair` de C++, o el envoltorio `or_insert_with` de Rust). Estas
notas no validan las garantías de concurrencia de cada API, y el `query_claim` lo dice:
no se afirma que el factory corra exactamente una vez. La matriz nueva ensaya Python,
Java y TypeScript con índices explícitos.

## Pruebas y corrección acotada

[`test_algorithm_flyweight.py`](../../../../tests/structural/test_algorithm_flyweight.py)
incluye un glifo con fuente almacenada y posición por argumento, un pool y dos
usos con la misma clave y posiciones diferentes. Se analiza el código; no se
ejecutan los fixtures.

La primera ejecución mostró **9 falsos positivos** que la query anterior permitía:
insertar bajo otra clave, retornar otra clave y crear un glifo correcto pero guardar
otro que no corresponde al pedido. Se corrigieron usando hechos ya disponibles:

- La operación de escritura debe tener `WRITES_ELEMENT` al pool y `INDEX` a la
  clave seleccionada.
- `STORES_VALUE` debe apuntar a la construcción que recibe esa clave.
- El retorno indexado debe exponer `CONTAINER` e `INDEX` al mismo pool y binding.

No se cambió el motor. Esta correlación es más fuerte que observar una escritura
cualquiera y una creación cualquiera dentro del mismo método; no demuestra
estabilidad temporal ni la condición del miss.

Resultado de la matriz nueva: **15 passed, 9 xfailed**:

- 6 positivos con/sin logging y aritmética independiente alrededor del lookup.
- 9 negativos de clave/objeto ahora rechazados, tres por lenguaje.
- 3 gaps de reemplazo incondicional: el método crea otro representante en cada
  llamada, aun si el pool ya contiene uno.
- 3 gaps de valor temporal: `key = 0` antes del retorno conserva el identificador
  del binding pero cambia el lookup efectivo.
- 3 expectativas pendientes del contrato de estado intrínseco estable: `draw`
  sobrescribe la fuente con la posición específica del cliente.

Los nueve xfail estrictos **no son detecciones correctas**. Los tres últimos
corresponden al refinamiento de uso prometido por ese ejemplo; la query candidata
actual sólo inspecciona pooling. El resultado combinado con los canónicos se
registra en la entrega de esta revisión.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_flyweight.py
```

## Mejoras pendientes

1. Condición de ausencia y flujo hit/miss que demuestre reutilización, incluyendo
   distintas APIs y sentinels.
2. Valores de clave/pool a lo largo de instrucciones, aliases y efectos; una
   relación `INDEX` al binding no prueba que no se reasignó.
3. Modelos de equivalencia de claves y cobertura del estado intrínseco. No exigir
   que todos los campos constructor sean parte de la clave.
4. Named queries de uso y preservación de estado lógico compartido, separadas de
   la firma de cache/pool.
5. Políticas explícitas de retención/concurrencia y manejo de factories que pueden
   correr más de una vez aunque sólo un resultado se publique.

No se atribuye al patrón una reducción medida de memoria, inmutabilidad, thread
safety o identidad global. Tampoco se midió aquí el impacto del endurecimiento en
repos externos; se validaron los canónicos y esta matriz controlada.
