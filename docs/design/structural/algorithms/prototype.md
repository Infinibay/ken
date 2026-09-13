# Prototype: del algoritmo en palabras al IR

El [patrón ejecutable](../../../../src/ken/structural/patterns/prototype.toml)
reúne construcción explícita, copia de campos y `Clone` derivado de Rust. Esas
variantes tienen evidencias distintas: un argumento del constructor no prueba
por sí solo que el objeto retornado conserve su contenido.

## Algoritmo en palabras

1. Recibir o seleccionar una instancia que sirve como prototipo.
2. Leer el estado que la política de copia declara relevante.
3. Obtener una nueva instancia o representación independiente en el nivel que
   exige esa política.
4. Poblarla con estado derivado del prototipo: copiar valores, compartir recursos
   permitidos y duplicar las partes que deben ser independientes.
5. Devolver esa instancia, preservando su identidad y el estado copiado hasta el
   retorno. Crear una copia y devolver el original no cumple esta variante.

El contrato puede permitir resetear contadores, regenerar IDs o compartir assets.
No exigir igualdad de todos los campos ni copia profunda universal. Un método
que comparte una referencia a un objeto inmutable puede cumplir perfectamente la
política; uno que accidentalmente comparte estado mutable puede violar un
refinamiento de independencia.

## Identidades y políticas

| Elemento | Requisito |
| --- | --- |
| Prototipo | El estado leído proviene de la instancia seleccionada |
| Nueva instancia | Es el resultado de la creación usada por la copia, no otra creación |
| Payload | Existe correspondencia entre origen y estado retenido según la política |
| Valor retornado | Es esa instancia; aliases locales pueden conservar su identidad |
| Campos compartidos | Su sharing está permitido o es desconocido, no inventar una copia |
| Campos independientes | Mutaciones admitidas sobre la copia no afectan al original |
| Original | No se modifica cuando el contrato promete una operación de copia pura |

“Mis mismos valores” no equivale a “mi misma identidad”. Dos contenedores pueden
ser distintos pero compartir elementos; dos wrappers pueden apuntar al mismo
recurso. Una variante funcional sobre valores inmutables tampoco debe modelarse
como un objeto mutable nuevo si el lenguaje no promete esa identidad observable.
La query explícita actual sí busca construcción de un objeto nominal nuevo.

## IR objetivo

Notación de diseño; las políticas `capture`/`copy_region` no son opcodes ya
implementados ni una sintaxis KenQL disponible:

```text
function duplicate(%original) {
  %source_address = field.addr %original [field = state]
  %source = memory.load %source_address
  %payload = capture %source [policy = shallow]
  %copy = construct @Product(%payload)
  return %copy
}

function Product.init(%self, %input) {
  %target = field.addr %self [field = state]
  memory.store %target, %input
}
```

La representación actual dispone de valores, direcciones, loads/stores, calls y
constructs. Falta vincular las operaciones entre métodos para probar una política
de copia concreta: mapear argumentos a parámetros y de éstos a los campos finales,
y correlacionar ese objeto con el retorno del método de copia.

Para inicialización por campos, el mismo contrato tiene otra forma:

```text
%copy = construct @Product()
%source = memory.load (field.addr %original [field = state])
%target = field.addr %copy [field = state]
memory.store %target, %source
return %copy
```

Aquí no se debe requerir que el estado pase al constructor. La variante existente
`field-copy` ya utiliza procedencia del objeto retornado y sus escrituras de campo.
Una llamada que recibe la copia puede invalidar esas garantías, salvo que exista
un resumen de efectos suficiente.

Para una política independiente del array:

```text
%source = memory.load %original.state
%payload = copy_region %source [depth = elements, element_policy = scalar]
%copy = construct @Product(%payload)
return %copy
```

La profundidad depende de los tipos: copiar elementos escalares puede bastar;
copiar referencias de elementos mutables no demuestra independencia transitiva.
Un mero `call clone` debe conservar efectos y semántica desconocidos si no hay
modelo de la implementación real.

## Variantes por lenguaje

| Forma | Lenguajes / ejemplos | Evidencia necesaria |
| --- | --- | --- |
| Constructor explícito | Python, Java, TypeScript | Campo fuente → argumento → payload retenido → resultado |
| Poblar objeto nuevo | Python, JS/TS, Java, C# | Identidad de asignación y escrituras finales del objeto retornado |
| Protocolo de copia | Python `copy`, C# `MemberwiseClone`, Java `clone` | Modelo de protocolo y overrides, profundidad explícita |
| Spread / asignación | JS/TS spread, `Object.assign` | Objeto destino nuevo y semántica de propiedades/getters |
| Constructor de copia | C++ | Selección de constructor, copia/move y miembros compartidos |
| Derivación | Rust `#[derive(Clone)]` | Derive real y destino de método; macro/trait identity sigue limitada |
| Valores compuestos | Go structs, Rust structs | Copiar valor no implica copiar backing arrays, pointers o `Arc` |
| Registro de prototipos | Muchos lenguajes | Lookup selecciona prototipo y la clonación usa ese objeto |

La nueva matriz ensaya Python, Java y TypeScript con construcción explícita. Las
otras formas son requisitos y regresiones previas separadas, no cobertura nueva
atribuible a este documento.

## Ruido, negativos y evidencia

[`test_algorithm_prototype.py`](../../../../tests/structural/test_algorithm_prototype.py)
analiza fuentes completas. El caller asigna estado al prototipo, lo duplica y
modifica el resultado. No se ejecuta el código de los fixtures.

**24 passed, 6 xfailed**, en tres lenguajes:

- 12 positivos: sin ruido, con logging/cálculo antes, después o en ambos puntos.
  El logger sólo recibe un número independiente.
- 9 negativos rechazados: construcción con constante, retorno del original y
  sustitución de la copia por otro objeto antes del retorno.
- 3 positivos confirman que compartir un array es una política shallow válida
  para el patrón genérico.
- 3 gaps: el constructor ignora el argumento capturado y fija estado constante.
  El caller había cambiado el estado original, por lo que la copia pierde ese
  estado. La firma sigue produciendo un match.
- 3 expectativas pendientes de un contrato **más fuerte** de independencia:
  compartir el array permite que editar el resultado modifique el original.
  No constituyen negativos universales de Prototype.

Los seis pendientes son `xfail(strict=True)` y no se contabilizan como true
negatives. Los tests de sharing positivo y de independencia pendiente usan el
mismo programa intencionalmente: la diferencia está en la propiedad buscada, que
no debe imponerse a toda la categoría GoF.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_prototype.py
```

## Gaps del IR y del buscador

`explicit-copy` demuestra un argumento leído de un campo y una construcción del
mismo tipo retornada. No verifica el destino de ese argumento dentro del
constructor; un constructor que lo descarta pasa. Tampoco distingue todo Prototype
de un constructor de sucesores que conserva parte del estado.

No se cambió el TOML en esta revisión. Exigir sin alternativas
`FINAL_FIELD_INPUT` para toda copia explícita descartaría constructores que
copian/normalizan la entrada mediante llamadas o representaciones diferentes.
Hace falta una variante con transferencia directa probada y un contrato común
que pueda aceptar transformaciones modeladas; simplemente exigir el nombre
`clone` no resuelve la semántica.

Mejoras necesarias:

1. Expresar el mapa de campos seleccionados y sus políticas de compartir/copiar,
   sin exigir todos los campos de un objeto.
2. Seguir argumentos y valores retornados a través de constructores y operaciones
   de copia modeladas; separar evidencia de transformación de identidad.
3. Propagar aliases y efectos de memoria para refinamientos de independencia o de
   preservación del original. Mantener `unknown` ante efectos no modelados.
4. Hacer componibles esas propiedades con la firma GoF mediante named queries:
   Prototype candidato, transferencia probada e independencia probada son
   búsquedas relacionadas con diferente fuerza, no tres algoritmos inconexos.
