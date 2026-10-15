# Revisión conceptual: contexto de implementación dentro del callable

**La hipótesis es viable con un contrato nuevo y explícito de procedencia.** No hace falta cambiar referencias, identidad exacta, anclas o aceptación. Tampoco sería fiel ampliar silenciosamente `owned_regions`, usar `entity_extent` como autorización, o reemplazar la entidad de un pasaje hijo por la del padre. No se aprobó implementación ni ajuste.

La partición canónica responde quién posee cada línea; un contexto léxico responde qué fuente anidada está contenida en un callable. Son responsabilidades distintas. Un bundle puede conservar una entidad primaria de respuesta y mostrar fuente descendiente con su propietario canónico y cadena de contención explícitos. Contención significa «incluye esta fuente»; no certifica llamada, ejecución, retorno resuelto ni orden de efectos entre cuerpos.

## Testigos públicos verificados

| Caso | Pérdida con regiones exclusivas | Lo que demuestra la fuente | Ventana ilustrativa, no predicción |
|---|---|---|---|
| Ajv07 | `code`:19–23,25–37,51 deja fuera24, parte del ancla original21–36 | `code.getEql`:24 es una declaración local dentro de `code`:19–51; la decisión loop/OR está27–36. La alternativa original tiene entidad nula y no se la reemplaza por una nueva etiqueta. |19–36:18 líneas|
| Boltons01 | `split_iter`:121–167,169,171–175,177–190 deja fuera176 del ancla174–189 | En el bucle se define `split_iter.sep_func` ordinal2:176 y se usa el identificador en177. Los otros dos `sep_func` conservan sus ordinales distintos. La entidad original sigue siendo exactamente `split_iter`. |121 +174–189:17 líneas en2 ventanas|
| Marked18 | `Marked.parseMarkdown`:310–317,380–382 no incluye el ancla345–354 | `const parse`:318 crea el callable cuyo cuerpo contiene345–354; `return parse`:381 aporta el testigo local de retorno. Eso no afirma que el método exterior ejecute el cuerpo asíncrono al crearlo. |310 +318–354 +381–382:40 líneas en3 ventanas|

Hashes de fuente y metadatos canónicos de source7 fueron contrastados en los tres casos; el JSON adjunto contiene entidades, ordinales, regiones y textos físicos. Las ventanas se eligieron durante esta revisión con referencias conocidas sólo como testigos de factibilidad geométrica. No son respuestas del motor, una regla de selección ni una estimación de mejora. El presupuesto JSON final, incluyendo procedencia, debe comprobarse en la implementación real.

## Contrato mínimo

1. Mantener identidad y partición exclusivas como fuente de verdad. Separar entidad primaria, fragmento físico y propietario real de cada tramo. Un fragmento continuo con varios propietarios necesita procedencia interna; no se convierte por eso en un `Passage` exclusivamente del padre.
2. Preparar el contexto para todos los owners antes de consultas/labels, desde AST y bytes vigentes: ruta, hash, generación, entidades exactas con ordinal y relación de contención léxica. Ni nombres parecidos, envolventes min/max, cosenos ni targets54/54b autorizan fuente. Ante identidad/ancestría ambigua o stale, fallar cerrado. Los casos de varios scopes en una misma línea requieren coordenadas de bytes o diagnóstico explícito.
3. El contexto de un callable puede incluir declaraciones anidadas como tales. No ascender a hermanos de clase/módulo ni atravesar llamadas, imports, herencia o nombres externos. Conservar fronteras de callable y alternativas de control. Afirmar uso/retorno resuelto exige prueba adicional del binding; aun así, devolver una función no ejecuta por sí mismo su cuerpo.
4. Usar la misma autorización de contexto en proyección de texto, target de capacidad de fuente y presentación. Distinguir cobertura fuente, bundle factible, evidencia efectivamente visible y prueba semántica/runtime. Un target futuro de la nueva unidad debe versionarse; las etiquetas históricas y referencias originales permanecen intactas.
5. Mantener identidad exacta cuando la alternativa la fija, hash vigente y TODAS las anclas de UNA alternativa original visibles. Entidad nula no exime anclas. Mantener ALL400, autoridad exacta, CPU,40 líneas por resultado, política de3fragmentos y12000 caracteres JSON finales incluyendo toda metadata. Headers y repeticiones consumen presupuesto; no esconder texto en metadata. Un recorte que quite un ancla sigue siendo fallo.
6. Conservar los perfiles anteriores. `source_bounds` y la política72/74 siguen teniendo su contrato propio; nueva autorización requiere versión/fingerprint y revisión de procedencia, selección y API antes de adopción.

## Límites y contraejemplos

Un helper no usado, una rama muerta o una clase local pueden estar físicamente anidados sin ejecutarse en el camino consultado. `def parse...; parse=external; return parse` impide inferir el retorno del primer `parse`. Dos definiciones condicionales del mismo nombre no forman una sola función ni una sola traza. Una llamada no calificada desde un método no permite elegir otro método homónimo de la clase. El JSON adjunto preserva estos contraejemplos y el comportamiento exigido.

54c aporta sólo cosenos/grados de parent/child a ranking: no construye bundles ni da autoridad de evidencia ni prueba retorno. Su resultado negativo no refuta esta hipótesis de representación.72/74 completa sólo regiones exclusivas, por lo que conserva justamente los huecos24,176 y345–354; ese límite cumple su contrato.

No recalcule aquí los cinco casos actuales sin positivo ni afirmo resolverlos todos. Los otros casos del informe histórico que necesitan callbacks anónimos de pruebas requieren representación explícita adicional. Recuperar fuente tampoco garantiza que un prefijo512 la codifique, que el selector la muestre o que mejore ranking. No se tocaron engine, labels, reglas, modelos o marcadores; no se abrieron reserva ni consultas/referencias del piloto auxiliar.
