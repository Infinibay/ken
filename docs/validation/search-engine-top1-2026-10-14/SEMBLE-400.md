# Semble y Ken sobre las mismas 400 consultas

Estudio de desarrollo, sin ejecutar la reserva de aceptación. Semble 0.6.2,
commit `0e5e02832ae0340c0feb637d2b7213fe065571fd`, usa su indexado, filtros,
alpha y reranking predeterminados. Se solicita top 10 y hasta 40 líneas por
fragmento. Los pesos locales son Potion-code-16M-v2 en la misma revisión usada
por Ken. Model2Vec genera los embeddings; Vicinity hace la búsqueda vectorial.
El productor sólo recibe identificador, repositorio/commit, raíz y consulta.

Comparación común del primer resultado, con las consultas y anclas originales:

| Criterio | Ken, control Potion con preferencia de rol v11 | Semble nativo |
|---|---:|---:|
| Archivo correcto | 241/400 (60,25%) | 204/400 (51%) |
| Archivo y todas las anclas decisivas visibles | 151/400 (37,75%) | 65/400 (16,25%) |

La segunda fila comprueba las mismas anclas, fuente fiel y presupuesto de
salida, pero ignora el campo de propietario canónico en ambos sistemas. Es un
diagnóstico común de recuperación y fragmento visible, **no el gate de
aceptación aprobado**. Los 151 aciertos de este control Ken también pasan el
scorer estricto. Semble no entrega nombre de función; atribuirle el propietario
requiere una normalización adicional y puede perder casos con varios dueños.
No se debe comparar su 4,75% normalizado directamente con el 37,75% estricto de
Ken como si midieran limpiamente la misma capacidad.

La normalización v2 sólo asigna entidad cuando un único propietario contiene
todas las líneas sustantivas visibles en sus regiones propias. Resuelve 161
primeros resultados; 53 coinciden en identidad y 19 pasan el scorer estricto.
Los chunks de clase o los que cruzan funciones suelen quedar sin entidad,
aunque contengan parte de código útil. Ese límite del adaptador se conserva
explícito; nunca se infiere el propietario a partir de la referencia esperada.

Se conservan orden y contenido nativos. El `end_line` de Semble puede describir
el chunk completo aunque su contenido haya sido recortado a 40 líneas: sólo
cuentan las líneas realmente mostradas. También puede empezar o terminar en
medio de una línea. El adaptador omite esos caracteres parciales y no completa
la declaración o instrucción invisible. Corrige únicamente la indentación del
primer renglón completo. Los hashes y las líneas se verifican contra fuente.

El primer adaptador v1 rechazaba algunos encabezados parciales de chunks.
Su salida y su fuente se preservan: daba 60 aciertos de todas las anclas. Tras
una prueba que reprodujo el defecto, v2 conserva las siguientes líneas completas
en su posición real y obtiene 65. No se cambiaron consultas, referencias,
recuperación nativa ni resolución de propietarios. Los nueve primeros
resultados todavía inválidos son un PNG binario de JUnit indexado por Semble;
se conservaron como fallos y no se filtraron después de ver resultados.

Recibos: `output/development/semble-cpu-400-v1/` conserva la salida nativa,
proveniencia y v1; `normalization-v2/` contiene la normalización corregida y su
auditoría. `output/development/semble-ken-visible-evidence-400.json` registra la
comparación común. SHA256 de la salida nativa:
`a433fddb5b7dae1f47af32f37b7cb20bcb557dc5661fb019421c0b80f75ea418`.
SHA256 de las 400 consultas/referencias de desarrollo:
`e68275872ea3cd14abb7499c4b6a38cc99908a8ce75bd7709a549f392972fc63`.

Este estudio no demuestra superioridad general ni sustituye una reserva
independiente. El objetivo sigue en al menos 90% de top‑1 estricto, con todas
sus condiciones y estratos, bajo CPU y RAM contenida.
