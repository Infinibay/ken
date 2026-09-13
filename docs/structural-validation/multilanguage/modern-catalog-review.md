# Revisión ejecutable de los diez conceptos modernos

Revisión del catálogo actual. Se inspeccionaron los diez TOML de
[modern_patterns](../../../src/ken/structural/modern_patterns), sus queries y las
pruebas fuente existentes. Los diez conceptos tienen query pública ejecutable;
no son diez placeholders. La variante transactional-change-set de Unit of Work
permanece explícitamente en diseño y no se presenta como implementada.

## Contratos revisados

| Concepto / ID público | Algoritmo reconocido | Variantes/operaciones ejecutables | Límite principal |
|---|---|---|---|
| architecture.continuation-wrapper | Devolver un handler local que invoca la continuación suministrada | Query raíz | No prueba forwarding de argumentos ni ejecución exactamente una vez |
| architecture.adapted-continuation-wrapper | Devolver un adaptador que recibe el handler que delega a la continuación | Query raíz | Pasar handler al adaptador no prueba que éste lo retenga o invoque |
| architecture.dependency-injection | Suministrar colaborador/callable a un campo usado desde otro método | object-assignment, callable-input; nuevo retained-object opt-in | La query general conserva escritura histórica; identidad entre métodos sigue abierta |
| architecture.dispatch-table | Registrar un callable por clave e invocar entrada del mismo registro | direct, adapted | No prueba que la clave utilizada haya sido registrada en ejecución |
| resilience.exception-retry | Retornar un intento protegido y repetir desde el handler del mismo loop | explicit-continue, handler-fallthrough | No distingue necesariamente fallback entre proveedores de retry del mismo destino |
| architecture.subclass-factory | Devolver una clase local derivada del parámetro base | returned-subclass | No demuestra MRO, compatibilidad runtime o aplicación del decorador |
| architecture.cache-aside | Buscar; al faltar, cargar/escribir; retornar origen pertinente | java-optional, null-miss | API y flujo local; no consistencia, invalidación, TTL ni atomicidad |
| architecture.read-through-cache | Componente con construcción de caché y caminos hit/miss/load/fill | Query raíz, read_fill | Construcción local no prueba ownership exclusivo del heap |
| architecture.batch-work-queue | Registrar trabajos, activar elementos y resetear el mismo campo | stored-batch, drain | Orden léxico de reset no garantiza exactly-once, FIFO ni éxito |
| persistence.unit-of-work | Registrar lotes por clave y coordinar al menos dos acciones sobre un store | keyed-change-set, keyed_flush | No prueba transacción única ni commit/rollback atómicos |

La revisión no transforma todas las limitaciones en requisitos universales. Por
ejemplo, el wrapper puede adaptar sus argumentos y un retry puede usar políticas
de backoff variables. Un buscador debe permitir pedir contratos más precisos sin
confundir ausencia de ese contrato con ausencia del concepto completo.

## Mejora real: retención de dependencias como contrato seleccionable

Se agregó la query `architecture.dependency-injection#retained-object` en
[dependency-injection.toml](../../../src/ken/structural/modern_patterns/dependency-injection.toml).
Reutiliza `strategy.supplied_policy` para exigir una entrada suministrada final
soportada hacia el campo, o una entrada de constructor soportada, y delegación a
ese campo desde otro método. Permite buscar explícitamente esta precisión:

```kenql
query retained_dependency {
  match "architecture.dependency-injection#retained-object"(
    unit:$consumer, dependency:$field, inject:$configure, operation:$use
  );
  emit $consumer,$field,$configure,$use;
}
```

En cinco lenguajes, la nueva query acepta inyección lineal y ruido aritmético
independiente, y rechaza estas dos roturas:

```text
configure(incoming):
    incoming = null
    self.dependency = incoming

configure(incoming):
    self.dependency = incoming
    self.dependency = null
```

También acepta las cinco formas de inyección por constructor ensayadas. Esto
mejora la precisión que el usuario puede seleccionar; no se atribuye esa garantía
a la consulta raíz ni a la variante histórica.

La query raíz conserva exactamente la unión anterior de object-assignment y
callable-input. Se evitó sustituir globalmente la escritura histórica por el
resumen lineal: la
[evaluación anterior](callable-dependency-injection.md) registró pérdidas de tres
usos válidos de Flask al imponer esa restricción sobre configuración no lineal.
Tres controles nuevos comprueban que una configuración condicional conserva el
match amplio y queda fuera del contrato preciso. Esos tres casos se clasifican
como cobertura semántica insuficiente del contrato preciso, no como true negatives.

La variante no prueba que configure ocurra antes de use, que se trate de la misma
instancia ni que no haya mutaciones del campo entre métodos. Tampoco interpreta
setters/descriptores como almacenamiento puro. No se agregaron hechos artificiales
para ocultar esas incertidumbres.

## Matriz nueva

[test_modern_catalog_review.py](../../../tests/structural/test_modern_catalog_review.py)
reutiliza fuentes de fixtures ya existentes y ejecuta la query pública de cada
concepto. Esto verifica la composición del catálogo completo, además de las
pruebas aisladas de variantes.

| Grupo | Casos | Qué se comprueba |
|---|---:|---|
| Diez conceptos en Python/JS/TS | 120 | Positivo y rotura de una relación; con/sin función independiente añadida |
| Integridad del catálogo | 1 | IDs públicos exactos; toda variante/operación ready contiene query no vacía y validable |
| Retención precisa de objetos | 20 | Cinco lenguajes: positivo, ruido, input reemplazado y campo sobrescrito |
| Constructores de inyección | 5 | Python, JS, TS, Java y C# |
| Configuración no lineal | 3 | Match amplio conservado y límite del resumen preciso explícito |

**149 tests pasan**, en 10.75 segundos. Los 120 primeros corresponden a 60
positivos y 60 negativos controlados, no a 120 algoritmos diferentes. JavaScript
y TypeScript comparten familia. La función independiente se agrega alrededor del
ejemplo: ese grupo no demuestra tolerancia a cualquier operación intercalada
dentro del algoritmo. La prueba de ruido en la nueva inyección precisa sí agrega
aritmética dentro del método de configuración.

Los contrastes de los diez conceptos rompen respectivamente la continuación,
el receiver del handler, el campo usado, el registro consultado, la repetición,
la clase retornada, el valor cargado, el valor escrito, el elemento activado y la
entidad pasada a una acción de persistencia. Las fuentes se parsean; no se ejecutan
ni importan los programas representados.

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_modern_catalog_review.py
```

La suite focalizada de los diez conceptos completó **1.152 passed en 89.64 s**.
Incluye la revisión nueva y las pruebas de inyección por objetos/callables,
propiedad de closures, continuaciones adaptadas, dispatch directo/adaptado, retry,
finalización normal, subclass factories, cache-aside, read-through, comandos en
cola y Unit of Work. No es la suite completa del repositorio.

## Qué no mide esta revisión

No se estiman precisión/recall globales a partir de estas fixtures y no se hizo
un nuevo benchmark externo en este subtrabajo. Las auditorías existentes conservan
sus resultados; la nueva variante no modifica el criterio de las diez consultas
públicas por defecto. La comparación externa actual corresponde al trabajo de
integración, no a estos 149 tests.

Las queries de wrappers aún necesitan efectos de llamadas/capturas para demostrar
ejecución y lifetime; las de registros necesitan identidad temporal de claves y
contenedores; Retry necesita destino estable, caminos alcanzables y protocolo de
error; Unit of Work necesita transacciones; las cachés necesitan efectos de APIs
y concurrencia. No se cambia una variante design a ready con una firma vacía.

La mejora incorporada usa el IR existente y una operación nombrada compartida.
El resto de necesidades se mantienen visibles como límites del contrato, para
que la siguiente extensión del núcleo pueda responder a una obligación concreta
en vez de añadir relaciones específicas sin semántica común.
