# Catálogo declarativo: un archivo por patrón

Estado: propuesta de formato. Volver al [índice](README.md).

## Fuente de verdad y ubicación

Los 23 archivos de [catalog](catalog/) son **borradores documentales TOML**, uno por
patrón. Cada archivo reúne variantes con lenguajes aplicables, capacidades y planes
de grafo. `status = "design"` significa que no debe ejecutarse como regla lista.
El campo `graph_requirements` conserva obligaciones aún no convertidas en KenQL.
`query_draft`, cuando aparece, ilustra sintaxis propuesta y no habilita la variante.

La distribución final usaría `patterns/gof/<id>.toml` o un directorio de recursos
equivalente dentro del paquete Ken; no una lista de strings en un módulo Python.
La documentación por patrón y los fixtures pueden estar separados y enlazados.
El motor no necesita importar código para conocer los patrones.

TOML se propone por ser legible, permitir strings multilínea y tener parser en la
biblioteca estándar de Python objetivo. No es una dependencia del modelo: otro
formato podría serializar el mismo schema. Se elige uno para evitar dos parsers y
ambigüedades de tipos en la primera entrega.

## Archivo final previsto

```toml
schema = "ken-rule/2"
id = "gof.iterator"
name = "Iterator"
collections = ["gof"]
tags = ["behavioral", "iteration"]
claim = "structural-signature"

[exports.iterator]
kinds = ["callable", "type_decl"]
required = true

[[variants]]
id = "generator"
languages = ["python", "javascript", "typescript", "csharp"]
requires = ["generator_lowering"]
claim = "generator-shape"
query = '''
query generator_shape {
  callable(generator: true) as $iterator;
  operation(kind: yield) as $suspend;
  require $iterator HAS_OPERATION $suspend;
  emit iterator = $iterator;
}
'''
fixtures = ["fixtures/iterator/generator/manifest.toml"]

[[variants]]
id = "explicit-cursor"
languages = ["python", "javascript", "typescript", "java", "csharp", "cpp", "rust"]
status = "design"
# No habilitar hasta tener consulta, protocolos y fixtures completas.
```

La variante generadora afirma presencia de generación; no prueba progreso ni
agotamiento. Una biblioteca puede exigir una variante más precisa. El generador
delegado se registra por separado; el archivo del patrón los reúne sin exigir
un único grafo artificial.

## Reglas del loader

IDs y variant IDs únicos; exports tipados y consistentes; versiones de lenguaje
cuando una construcción lo requiere; queries parseables; dependencies de `match`
resueltas; error por keys desconocidas para detectar typos. No descargar dependencias
de reglas por sorpresa. Paths de fixtures/documentación son datos, no comandos.

Archivo final habilitado requiere al menos una variante lista. Variantes draft
siguen visibles en `rules --include-drafts`, pero no se ejecutan por defecto.
Si el usuario pide explícitamente una variante draft, informar que no está lista.
No confundirla con «cero coincidencias».

Un patrón puede tener varias variantes en el mismo lenguaje y una variante puede
servir para varios lenguajes. Cuando las queries divergen, crear otra variante;
cuando solo diverge el lowering, compartir query y declarar capabilities.
No usar language tags para ocultar que una consulta exige herencia inexistente.

## Base de datos de Ken

La DB es una proyección indexada y un cache, no el único lugar donde vive una regla.
Tablas lógicas: `rule`, `variant`, `export_role`, `dependency`, `compiled_plan`,
`fixture_manifest` y `evaluation`. Al cargar, sincronizar por hash de contenido y
versión; detectar archivos eliminados para retirar variantes obsoletas. Registrar
ruta de origen y hash para abrir exactamente la definición evaluada.

Una coincidencia referencia `rule_id`, `variant_ids`, hash de definición y snapshot.
Si cambia el archivo, la evaluación anterior sigue trazable, pero no se reutiliza
como si usara la definición nueva. Cambiar metadata no obliga a repetir joins.

Overrides locales explícitos conservan procedencia del original. Ediciones
simultáneas requieren lock/transacción y detección de actualización perdida;
`os.replace` solo asegura integridad de un archivo, no resuelve por sí solo ese
conflicto. Escribir archivos revisables facilita diffs y versionado con Git.

## Visibilidad

La CLI/MCP debe poder listar patrones, variantes, estado, lenguajes, dependencias,
consulta fuente y requisitos faltantes; abrir el archivo de definición; explicar
qué variante produjo un match. «23 patrones» no resume cuántas variantes están
listas. La relación con otras consultas se describe en [composición](composition.md).
