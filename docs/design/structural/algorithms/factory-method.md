# Factory Method: el slot de creación y el producto que usa el algoritmo

Estado: ejercicio en palabras, traducción al IR y **30 pruebas pasando** en
Python, Java y TypeScript. Véanse el [contrato general](../gof-algorithm-contracts.md#3-factory-method),
la [regla de definición](../../../../src/ken/structural/patterns/factory-method.toml)
y la [matriz ejecutable](../../../../tests/structural/test_algorithm_factory_method.py).

## Algoritmo en palabras

1. Definir un algoritmo que necesita un producto y conoce el contrato con el que
   podrá usarlo. La decisión de qué implementación crear se deja a un slot de
   extensión.
2. Cuando el algoritmo necesita el producto, invocar ese slot sobre su creator.
   Un creator concreto sobrescribe el slot y decide cómo obtenerlo.
3. En la variante de construcción directa, construir el producto y devolver ese
   mismo valor, admitiendo variables locales y aliases intermedios.
4. El algoritmo recibe el resultado del slot y lo utiliza por el contrato del
   producto. Construir un producto fijo en el consumidor después de ignorar el
   resultado rompe esta colaboración, aunque la fábrica siga estando definida.

La definición de un método fábrica y un uso correcto de esa definición son dos
consultas diferentes. No encontrar clientes dentro del repositorio no elimina
un método fábrica exportado por una biblioteca.

## Del algoritmo al IR

El núcleo de instrucciones debe separar el slot que se invoca de los candidatos
concretos que pueden implementarlo. El siguiente texto es una representación
objetivo, no sintaxis aceptada por un parser de instrucciones.

```text
function Base.execute(%self) {
  %product = call %self, slot: Base.make, dispatch: virtual
  %result = call @consume, argument[0]: %product
  return %result
}

function Concrete.make(%self) overrides Base.make {
  %allocated = construct @Product
  @result = slot.declare Product
  slot.store @result, %allocated
  %metric = binary.add 1, 2
  call @log, argument[0]: %metric
  %returned = slot.load @result
  return %returned
}
```

`call`, `construct`, slots, valores y retorno ya existen como instrucciones.
La identidad de un slot de despacho y sus candidatos pertenece a la resolución
semántica del grafo. Relacionar ambas vistas no implica demostrar qué override
se ejecutará en una instancia concreta.

Un nombre de variable no identifica un producto. Este cuerpo conserva el
producto aunque cambie el binding original:

```text
%p = construct @Product
slot.store @result, %p
%snapshot = slot.load @result
slot.store @saved, %snapshot
slot.store @result, null
%returned = slot.load @saved
return %returned
```

En cambio, `result = null; return result` rompe el origen del retorno. Para
objetos Python/Java/TypeScript, asignar `saved = result` conserva una referencia
al mismo objeto; no copia su estado ni crea un producto independiente.

## Contratos y ruido intermedio

| Afirmación | Evidencia requerida | Lo que no demuestra |
|---|---|---|
| Método reemplazable | Relación entre override y slot del contrato | Que un caller despache a ese override en ejecución |
| Producto nuevo devuelto | Origen del valor que llega al retorno | Que todas las ramas retornen el mismo tipo |
| Uso por el algoritmo | Resultado del slot usado como receptor/argumento o retornado | Que el consumidor cumpla obligaciones de dominio |
| Contrato del producto | Tipo esperado y compatibilidad del producto concreto | Compatibilidad sólo por nombres parecidos |
| Preservación entre pasos | Valores y escrituras, más efectos relevantes | Pureza de una llamada arbitraria de logging |

Las pruebas insertan suma local y logging de números entre construcción y
retorno, y antes de la invocación del slot. Conservan los matches y aceptan el
alias `saved`. No comprueban ausencia de excepciones ni monkey-patching de las
funciones de logging. Una prueba estricta de efectos debería producir `unknown`
si no puede resolverlas.

## Refinamiento de cliente que ya se puede expresar

La prueba usa esta **query KenQL ejecutable** mediante un `SavedRule` temporal;
no se añadió como operación pública del catálogo:

```kenql
query factory_client {
 match "factory-method"(factory:$factory, product:$product);
 require $factory OVERRIDES $slot;
 require $creation TARGET $slot;
 require $creation RESULT $value;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $value;
 emit $factory, $creation, $consumer;
}
```

Esto responde a una pregunta concreta: «¿hay una llamada al slot base cuyo
resultado se pasa directamente como argumento a otra llamada?». El positivo
es `consume(self.make())` / `consume(this.make())` en el algoritmo base.

Los negativos `consume(new Product())` y `this.make(); consume(new Product())`
no cumplen el refinamiento, pero siguen encontrando la definición de Factory
Method. Así se evita eliminar definiciones válidas para corregir un problema
que pertenece al cliente.

Esta query no cubre por sí sola todas las formas de uso: una cadena de aliases,
un retorno al caller o una llamada donde el producto sea el receptor necesitan
otras rutas de flujo. Tampoco correlaciona el tipo dinámico del creator concreto
con el caller: une candidatos que sobrescriben el mismo slot. Es evidencia de
colaboración posible, no un análisis completo de points-to.

## Variantes por lenguaje

| Lenguaje | Forma de extensión | Trabajo de normalización |
|---|---|---|
| Python | Método sobrescrito, ABC o protocolo | Slot nominal cuando existe; tipos opcionales, aliases y retorno de `None` |
| Java | Método abstracto/virtual, retorno covariante | Resolución del slot, contratos del producto y posibles destinos |
| TypeScript | Clase abstracta u objeto estructural | Distinguir herencia de un callback de creación; genéricos y uniones |
| JavaScript | Método de prototipo o función inyectada | Un callback constructor es una variante funcional, no prueba de override nominal |
| C# | Virtual/abstract, interfaces, delegates | Despacho, tipos de retorno y alternativas funcionales explícitas |
| C++ | Virtual factory o CRTP/templates | Ownership de `unique_ptr`, retorno por valor y especialización |
| Go | Interfaz de creación recibida por el algoritmo | Contrato implícito; `(Product, error)` y selección del valor producto |
| Rust | Trait con tipo asociado o genérico | Tipos asociados, ownership y envoltorios `Result`/`Option` |

Un método que devuelve un objeto cacheado o clonado puede cumplir la intención
del patrón sin una construcción directa. La variante actual `virtual-slot`
requiere `RETURNS_NEW`; `contract-slot` para Go/Rust sigue en diseño. Esta matriz
no demuestra cobertura de todas las formas de la tabla.

## Validación y límites pendientes

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_factory_method.py
```

Resultado: **30 passed**, sin `xfail`.

- Nueve casos de definición: baseline, ruido y renombrado por lenguaje.
- Nueve negativos de definición: quitar override, rebinding del retorno y
  construcción descartada.
- Tres casos de alias que conserva el producto tras cambiar el binding original.
- Tres positivos del refinamiento de cliente.
- Seis negativos del refinamiento, manteniendo detectable la fábrica válida.

Son fixtures de fuente parseada, no un benchmark de compilación o ejecución.
Los negativos pueden romper el contrato estático de retorno o dejar una clase
sin herencia deliberadamente; Tree-sitter verifica sintaxis, no tipado completo.

La regla actual de definición no requiere que el producto satisfaga el tipo de
retorno del slot ni que exista un algoritmo cliente. Lo segundo es correcto para
una consulta de definiciones; para probar colaboración se necesita composición.
Quedan pendientes análisis de despacho por instancia, caminos entre creación y
consumo, compatibilidad de tipos, flujo a través de wrappers y semántica de
efectos desconocidos. Las pruebas nuevas aprovechan hechos existentes y no
presentan esas capacidades pendientes como implementadas.
