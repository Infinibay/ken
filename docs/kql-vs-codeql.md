# KQL frente a CodeQL: evaluación técnica

Estado comparado: Ken IR 1.77 / kenql/1, 14 de septiembre de 2026.
Esta es una evaluación de diseño e implementación, no una encuesta de opiniones.
No se ejecutó un benchmark comparativo con CodeQL.

El [rediseño KQL 2](design/kql2/README.md) incorpora la dirección propuesta a
continuación como especificación, sin implementación. Esta comparación sigue
refiriéndose a KQL 1 disponible; capacidades de diseño no cuentan como ventajas
ya implementadas.

## Mi conclusión

Hoy elegiría CodeQL como base para análisis de seguridad complejo. Su ventaja
principal es la infraestructura semántica y de evaluación, no una sintaxis más
agradable. Seguiría desarrollando KQL para búsquedas de arquitectura integradas
en Ken, con roles y variantes comunes entre lenguajes. No lo presentaría como
sustituto equivalente de CodeQL.

| Dimensión | KQL actual | CodeQL | Mi juicio |
|---|---|---|---|
| Lenguaje | Selectores, joins, alternativas, negación acotada, agregaciones, consultas nombradas y caminos de hasta 32 pasos | QL declarativo, tipado, clases/módulos, recursión y evaluación por punto fijo | CodeQL puede expresar análisis que hoy requieren extender el runtime Python de Ken |
| Semántica | Grafo común de hechos fuente más summaries parciales de control/valores | Extractores y bibliotecas semánticas por lenguaje, flujo local/global y taint tracking | CodeQL tiene una base considerablemente más completa para bugs interprocedurales |
| Portabilidad de queries | Una relación común puede unir variantes de Python, Java, Rust, etc. | Las consultas suelen utilizar APIs de bibliotecas específicas de cada lenguaje | Ventaja de diseño de KQL, siempre que la normalización preserve diferencias nativas |
| Catálogo | TOML con roles, variantes y operaciones reutilizables de GoF/arquitectura | Queries, bibliotecas, suites y packs versionados personalizables | La comodidad específica para arquitectura puede diferenciarnos; reutilización y archivos declarativos no son exclusividades |
| Evaluación | Índices por relación/extremos/atributos, elección de joins, memoización de named queries y presupuestos explícitos | Motor especializado, planes/intermedios cacheados, packs precompilados y opciones de evaluación | No hay evidencia para afirmar que Ken sea globalmente más rápido |
| Incertidumbre | Estados de cobertura, modalidades y resultados incompletos explícitos; ausencia no siempre permite negación | Análisis con límites documentados en resolución dinámica, aliases y bibliotecas externas | Me gusta hacer esos límites visibles en KQL; eso no reemplaza análisis más preciso |

Los hechos sobre QL se apoyan en su [referencia del lenguaje](https://codeql.github.com/docs/ql-language-reference/about-the-ql-language/)
y [recursión](https://codeql.github.com/docs/ql-language-reference/recursion/).
La comparación de flujo se apoya en [el modelo local/global y taint tracking](https://codeql.github.com/docs/writing-codeql-queries/about-data-flow-analysis/).
La distribución y evaluación están documentadas en
[packs](https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-query-packs)
y [opciones de caché de la CLI](https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-cli-manual/query-run).

## Ventajas que no atribuiría a Ken sin medir

CodeQL no exige siempre compilar el proyecto: actualmente C/C++, C#, Java y
Rust tienen opciones sin build. También dispone de análisis incremental.
Por lo tanto, ni “no requiere build”, ni “tiene caché”, ni “se actualiza
incrementalmente” bastan para diferenciar Ken.
[Modos de extracción](https://docs.github.com/en/code-security/concepts/code-scanning/codeql/codeql-for-compiled-languages),
[análisis incremental](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/incremental-analysis).

Tampoco atribuiría a Ken mayor cobertura de lenguajes. CodeQL incluye, entre
otros, Kotlin, Swift, Ruby y Rust; Rust ya no es una preview. El catálogo
estructural de Ken anuncia ocho lenguajes, con alcance distinto por variante.
[Lenguajes y frameworks de CodeQL](https://codeql.github.com/docs/codeql-overview/supported-languages-and-frameworks/).

Los resultados TP/TN/FP/FN del catálogo de Ken miden sus propios oráculos.
No prueban superioridad frente a CodeQL: no implementamos allí queries
equivalentes y CodeQL no debe evaluarse suponiendo que su catálogo de seguridad
incluye automáticamente nuestros patrones arquitectónicos.

## El riesgo principal de nuestro diseño

Una consulta puede encontrar un encoder, un transporte y un decoder sin
demostrar que comparten el mismo valor. También puede encontrar asignaciones
históricas que una escritura posterior invalida. Esos son problemas del contrato
del IR y del análisis, no de elegir palabras más legibles para KQL.

Mi prioridad sería:

1. Unificar procedencia por definición, identidad de bindings, escrituras y
   retornos, incluyendo miembros de registros y aliases.
2. Hacer explícitas las garantías de control: camino posible, orden lineal,
   dominancia y preservación en todos los caminos son propiedades diferentes.
3. Construir operaciones de catálogo sobre ese núcleo común; evitar que cada
   patrón necesite una relación especial desconectada del resto del modelo.
4. Ampliar flujo interprocedural y modelos de APIs sólo con contrastes que
   demuestren tanto aceptación válida como rechazo de testigos desconectados.
5. Evaluar Ken y CodeQL con queries equivalentes, las mismas fuentes y oráculos,
   separando extracción, consulta fría/caliente, memoria, TP/TN y errores.

Para esa comparación empezaría por Builder, Proxy remoto, Memento, Observer y
Factory con consumo posterior: fuerzan a relacionar construcción, parámetros,
retornos, aliases y llamadas. Medir sólo coincidencias por nombre o estructura
de clases daría una comparación poco útil.

## Diferencias concretas de expresividad

«No podemos» significa aquí «no puede escribirlo un usuario en KQL actual sin
extender el runtime de Ken». Se distingue el lenguaje QL de las bibliotecas
semánticas de CodeQL. Los ejemplos QL se contrastaron con la documentación de
las APIs, pero no se compilaron ni ejecutaron localmente con CodeQL.

### 1. Relaciones recursivas definidas por el usuario

Buscar una ruta de llamadas sin elegir una profundidad máxima en la consulta:

```ql
import java

predicate reaches(Callable caller, Callable target) {
  caller.polyCalls(target)
  or
  exists(Callable intermediate |
    caller.polyCalls(intermediate) and reaches(intermediate, target)
  )
}

from Callable entry, Callable target
where
  entry.hasName("controller") and target.hasName("save") and
  reaches(entry, target)
select entry, target
```

Esto calcula alcanzabilidad en el modelo de llamadas posibles, no demuestra que
el programa ejecute ese camino. `polyCalls` contempla destinos por sobrescritura.
KQL admite caminos de hasta 32 pasos y dependencias acíclicas entre consultas
nombradas; no permite definir esta relación recursiva. Aumentar el límite de
caminos no proporcionaría recursión general. QL sigue sujeto a presupuestos de
recursos y restricciones sobre qué recursiones son válidas.
[Recursión](https://codeql.github.com/docs/ql-language-reference/recursion/),
[grafo de llamadas Java](https://codeql.github.com/docs/codeql-language-guides/navigating-the-call-graph/).

### 2. Calcular valores, agregarlos y devolver resultados derivados

Ejemplo: contar destinos de llamada distintos por callable y devolver además una
puntuación calculada. El cuadrado es una fórmula ilustrativa, no una métrica de
calidad recomendada.

```ql
import java

from Callable caller, int destinations
where destinations = count(Callable target | caller.polyCalls(target))
select caller, destinations, destinations * destinations
```

QL ofrece además `sum`, `avg`, `min`, `max`, concatenaciones y ordenamiento.
KQL tiene `count distinct $role >= N { ... }` como condición, pero no un lenguaje
general de agregaciones que produzcan valores, aritmética y columnas calculadas.
Esto importa para resumir directorios, priorizar candidatos o calcular medidas
arquitectónicas dentro de la consulta, en vez de hacerlo después en Python.
[Expresiones y agregaciones](https://codeql.github.com/docs/ql-language-reference/expressions/).

### 3. Seguimiento global de datos transformados

```javascript
function decorate(value) { return "run " + value; }
function dispatch(value) { executeCommand(decorate(value)); }
dispatch(readUserInput());
```

Definiendo explícitamente esas APIs como origen y destino, CodeQL permite
configurar un análisis `TaintTracking::Global<Config>` que siga influencia a
través de funciones y transformaciones. No basta buscar el mismo identificador:
la concatenación cambia el valor y los parámetros viven en ámbitos diferentes.
KQL dispone de relaciones de flujo parciales, pero no de un marco global
equivalente configurable por el autor de la consulta. La precisión de CodeQL
también depende de los modelos y de la resolución; los nombres del ejemplo por
sí solos no prueban una vulnerabilidad.
[Biblioteca de flujo para JavaScript](https://codeql.github.com/docs/codeql-language-guides/data-flow-cheat-sheet-for-javascript/).

### 4. Propagar estados y validaciones parciales

```javascript
const envelope = JSON.parse(input);
if (envelope !== null) {
  const message = envelope.message;
  consume(message.length);
}
```

Comprobar `envelope` no acredita que `message` sea no nulo. Una consulta puede
necesitar conservar la procedencia JSON después del chequeo y volver a atribuir
posible nulidad al leer un miembro. CodeQL ofrece `StateConfigSig` y
`GlobalWithState`, con estados, transiciones y barreras definidos por la consulta.
Ken no ofrece hoy ese marco general. Lo mismo sería útil para describir fases
de un Builder o propiedades de un snapshot, aunque tales análisis necesitarían
sus propios modelos; no aparecen automáticamente por adoptar esta API.
[Estados de flujo](https://codeql.github.com/docs/codeql-language-guides/using-flow-labels-for-precise-data-flow-analysis/).

### 5. Parametrizar un algoritmo de análisis con otras relaciones

```ql
module RequestFlow = TaintTracking::Global<RequestConfig>;
module SnapshotFlow = DataFlow::Global<SnapshotConfig>;
```

Este fragmento requiere definir/importar las configuraciones. Ilustra la
instanciación de bibliotecas con contratos de orígenes, destinos, pasos y
barreras. En KQL podemos llamar consultas nombradas, pero no pasar así un
conjunto de relaciones a un algoritmo genérico de análisis. La diferencia es
abstracción de bibliotecas, además de reutilizar fragmentos de búsqueda.
[Módulos](https://codeql.github.com/docs/ql-language-reference/modules/).

No incluiría negación, regex, búsquedas de llamadas o reutilización simple como
capacidades exclusivas de CodeQL: KQL ya tiene mecanismos para ellas. Tampoco
consideraría `forall` una diferencia fundamental aislada, porque ciertas
propiedades universales se pueden expresar como ausencia de contraejemplos;
para hacerlo de forma fiable importa que el ámbito esté cerrado y completo.

## Dirección propuesta para la sintaxis de Ken

Prefiero un núcleo inspirado en QL: predicados tipados, expresiones componibles,
módulos y recursión controlada. La sintaxis actual acumuló formas específicas
para roles, relaciones, caminos y operaciones; esa diversidad aumenta el coste
de escribir y revisar un algoritmo completo. Esto es una recomendación de
diseño, no una migración implementada.

Ejemplo de API **propuesta para Ken, no QL estándar ni KQL ejecutable hoy**:

```ql
predicate facadeOperation(Type facade, Callable operation) {
  operation.getDeclaringType() = facade and
  exists(Field left, Field right |
    left.getDeclaringType() = facade and
    right.getDeclaringType() = facade and
    left.getType() != right.getType() and
    operation.delegatesTo(left) and
    operation.delegatesTo(right)
  )
}

from Type facade, Callable operation
where facadeOperation(facade, operation)
select facade, operation
```

El ejemplo conserva el contrato estructural limitado de la consulta original:
no demuestra por sí mismo que se simplifique una API. Aquí `=` es una condición
relacional, no una asignación del programa analizado. `delegatesTo` debe tener
un contrato semántico publicado; una notación más agradable no lo vuelve más
preciso. Conservaría el grafo común entre lenguajes y los oráculos del catálogo,
y separaría la migración de sintaxis de los cambios en análisis y evaluación.
