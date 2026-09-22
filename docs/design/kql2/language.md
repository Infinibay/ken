# Lenguaje KQL 2

Especificación objetivo; [estado de implementación parcial](implementation-status.md).
[Índice y decisiones](README.md).

## 1. Archivo y declaraciones

```kql2
language "kql/2";
module examples.workers;
import ken.core;

pattern Worker(out TypeDecl $worker, out Callable $work) {
    class $worker {
        field $name { type: string; name: /name/i; visibility: public; }
        field $age { type: integer; visibility: public; }
        method $work {
            name: /^work$/;
            param $task { position: 0; accepts_position: true; }
        }
    }
}

query workers {
    use Worker(worker: $worker, work: $work);
    select $worker, $work;
}
```

Una unidad tiene versión, módulo, imports y declaraciones `pattern`, `predicate`,
`query`, `enum`, `signature` o `model`. Nombres públicos cualificados por módulo.
`pattern` combina estructura y comportamiento. `predicate` define una relación
lógica; sus parámetros no crean un universo infinito. `query` produce una tabla.
Las declaraciones son puras y no acceden a red, archivos, reloj, Python o shell.

Cada parámetro de patrón declara `in` u `out`. `in` debe estar ligado al invocarlo.
`out` puede recibir un rol ya ligado, actuando como restricción de igualdad.
Los parámetros de predicado son relacionales: su seguridad depende de generadores
finitos positivos, no del orden textual. No hay argumentos posicionales en `use`.

## 2. Léxico

UTF-8; identificadores de declaraciones y roles ASCII `[A-Za-z_][A-Za-z0-9_]*`.
Los nombres fuente Unicode se representan como strings, nunca se normalizan para
inferir identidad. Roles con `$`; `_` es un existencial nuevo por aparición.
Comentarios `//` y `/* ... */` no anidados. `;` termina sentencias simples y
propiedades; bloques estructurales no requieren `;`. Espacios y saltos no tienen
semántica. Strings con escapes JSON, números decimales y booleanos.

Regex `/.../ims` sólo en posición de matcher o RHS de `matches`; `/` es división
en expresiones. `\/` representa una barra dentro del patrón. Sin backreferences,
lookaround ni ejecución; contrato regular portable. Máximo 4096 bytes de patrón,
error de compilación al superarlo. El costo total está sujeto al presupuesto.
Las flags no se repiten. Matching busca subcadena; `^...$` exige cadena completa.

El núcleo no acepta palabras alternativas en mayúsculas, `WILL`, `%`, `define`
ni sintaxis KQL 1. Evitar múltiples maneras de escribir una misma obligación en
la primera versión. Los ejemplos conversacionales anteriores son antecedentes.

## 3. Dos sistemas de tipos

**Tipos del buscador:** `Entity`, `Module`, `TypeDecl`, `Callable`, `Field`,
`Parameter`, `Binding`, `Value`, `Object`, `Location`, `Operation`, `Argument`,
`Region`, `Point`, `Fragment`, `Iteration`, `Task`, `Lock`, `TypeRef`, `Scope`,
`CodeNode`, `Declaration`, `Expression`, `Statement`, `ArgumentPack`, `Receiver` y tipos escalares
`String`, `Int`, `Float`, `Bool`. `Parameter` y `Receiver` son subtipos de `Binding`; `Field`
es una declaración, no una ubicación de una instancia. `Option<T>` representa
proyección opcional explícita. `Evidence` no es un valor del programa fuente.

**Tipos del programa fuente**, como datos `TypeRef`:

| Familia | Representación normalizada |
|---|---|
| Básicos | `boolean`, `integer`, `float`, `decimal`, `char`, `string`, `bytes` |
| Colecciones | `array<T>`, `list<T>`, `set<T>`, `map<K,V>`, `tuple<T,...>` |
| Función y nominal | `function<(T,...)->R>`, `nominal($type)`, `generic($type,[T,...])`, `parameter($t)` |
| Indirección | `reference<T>`, `pointer<T>`, `optional<T>`, `union<T,...>` |
| Efectos/tipos compuestos | `iterator<T>`, `async_iterator<T>`, `task<T>` |
| Especiales | `void`, `never`, `null`, `undefined`, `any`, `unknown` |

`int`, `str`, `bool` y `double` no son alias léxicos: se conserva un vocabulario
normalizado y `native_type` para grafías originales. Anchura, signo, encoding,
mutabilidad, ownership y nulabilidad son propiedades separadas, no se pierden.
No se convierte un `char` a `string` ni un `float` a entero por coincidencia.

`any` es el tipo dinámico/top declarado cuando el lenguaje lo tiene. `unknown`
es el tipo fuente explícito equivalente, por ejemplo TypeScript `unknown`.
Información de tipo ausente se consulta con `type_status: unknown`; **no** se
fabrica `TypeRef(unknown)` para un Python sin anotación. `type: _` omite el filtro.

`type: string` exige evidencia de pertenencia a esa familia; `any` ni información
ausente satisfacen eso por defecto. `oneof(string, unknown)` acepta esos dos tipos
fuente, no ausencia de información. Para incluir esa ausencia se usa `either`:

```kql2
either { var $v { type: string; } }
or     { var $v { type_status: unknown; } }
```

El ejemplo es un fragmento de selección estructural. `assignable`, `subtype`,
`same_type` y `instantiates` son predicados de biblioteca distintos. `type: string`
no activa asignabilidad ni duck typing implícitos.

## 4. Capturas y estructura

Selectores: `module_decl`, `type`, `class`, `interface`, `trait`, `field`,
`property`, `callable`, `method`, `function`, `constructor`, `param`, `receiver`, `var`,
`value`, `operation`, `iteration`, `task`, `lock`, `region`, `import_decl`,
`export_decl`. Se añaden `node`, `expression`, `statement` y `constant` según el
[modelo del programa](code-model.md). Cada selector tiene schema de propiedades;
un nombre desconocido es error. `type` selecciona cualquier `TypeDecl`; `class` sólo una clase nativa.
`method` requiere pertenencia a tipo; `function` no equivale a cualquier callable.

El bloque anidado añade relación de pertenencia inmediata: método → parámetro,
tipo → campo/método/constructor, módulo → declaración/import/export. No significa
«aparece en algún descendiente textual». Campos heredados requieren predicado
`member_of`; cuerpos de closures se inspeccionan por su propio callable.

Propiedades registradas mínimas:

| Selector | Propiedades |
|---|---|
| Todos los nodos fuente | `name`, `language`, `path`, `native_kind` cuando apliquen |
| Tipos/campos/callables | `visibility`, `static`, `type`, `type_status`, `native_type` según schema |
| Callable | `async`, `generator`, `return_type`, `return_type_status` |
| Parameter | `position`, `native_position`, `kind`, `accepts_position`, `accepts_name`, `passing`, `default_status`, `type`, `type_status` |
| Binding | `mutable`, `storage`, `scope_kind`, `type`, `type_status` |
| Operation | `kind`, `execution`, `native_kind` |

Propiedades no aplicables a un tipo son error estático. Valor aplicable pero
desconocido produce `unknown`, excepto filtros explícitos de estado. Visibilidad
es `public|protected|private|internal`; convenciones Python se marcan `conventional`
en evidencia y no prueban enforcement. Tipos anónimos no adquieren nombre ficticio.

Un rol repetido exige el mismo ID. Roles diferentes pueden coincidir: escribir
`where $a != $b;` si deben ser diferentes. Igualdad de nombres no unifica roles.
Esto vale incluso para dos selectores `field` hermanos. No hay regla oculta de
distinción por posición textual.

`fields { ... }` y `parameters { ... }` agrupan selectores sin cambiar semántica.
`fields exact { ... }` exige que los campos directos sean exactamente el conjunto
de declaraciones distintas capturadas allí; requiere inventario completo.
`parameters exact` cuenta todos los parámetros ordinarios; excluye el receptor,
sea explícito o implícito en la sintaxis fuente. El selector `receiver` lo captura
aparte conservando su declaración cuando existe. `param` no selecciona receptores.
No se admite `exact` sobre una clase entera: sería ambiguo con herencia/sintetizados.

`type_parameter $t;` liga el nombre de un parámetro genérico de la declaración
envolvente (tipo, clase, interfaz o trait); el IR lo publica como
`BINDS_TYPE_PARAMETER(declaración, nombre)`. El parámetro es un *nombre*, no una
entidad, así que el rol liga esa grafía y `type: parameter($t)` exige que el tipo
declarado del campo o variable **sea** ese mismo parámetro (`TYPE_NAME`). Un
refinamiento puede renombrar su parámetro: se compara la grafía, no la posición.

Para relacionar campo y clase del ejemplo original:

```kql2
type $jobType { name: /^Job$/; }
class $worker {
    field $jobField { type: nominal($jobType); visibility: private; }
}
```

## 5. Ámbitos y composición

Capturas en bloques positivos estructurales son visibles en el patrón envolvente;
su pertenencia queda fijada por el bloque. Capturas en `exists`, `not exists`,
`forall`, `optional`, ramas y cuerpos de iteración son locales salvo salida
explícita. Las variables de patrón no se sombrean: un nuevo binding con el mismo
nombre restringe identidad si el tipo coincide; si no, error.

`either { ... } or { ... }` combina alternativas; sólo escapan roles ligados en
todas las ramas con tipo común compatible. No mezclar testigos de ramas distintas.
`use Name(arg: $role, ...) as $proof;` liga salidas de una única coincidencia;
omitidas sólo salidas (`out`) quedan existenciales. Entradas omitidas son error.
`$proof` es `Evidence` para patrones normales, `Fragment` para patrones que exportan
un fragmento. Internos se renombran higiénicamente. No hay expansión textual.

`optional { ... }` es evidencia adicional. Roles internos no escapan ni filtran
resultados obligatorios; pedir columnas opcionales requiere predicados que devuelvan
`Option<T>`. Evita joins accidentales y usar una captura posiblemente inexistente.

## 6. Predicados y consultas relacionales

```kql2
predicate Reaches(Callable $from, Callable $to) {
    possible_call($from, $to)
    or exists(Callable $mid |
        possible_call($from, $mid) and Reaches($mid, $to)
    )
}

query public_reach {
    from Callable $entry, Callable $target;
    where public($entry) and Reaches($entry, $target);
    select $entry, $target;
}
```

`possible_call` describe posibles destinos en el modelo, no ejecución real.
Predicados tienen nombre, firma y fórmula sin `;` interior. No aceptan selectores
BODY directamente: reutilizan patrones mediante relación `matches(Name, ...args)`
con argumentos nombrados y salidas explícitas. `matches` no ejecuta otro escaneo.
Sus dependencias participan del mismo grafo de evaluación y de la estratificación.

Fórmulas: `and`, `or`, `not`, comparaciones, `exists(T $x | f)` y
`forall(T $x | dominio | propiedad)`. `forall` exige dominio finito completo para
confirmar; sobre dominio vacío completo es verdadero. Añadir `exists` para exigir
al menos un miembro. `not exists { ... }` en patrones tiene las mismas reglas.

Precedencia de expresiones de consulta: postfix/call, unary (`not`, signo), `* / %`, `+ -`, comparaciones
(`== != < <= > >= in matches`), `and`, `or`. Comparaciones no se encadenan.
`=` sólo aparece en captura calculada `bind`, inicialización/assignment BODY y
reglas de transición; igualdad relacional se escribe `==`.

`bind $score = expresión;` liga un valor derivado inmutable, no una variable del
programa fuente. El nombre debe estar fresco; rechazar reasignación de `bind`.
`from` declara dominios finitos del grafo o enums; no genera todos los `Int/String`.

Acceso `$entity.name`, `$operation.before` o `$entity.accessor(...)` es lectura de
propiedades/accesores registrados y tipados de la biblioteca, no ejecución de
métodos fuente. Acceso desconocido es error; datos no resueltos propagan unknown.
No hay reflexión ni acceso a atributos internos del runtime. Las firmas de
accesores deben declarar si son totales o retornan `Option<T>`.

```kql2
query dependency_counts {
    from Callable $caller;
    bind $count = count(Callable $callee | possible_call($caller, $callee) | $callee);
    bind $score = $count * $count;
    where $count >= 2;
    select owner($caller) as owner_module, $caller, $count, $score;
    order by $score desc, stable_id($caller) asc;
}
```

Agregaciones `count`, `sum`, `min`, `max`, `avg` sobre conjuntos de valores
proyectados distintos; contar eventos distintos requiere proyectar IDs de eventos.
`count`/`sum` del conjunto vacío = 0; `min`/`max`/`avg` = `Option.none`.
`sum` sólo numéricos; para valores repetidos asociados a eventos usar
`sum_by(Event $e | f | numeric_expression)`, que suma una vez por tupla de dominio,
no elimina contribuciones iguales. `count` retorna `Int`; `avg` `Option<Float>`.
División por cero es error de evaluación de la query, no simplemente fila ausente.

`select` deduplica tuplas; evidencia alternativa se conserva aparte. No garantiza
orden sin `order by`. `limit N` posterior al orden limita presentación y se marca
`results_truncated`; no es un presupuesto que certifique exhaustividad.

## 7. Módulos y parametrización

`enum State { fresh, used, closed }` define un dominio finito del buscador.
`signature` declara predicados requeridos; `model` proporciona definiciones con
esas firmas. Un patrón genérico recibe modelos: `pattern Walk<M: FlowModel>(...)`.
Se instancia con `use Walk<UserInput>(...)`. No recibe código host ni expresiones
arbitrarias; los argumentos de tipo/modelo se resuelven al compilar la biblioteca.
La firma determina qué relaciones son necesarias y sus tipos. No hay herencia
múltiple ni dispatch dinámico de modelos en la revisión 0.1.

Exports son explícitos por manifiesto del paquete; import no ejecuta queries.
Resolución por módulo y versión de paquete fijada en lockfile. Colisiones, ciclos
de imports de inicialización (no existen inicializadores) y dependencias lógicas
se tratan por separado: imports pueden ser cíclicos si las firmas se resuelven;
el grafo lógico debe satisfacer las reglas de [evaluación](ir-and-evaluation.md).


## 8. Alternativas y condiciones sobre metadatos

Además de `either { ... } or { ... }`, se admite `{ ... } or { ... }` con la misma
semántica y alcance. Son alternativas de una coincidencia, no una combinación de
hechos tomados de varias ramas. El texto de cada bloque contiene constraints; las
alternativas en BODY contienen instrucciones de búsqueda de comportamiento.

`when formula { ... } else when formula { ... } else { ... }` selecciona ramas
mediante expresiones de consulta. `if` dentro de BODY sigue describiendo un `if`
del código fuente. El sujeto es explícito: `$base.language`, `$base.path`, etc.
No hay un objeto global `base` implícito ni evaluación de código host.

```kql2
query adapters {
    class $base {
        when $base.language in ["java", "csharp"] {
            method $method { name: "execute"; }
        } else when in_directory($base, "abc") {
            { method $method { name: "work"; } }
            or { method $method { name: "run"; } }
        } else {
            method $method { name: "process"; }
        }
    }
    select $base, $method;
}
```

`in_directory(Entity, String) -> Bool` opera sobre componentes del directorio
relativo al proyecto, excluyendo el nombre del archivo. Una ruta desconocida
produce unknown. No acepta matches parciales de un componente. Combinar con
`and`/`or`, igualdad de path o `matches` para otras condiciones.

La rama `else` exige falsedad de la condición anterior, no ausencia de prueba de
verdad. Un guard desconocido no activa else por defecto. Sin else, la rama falsa
no añade restricciones; una captura introducida sólo por la rama verdadera no
puede escapar. Las capturas proyectadas deben estar ligadas en todas las ramas.
El backend puede descartar ramas por metadatos conocidos antes de ejecutar sus
joins; nunca interpretar un lenguaje sin frontend como prueba negativa.

`step` se trata como palabra contextual para admitir firmas como
`predicate step(Value $a, Value $b)`; dentro del bloque C-style `for`, sigue siendo
la etiqueta de actualización. Esta excepción resuelve los ejemplos de FlowModel.
