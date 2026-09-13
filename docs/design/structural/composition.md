# Composición: consultas que dependen de consultas nombradas

Estado: contrato de diseño. El núcleo de composición mediante `match`, exports,
dependencias y evidencia está implementado; otras extensiones de este documento
siguen siendo propuestas. La [guía operativa](../../structural-queries.md) describe
la sintaxis disponible y sus límites.
Volver al [índice](README.md).

## 1. Motivación

Una consulta de flujo de productos no debería copiar la definición de Factory
Method, ni una regla de Builder defectuoso copiar todas las formas de Builder.
Debe poder exigir que algunos de sus roles participen en una coincidencia de otra
consulta y continuar buscando desde esos mismos roles.

La composición es relacional: una consulta nombrada expone una relación de bindings
con evidencia. Un patrón no se transforma en un tipo de programación ficticio.
Esto permite usar la misma función para consultas de uso, arquitectura y bugs.

## 2. Sintaxis propuesta

```kenql
query product_flow {
  match "gof.factory-method"(
    factory: $factory,
    product: $product
  ) as $factory_match;

  call() as $creation;
  require $creation TARGET $factory;
  require $creation RESULT $result;
  path $result VALUE_FLOW{0,6} $consumed as $flow;
  call() as $consumer;
  require $consumer ARGUMENT $argument;
  require $argument VALUE $consumed;
  emit $factory, $creation, $consumer, $flow;
}
```

`factory` y `product` son nombres públicos de roles de la consulta referenciada;
`$factory` y `$product` son bindings locales. Se conectan por identidad y en la
**misma fila** de resultado. No vale tomar la factory de una coincidencia y el
producto de otra. `$factory_match` es un handle de evidencia: permite explicación
y trazabilidad, no es una entidad del programa.

El rango `{0,6}` admite que el resultado sea directamente un argumento del
consumidor. `{1,6}` exige alguna transferencia intermedia. Se explicita la ocurrencia
de argumento porque ARGUMENT no apunta indistintamente a valor y parámetro.

`match` no quiere decir «ejecutar un script externo»: referencia una consulta
registrada y validada del mismo lenguaje. Los nombres completos van entre comillas
para admitir namespaces y guiones sin ambigüedad con operadores.

## 3. Interfaz pública de una consulta

Una consulta reutilizable proyecta nombres estables:

```kenql
query returns_product {
  callable() as $maker;
  require $maker RETURNS_NEW $type;
  emit factory = $maker, product = $type;
}
```

Esta consulta solo detecta construcción con retorno; su ID podría ser
`construction.returns-product`, sin atribuirle el significado de Factory Method.
Una regla más precisa puede usarla y agregar override, slot y uso del producto.
Los aliases internos pueden cambiar sin romper consumidores de `factory` y
`product`. `emit $factory` es azúcar de `emit factory = $factory`.

El archivo declarativo registra el contrato inferido/verificado:

```toml
id = "construction.returns-product"
query_language = "kenql/draft-2"

[exports.factory]
kinds = ["callable"]
required = true

[exports.product]
kinds = ["type_decl"]
required = true
```

Si la consulta y esa declaración discrepan, hay un error de biblioteca. Los roles
son comprobados por el compilador; no se confía ciegamente en el TOML.

Una referencia puede enlazar todos o algunos roles. Los omitidos son existenciales:
`match "construction.returns-product"(factory: $f);` exige algún producto. No
genera una fila visible por cada rol interno no solicitado. La evidencia puede
conservar varios testigos agrupados para explicar alternativas.

Un rol ya ligado restringe la consulta; uno nuevo se liga desde sus resultados.
El planificador puede propagar restricciones o usar resultados materializados,
pero ambas estrategias deben devolver los mismos bindings y conocimiento.

## 4. Variable cuyo tipo participa en un patrón

El ejemplo del usuario admite dos intenciones distintas. Para una función usada
como factory basta ligar el rol callable. Para una variable que contiene un objeto
factory hay que recorrer almacenamiento, valor y tipo:

```kenql
query factory_objects {
  variable(name: /^user_factory$/) as $storage;
  require $storage STORES_VALUE $value;
  require $value INSTANCE_OF $type;
  match "gof.factory-method"(creator: $type) as $factory_match;
  emit variable = $storage, creator = $type;
}
```

La relación anterior describe alguna escritura al storage. Para preguntar por el
objeto en un punto de uso se selecciona la operación `load` y su resultado, con
análisis def-use; no se mezclan todos los valores históricos de la variable.

Si el runtime type solo es posible, la coincidencia debe conservar esa modalidad.
Una anotación `Factory` no demuestra que el objeto cumpla el patrón; el patrón
puede no existir aunque la clase se llame así. Una función simple de construcción
puede satisfacer `construction.returns-product` y no `gof.factory-method`.

## 5. Variantes y roles comunes

Un archivo lógico puede contener muchas variantes. `match "gof.iterator"(...)`
consulta la unión de las variantes habilitadas y aplicables. Devuelve evidencia
con los IDs de las variantes satisfechas y deduplica los mismos roles públicos.

Para restringir una variante se propone selector explícito:

```kenql
query generated_iterators {
  match "gof.iterator#generator"(iterator: $iterator) as $proof;
  emit $iterator;
}
```

El carácter `#` está dentro del string y separa patrón de variante; no inicia un
comentario. No se usa el nombre de lenguaje como sustituto del nombre de variante:
Python puede implementar tanto cursor como generador.

Los roles comunes deben tener significado estable. Iterator puede exportar
`iterator: callable | type_decl`, identificando la entidad que implementa el
recorrido. Una consulta consumidora que necesita una callable filtra esa unión o
selecciona la variante adecuada. No se inventa una clase para la variante yield.
Builder exporta `builder`, `product` y `finish`; si una variante no puede demostrar
un producto, no satisface una interfaz que lo exige. Puede ser una regla separada
de forma exploratoria, no un valor inventado para completar el binding.

La metadata de una coincidencia conserva todos los witnesses pertinentes; no se
elimina una variante porque otra obtuvo más puntuación. Severity, tags y score no
son parte de la identidad ni de las condiciones por defecto.

## 6. Uso con negación, alternativas y conteos

```kenql
query factories_with_several_creators {
  type_decl() as $product;
  count distinct $factory >= 2 {
    match "construction.returns-product"(
      factory: $factory,
      product: $product
    );
  };
  emit $product;
}
```

El conteo se correlaciona por producto y cuenta factories distintas, no variantes
ni explicaciones duplicadas. Que dos fábricas existan no demuestra Abstract Factory:
la interpretación de la consulta sigue siendo la que escribió el usuario.

Un `match` puede estar en `optional`, en una rama de `any` o dentro de `not exists`.
La negación necesita que la subconsulta sea completa para ese binding y scope,
incluidas variantes aplicables y dependencias. Cero filas tras timeout no demuestra
que el patrón esté ausente.

Reglas de conocimiento:

- Un testigo confirmado satisface el match existencial, aunque haya otras variantes
  incompletas; la enumeración total puede seguir parcial.
- Si solo hay testigos posibles, la obligación queda unknown en modo estricto.
- Ausencia con una variante aplicable incompleta permanece unknown.
- Variante no aplicable por lenguaje/versiones declarados no es una falla de análisis.
- Biblioteca o ID inexistente, interfaz incompatible o versión ausente es error de
  configuración, no una propiedad desconocida del programa.

## 7. Dependencias, resolución y recursión

El compilador extrae dependencias de cada `match`; la biblioteca puede declararlas
para fijar versiones, pero no existe una segunda lista informal que el motor ignore.
Resolver primero todo el grafo de dependencias, validar exports y después escanear.
Detectar ciclos con cadena legible, por ejemplo `A -> B -> C -> A`.

**Primera versión: DAG de consultas, sin recursión entre queries.** Los caminos
acotados del IR siguen permitidos. Así se pueden componer libremente componentes
reutilizables sin definir todavía semánticas de punto fijo, negación recursiva y
conteos no monotónicos. Admitir recursión sería una decisión posterior explícita.

Los nombres internos se renombran al expandir consultas: `$factory` en una query
no captura accidentalmente una variable del mismo nombre en otra. Solo se conectan
roles a través del contrato público. Una llamada repetida con bindings diferentes
es una instancia lógica distinta, no un estado global mutable.

Bibliotecas locales pueden referenciar consultas distribuidas con Ken. No pueden
sobrescribir IDs silenciosamente ni leer fuera de sus raíces autorizadas. El scope
de búsqueda del usuario se hereda; una dependencia no amplía el scan a otro repo.

## 8. Planificación y caché

Compilar dependencias una vez por versión semántica y schema. Elegir entre inlining,
semi-join para existencia, consulta parametrizada por bindings o materialización
compartida según cardinalidad y reutilización. No ejecutar todo GoF por cada fila
de `product_flow`.

Clave de caché: snapshot, hash transitivo de queries/variantes, modelos semánticos,
proyección relevante, restricciones y modo de evidencia. Cambiar la definición
usada de Factory Method invalida product_flow, incluso si su texto no cambió.
Cambiar la descripción editorial solo invalida presentación.

Presupuesto global para la consulta raíz y sus dependencias; estadísticas por
subconsulta para explicación. Anidamiento no multiplica el tiempo permitido.
Cancelación se propaga. Resultados parciales cacheados conservan alcance/budget y
no se presentan como relaciones cerradas para negación.

## 9. Tests que exige esta capacidad

Bindings parciales/completos; roles equivocados; nombres internos iguales sin
captura; misma factory con varios productos; variantes duplicadas; tipos unión;
negación sobre dependencia incompleta; dependencia inexistente; ciclos; cambio de
query transitiva; ejecución inlined vs materializada; budgets compartidos; misma
consulta invocada con dos bindings; proyección existencial sin duplicación.

Un test clave: dos coincidencias `(factory A, product X)` y `(factory B, product Y)`
no deben permitir `(A,Y)`. Otro: agregar variante yield a Iterator permite nuevos
resultados, sin cambiar el significado de los resultados de cursor.
