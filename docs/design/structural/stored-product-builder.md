# Builder con producto almacenado y copia al finalizar

Estado: implementado en IR **1.31.0**, después del diseño de esta variante.
La [guía operativa](../../structural-ir.md) es la referencia de disponibilidad;
la [auditoría reproducible](../../structural-validation/multilanguage/stored-product-builder.md)
registra resultados y límites.

## Problema y representación

RecordBuilder y MetadataBuilder de rust-lang/log conservan un producto interno,
lo configuran por campos y devuelven su clon. Una firma que exige construir el
producto dentro de build no puede reconocerlos. Además, `Record<'a>` no es el
nombre literal de la declaración `Record`. La solución conserva tanto la
anotación completa como el enlace a su declaración nominal.

El recorrido implementado es:

1. Un tipo builder tiene un campo anotado o inferido como producto diferente.
2. Un método del builder contiene una construcción de ese producto que se asigna
   al campo, directamente o mediante un inicializador de la construcción del builder.
3. Otro paso de instancia recibe un parámetro explícito sin reasignaciones y lo
   escribe directamente en un miembro del producto interno.
4. Una finalización distinta del paso devuelve ese campo o una copia derivada
   reconocida del mismo campo. No se unen evidencias de productos diferentes.

La query está en [builder.toml](../../../src/ken/structural/patterns/builder.toml),
variante `stored-product`. Sus roles públicos son `builder`, `finish` y `product`.
El paso no necesita devolver `self/this`: también cubre configuración no fluente.
Un paso es suficiente; no se exige una cantidad arbitraria de setters.

## Ejemplos de fuente

Ejemplo propio Rust; la finalización copia el producto interno:

```rust
#[derive(Clone)]
struct Product<'a> { label: &'a str }
struct Builder<'a> { product: Product<'a> }
impl<'a> Builder<'a> {
    fn new() -> Self { Builder { product: Product { label: "" } } }
    fn label(&mut self, value: &'a str) -> &mut Self {
        self.product.label = value;
        self
    }
    fn finish(&self) -> Product<'a> { self.product.clone() }
}
```

También se admite `fn finish(self) -> Product<'a> { self.product }` como devolución
directa. No significa que el analizador haya validado el borrow checker.

Ejemplo propio Python; configuración no fluente y devolución directa:

```python
class Product:
    def __init__(self):
        self.label = ""

class Builder:
    def __init__(self):
        self.product = Product()

    def label(self, value):
        self.product.label = value

    def finish(self):
        return self.product
```

JS/TS, Java y C# pueden expresar la misma forma mediante
`this.product = new Product()`, `this.product.label = value` y
`return this.product`. Los fixtures incluyen esos seis lenguajes, renombrados,
miembros anidados y una segunda forma Rust con clone.

## Contratos del IR

### Declaración nominal y anotación completa

`TYPE_HEAD` conserva la raíz nominal obtenida del AST de una anotación Rust a
través de referencias, punteros y aplicaciones genéricas. `TYPE` enlaza esa raíz
con una declaración local resuelta; no reduce `external::Product<'a>` al nombre
`Product`. Tampoco convierte arrays, tuplas ni componentes de contenedores en
el tipo del valor que los contiene. Imports Rust arbitrarios y aliases de tipos
necesitan modelos adicionales.

`TYPE_NAME`, `native_type` y `TYPE_REF` conservan especialización, lifetime y forma
escrita. `Product<'a>` y `&Product<'b>` pueden enlazar la misma declaración sin
que eso pruebe igualdad de tipos, lifetimes o modos de acceso. Los parámetros
Rust de tipo/const se conservan en `type_parameters` de su ámbito: un `T` ligado
no se resuelve como una clase global homónima.

### Inicializadores

Rust `struct_expression` emite el protocolo de inicializadores ya usado por Go:
`HAS_INITIALIZER` de construcción a operación fuente, `FIELD_NAME`, `STORES_VALUE`
y `INITIALIZES_FIELD` al resolver el campo nominal. Se admiten campos explícitos
y shorthand. Los campos con atributos conservan `modality=may`, también cuando
hay comentarios entre atributo y campo. No se evalúan cfg ni macros.

`Product { value, ..other }` aporta evidencia para `value`; no inventa escrituras
para los campos aportados por `other`. Estos hechos preservan el operando fuente,
no sustituyen un análisis general de valores o de efectos del inicializador.

### Última entrada directa a un miembro

`FINAL_MEMBER_INPUT` vincula una operación de escritura con un parámetro explícito,
y `ASSIGNMENT_TARGET` conserva el miembro escrito. El pase `linear-members/1`:

- considera Python/JS/TS/Java/C#/Rust y cuerpos con asignaciones a miembros;
- exige eventos directos dentro del cuerpo, permitiendo wrappers de declaraciones;
- conserva la última escritura a cada miembro antes del primer retorno explícito;
- exige que el parámetro no tenga ninguna reasignación explícita en el cuerpo;
- rechaza ramas, bucles, excepciones, suspensión, funciones anidadas, operaciones
  de ámbito dinámico conocidas, escrituras compuestas y asignaciones no modeladas.

`MEMBER_FLOW_STATUS` indica `supported` o `unsupported`, con `reason`. La ausencia
del estado puede significar que no era candidato o que el grafo tiene diagnósticos.
Las relaciones llevan `basis=linear-syntax` y `analysis=linear-members/1`.
Un retorno fluente está permitido, incluido el tail Rust. Las escrituras después
del primer retorno explícito no reemplazan el resultado; otros controles no se
resuelven como un análisis completo de código muerto.

## Consultas y composición

```kenql
query stored_builders {
  match "builder#stored-product"(builder: $builder, finish: $finish, product: $product);
  emit $builder, $finish, $product;
}
```

La operación pública `prototype.derived_copy`, definida en
[prototype.toml](../../../src/ken/structural/patterns/prototype.toml), expone tipo,
receptor y llamada `clone` del modelo existente de `derive(Clone)`:

```kenql
query copied_products {
  match "prototype.derived_copy"(unit: $product, receiver: $stored, copy: $copy);
  require $finish RETURNS_CALL $copy;
  emit $product, $stored, $finish;
}
```

Builder reutiliza esta operación con el campo interno ya ligado. Una llamada
sobre otro receptor no satisface el vínculo. Un método inherente `clone` resuelto
no se supone equivalente al derivado. El modelo exige el derive reconocido y una
llamada de nombre clone no resuelta; no acredita expansión de macros, resolución
de derives importados, deep copy ni despacho arbitrario.

Las relaciones también se pueden consultar sin usar el catálogo:

```kenql
query configured_members {
  require $write FINAL_MEMBER_INPUT $input [basis: linear-syntax];
  require $write ASSIGNMENT_TARGET $member;
  path $member MEMBER_OF{1,8} $root as $access;
  emit $write, $input, $root, $access;
}
```

El límite de ocho enlaces es explícito en la variante: miembros más profundos
necesitan una consulta con otro presupuesto o una variante adicional.

## Contraejemplos y límites

`self.product.label = 0`, una entrada reemplazada antes de escribir y una escritura
que después se sobreescribe no acreditan el paso. Configurar `product` y devolver
`other` no satisface la correlación. Recibir un producto prestado en el constructor,
sin construcción propia observada, tampoco cumple esta variante.

La relación entre inicialización, pasos y finalización describe una estructura;
no demuestra todos los órdenes de llamadas, que la inicialización sea la última
antes del uso, ni ausencia global de aliasing o efectos ocultos. Los métodos que
transforman entradas mediante map, closures o factories no resueltas requieren
otros modelos. No hay garantía de ownership, typestate ni igualdad de
instanciaciones genéricas. Las ambigüedades Builder/Memento anteriores permanecen.

Se añadieron 171 pruebas de Builder, 24 de anotaciones/inicializadores Rust y uso
público de copias, 20 del pase de miembros y tres consultas ejecutables de la guía.
Son fixtures de parsing, enlace y búsqueda: no se compilan ni ejecutan como
programas de los seis lenguajes.
