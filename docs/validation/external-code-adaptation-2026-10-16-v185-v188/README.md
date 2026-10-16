# Adaptación externa del reranker de 68M y exportación CPU, v185–v188

El experimento está cerrado y guardado; la captura pública A189 sigue en curso.
**El motor instalado sigue en 191/197 (original) y 159/195 (nuevo). No se acredita 90%
nuevo, no se cambia el default y la reserva permanece cerrada. Sin release.**

La adaptación del mismo modelo de 68M subió de 2768/3000 a 2799/3000 en una validación externa
de cuatro candidatos por consulta. No es la batería de Ken ni una aceptación
independiente. No comparar directamente este porcentaje con top1en200consultas
contra repositorios completos.

| Validación externa | Original | Adaptado | Consultas |
|---|---:|---:|---:|
| Python |908|920|1000|
| Java |928|934|1000|
| JavaScript |932|945|1000|
| Total |2768(92,27%)|2799(93,30%)|3000|

## Qué se entrenó y qué información se usó

Mismo Ettin de 68.408.321 parámetros. Se ajustaron 4.722.177 parámetros existentes:
últimos 2 de 19 bloques y cabeza publicada. Los 63.686.144 restantes quedaron fijos.
Una época, seed 42, AdamW 5e-5 y objetivo softmax entre cuatro candidatos; no hubo
búsqueda de hiperparámetros o elección de checkpoint según las 400 consultas.

CodeSearchNet TRAIN, revisiónbd0cf261e357a3eb5c8fba490d23ec1a1cd59555. Se
prepararon 12.000 grupos de entrenamiento y 3.000 de validación, 4.000/1.000 por lenguaje.
Dos negativos del mismo repositorio —el primero prefiere el mismo archivo— y
uno de otro repositorio. La partición separa también TODOS los repositorios de
los candidatos: 829 entrenamiento, 199 validación, sin intersección.

Se excluyeron los ocho proyectos evaluados por nombre y se compararon clones
normalizados con 2.593 archivos públicos. Se retiraron comentarios/docstrings,
se controlaron duplicados y fuga textual de la pregunta. La revisión independiente
de 24 pares y la auditoría mecánica corrigieron problemas antes de entrenar.
Las etiquetas siguen siendo supervisión documental débil: el muestreo no prueba
que cada negativo sea semánticamente incorrecto ni elimina todos los forks
modificados. Los 26 archivos con fallback crudo del guard tienen ese límite registrado.

Sólo para TRAIN se omitieron 1.032 positivos que no cabían completos en 512 tokens o
tenían pregunta >480 tokens: quedaron 10.968 grupos y 5.484 actualizaciones. Se retuvieron
LOS 3.000 de validación. Esto no cambia ningún ID/label/denominador de Ken.
No se usaron respuestas de las 400 consultas para ajustar estos pesos. No se abrió
ningún payload de la reserva, tampoco sus consultas públicas.

## Prueba del modelo portable

Se reemplazaron 17 initializers autorizados del ONNX existente. Los 2.513 nodos,
inputs, outputs, shapes y 125 initializers conservan su estructura; los demás
pesos se verifican iguales. No se agregan parámetros ni operadores. El exportador
de identidad reproduce byte por byte el ONNX original. Las siete parejas
sintéticas de la exportación adaptada coinciden entre TorchCPU y ONNX CPU dentro
de 1e-3; máximo observado 5,7220458984375e-6, incluyendo un documento de 512 tokens.
Esto prueba equivalencia numérica de esos inputs, no calidad de búsqueda.

- Tail final SHA498f4ae5ee2923c3f3a81b6f7e5c9c6a14a8c6b593babf0463cd3d5365a9f6e3.
- ONNX adaptado SHA33c135076925f43f8cc81be7194ba37ffc478c89a7e60b12eabd7ec32f8d7a06.
- Archivo ONNX de 274.035.078 bytes. El tail retenido permite reconstruirlo con los
  artefactos publicados, productores y hashes guardados; el ONNX completo no se duplica enGit.

El entrenamiento usó MPS local. La inferencia exportada usa CPUExecutionProvider.
El verificador que mantiene Torch y ONNX juntos llegó a 2.361.180.160 bytes; **eso
no es el RSS del motor**. Falta la medición completa MCP normal del candidato
antes de cualquier promoción. Que coincida el grafo no acredita latencia/RAM.

## Incidentes preservados y comprobaciones

El entrenamiento inicial crecía de memoria y se reanudó desde checkpoints
cerrados cada 500 pasos, conservando optimizer/scheduler/orden. No hubo otra época
ni selección por aciertos. El primer resume falló antes de actualizar por una
ruta absoluta que no coincidía con la relativa registrada; se corrigió el caller.

Al final, el entrenador cerró con exit 0, pero el supervisor terminó exit 1:
después de 5.000 esperaba 5.500 en su loop interno, aunque el total era 5.484. El bloque
final parcial y su validación acabaron correctamente. La auditoría reconstruye
5484losses,5484pasos de scheduler,10968IDs, todos los scores/IDs externos y el
tail final idéntico al checkpoint 5.484. El defecto del supervisor y sus logs se
conservan; para otro run debe esperar min(total,paso+500). No se reentrenó ni se
reescribió el productor histórico para ocultarlo.

32 pruebas del curador/exportador pasan. Se preservan los fallos iniciales:
fixture NumPy no contiguo y un comando de tests sin PYTHONPATH; corregidos sin
cambiar la receta. Las tres pruebas previas del wrapper verifican equivalencia
del modelo original, padding y máscara de parámetros entrenables. Un smoke de
46consultas en8repositorios reproduce exactamente los órdenes MCP originales
usando la API diagnóstica que hará la captura; incluye las cuatro piezas.

## Siguiente validación, fijada antes de puntuar

Se capturan 400 consultas completas, manteniendo exactamente los candidatos,
locators cualificados, fuentes y modelos nativos. Se informan tres variantes:
raw adaptado; RRF(.5,60)adaptado; y raw para símbolos con esa RRF para agregados.
La tercera política se registró antes de existir el tail final: la supervisión
externa identifica funciones, mientras el bosque de piezas aporta evidencia
para clase/módulo/archivo. Usan una sola sesión de 68M; no una selección por ID.

Cada variante exige>=180/200original Y>=180/200nuevo, con Recall10exacto197y195.
No se promedian cohortes para superar el umbral. Se cierran TODAS las predicciones
antes de puntuar referencias expuestas. Si ninguna pasa, el candidato no se
activa; los fallos pueden informar otra hipótesis. La reserva sigue cerrada
incluso si una pasa. Todo esto es desarrollo expuesto.

La [revisión fuente de los26fallos anteriores](SOURCE-CARD-VISIBILITY.md)
encuentra 13 núcleos visibles, 9 contextos externos y 4 pérdidas materiales previas al
tokenizer. Ningún card correcto supera 512 tokens. No hay errores definitivos de
referencia ni cambios de label. Distinguir disponibilidad de causa del ranking.

## Archivo reproducible

`output/checkpoints/external-code-adaptation-v185-v188` contiene 103 payloads gzip
con hashes de bytes originales y comprimidos, incluidos el tail final, recetas,
curación/revisiones, scores externos, tests/fallos, exportaciones y auditoría.
Manifest SHA7c047b0621842d72881c5416978e916f0ee5343a35eab2a22f2df0e140eb658b.
Metadatos exactos de funciones/grupos permiten contrastar IDs/orden/hashes con
una regeneración desde los parquets públicos registrados. No se duplica 1GB de
parquets ni el modelo base público. Los payloads de código/query externos
completos se regeneran con el productor y sus dependencias registradas.
Este archivo cerrado no contiene resultados públicos A189 ni reservas.
