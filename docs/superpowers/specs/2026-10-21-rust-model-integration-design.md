# M2: adquisición e integración nativa de modelos

Autoridad: contrato general y contrato M2 aprobados. El usuario autorizó terminar
toda la migración con ejecución nativa, conservar los originales y continuar sin
confirmaciones. Este documento concreta el siguiente tramo; no declara M2
aceptada. La implementación comienza después de cerrar y revisar el plan de
transformers. Su preparación documental puede avanzar mientras corren gates
inmutables del plan anterior.

## Propósito

Los encoders nativos ya tienen contratos propios de inferencia. Falta que un
consumidor pueda seleccionar el perfil existente, obtener sus datos fijados y
usar el encoder correcto sin conocer los detalles de cada backend ni ejecutar
Python. Una instalación con cache vacío debe poder preparar únicamente datos
públicos; una ejecución offline debe fallar claramente si faltan datos.

El resultado mantiene separados tres hechos: la identidad del espacio anterior,
los artefactos que lo acreditan y el runtime nativo que realmente se ejecutó.
Conservar la dimensión sin conservar esos tres hechos no acredita compatibilidad.

## Diseño y alternativas

Se compone el registro existente con un cache de artefactos, un transporte HTTP
nativo y una fábrica perezosa. Se reutilizan `ModelAssets`, las verificaciones
streaming y los encoders actuales. El cache publica un snapshot completo mediante
rename dentro del mismo filesystem. La fábrica coordina selección y preparación;
cada backend sigue siendo dueño de tokenización, lotes, dispositivos y errores.

Mantener descargas en scripts Python dejaría incompleta la instalación nativa.
Introducir otro SDK de modelos duplicaría el registro y podría cambiar pooling o
revisiones. Usar el transporte `ureq` ya fijado, con TLS explícito, conserva la
implementación matemática acreditada y concentra la variación de red en un dueño.

## Conceptos y uso

| Concepto | Responsabilidad |
| --- | --- |
| `ArtifactCache` | Resolver o publicar datos completos y verificados bajo un root explícito |
| `ArtifactTransport` | Obtener un stream de un artefacto público fijado, sin decidir su identidad |
| `PublicModelTransport` | Implementar HTTPS y sus límites sin credenciales ni código remoto |
| `EncoderSpec` | Validar la configuración serializable original del encoder |
| `LegacyRuntimeIdentity` | Declarar las versiones originales que identifican un espacio compatible |
| `RetrievalProfile` | Conservar configuración, serialización y hashes existentes, sin ejecutar ranking |
| `ModelCatalog` | Resolver nombres, revisiones y roles a registros ya acreditados |
| `ModelFactory` | Crear un dueño perezoso del encoder o juez solicitado |
| `ManagedEncoder` | Coordinar una inicialización y exponer el encoder a consumidores |

Uso orientativo, a concretar con firmas exactas en el plan:

```rust,ignore
let profile = RetrievalProfile::from_json(saved_profile)?;
let compatibility = LegacyRuntimeIdentity::from_json(saved_compatibility)?;
let factory = ModelFactory::new(catalog, cache, prepared_native_resources);
let encoder = factory.encoder(&profile.behavior, &compatibility)?;
assert!(!encoder.is_prepared()?);
let vector = encoder.embed_query("¿Dónde se guarda la configuración?")?;
```

Las rutas de SDK, módulos y archivos incluidos son entradas explícitas. Declarar
la fábrica o consultar `status` no descarga ni carga bibliotecas opcionales.
Los encoders `provided` exigen inyección explícita; no se convierten en un modelo
por defecto. La selección histórica por nombre conserva Potion, tablas Ken,
FastEmbed y transformers registrados. Un nombre o arquitectura desconocidos
produce un error identificable, sin ejecutar código remoto ni inventar un alias.

## Adquisición y propiedad

El destino es `cache_root/models/<assets.fingerprint()>/<revision>`; no se usan
componentes del identificador del modelo como rutas locales. Los nombres de
artefactos pasan la validación existente de `ModelAssets`. Un staging privado
0700 y archivos creados exclusivamente contienen la descarga hasta acreditar
todos los tamaños y SHA-256. Se mantienen buffers de 64 KiB, se rechaza el primer
byte que supera el tamaño declarado y se sincronizan archivos/directorios antes
de publicar. Una carrera verifica el destino completo del ganador. Un snapshot
existente corrupto devuelve error y permanece disponible para diagnóstico.

Offline no construye ni invoca el transporte. Un snapshot prestado de HF admite
los symlinks de blobs que el verificador ya soporta; nunca se elimina ni se
reescribe. Sólo se retira el staging que creó la operación. Una interrupción,
respuesta incompleta, digest incorrecto o fallo de escritura nunca publica éxito.

HTTPS usa únicamente el host público HF y redirects HTTPS de descarga; no envía
tokens, cookies ni autorización y no lee credenciales de HF. No admite URL de
usuario como parte del registro. Limita redirects a 10, conexión a 15 segundos,
inactividad de lectura a 60 segundos y tiempo total por artefacto a 3600 segundos.
Pruebas de transporte usan un servidor local explícito de pruebas, sin debilitar
la política del transporte público. La preparación de fuentes sucede fuera de
los plazos de inferencia; el tamaño total y el espacio libre se verifican antes
de empezar cada modelo.

## Compatibilidad de perfiles

Se porta la configuración de `src/ken/retrieval/profile.py`, incluidos
`JointRanking`, `EvidenceRanking` y `ContextualRetrieval`, sus defaults y errores.
La serialización omite `evidence` y `contextual` ausentes y `view_model` ausente
exactamente como el original. Conserva representación 3; representación 2 sólo
se acepta mediante la opción explícita de upgrade que ya existe.

Los hashes conservan JSON Python ordenado, espacios y escape ASCII. `EncoderSpec`
incluye backend, dtype, longitud, batch y revisión de 40 o 64 hexadecimales. Los
identificadores `key`, `tokenizer_revision`, `vector_revision` y `fingerprint`
usan versiones originales declaradas, nunca paquetes Python ficticiamente
instalados. Cambiar esas versiones cambia la identidad. Un recibo de equivalencia
debe acreditar el runtime original declarado y el backend nativo correspondiente
antes de reutilizar un espacio. No se escribe ni actualiza un pin existente para
hacerlo coincidir. El cálculo de hashes no requiere cargar modelos ni red.

## Integración de backends

La fábrica delega a los encoders acreditados. Una vez elegida la familia, no
reintenta otra familia si falla la carga. El propio backend conserva su regla
de degradación CPU. Los adaptadores de Potion y NPZ incorporan su carga perezosa
original alrededor de las implementaciones matemáticas actuales. Cada familia
mantiene su regla observada para dimensión, conteo y lotes vacíos; no se aplica
una regla uniforme que altere contratos distintos.

Las preparaciones derivadas de Ettin y traducción consumen el snapshot resuelto
y usan sus compiladores Rust existentes. Contextual, reranker, expansión y juez
conservan sus interfaces propias: no se fuerza un juez a ser un encoder.
Selección de proyecto usa `ModelPolicy` y los hechos de almacenamiento existentes.
La primera integración de búsqueda/indexación pertenece a M3/M4.

## Aceptación y eficiencia de verificación

1. Oráculo original independiente de configuraciones y hashes: defaults,
   Unicode, revisiones inválidas, todos los subperfiles, omisiones y upgrades.
2. Cache real: descarga acotada, offline sin red, reuso con rehash, corrupción,
   interrupción, publicación concurrente y conservación de fuentes prestadas.
3. Transporte nativo probado contra servidor local y datos HF públicos fijados;
   el ejecutable se mueve fuera del checkout, sin Python en PATH, con auditoría
   de dependencias y ambas syscalls de exec en Linux.
4. Llamadas públicas a la fábrica para cada familia; resultados y errores se
   comparan con los adaptadores ya acreditados. No se repite toda la matriz
   neuronal cuando sus fuentes matemáticas, módulos y hosts no cambiaron.
5. Pruebas Rust/fmt/clippy, originales intactos, suite Python completa al cierre,
   gates de almacenamiento previos y evidencia de ambos sistemas. Cada resultado
   distingue inferencia acreditada previamente de nueva integración observada.
6. Una revisión fresca del plan completo y una reparación TDD de hallazgos
   importantes/críticos. Minors se documentan. M2 sólo se cierra si todos sus
   planes, incluida esta integración, están aceptados; después continúa M3.

Autorrevisión: las operaciones de red pertenecen al transporte, publicación al
cache, identidad al perfil y decisiones numéricas a cada backend. No se cambian
fuentes originales, reglas de búsqueda ni formatos de almacenamiento en este
tramo. No se consideran acreditados modelos arbitrarios fuera del inventario.
