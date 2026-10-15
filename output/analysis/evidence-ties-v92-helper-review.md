# Revisión independiente del helper 92

La definición y propiedades del helper pasan la revisión. No encontré un bloqueo en esta pieza; aún no revisé ni aprobé matrices, manifiestos o un gate pre-fit. No leí consultas/etiquetas/rankings, ejecuté entrenamiento, edité implementación/referencias/modelos ni abrí la reserva.

Para un valor con `g` scores mayores y `c` scores iguales, usa `1 / (g + (c+1)/2)`. Esto coincide con el recíproco del [rango promedio de empates de SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.rankdata.html). El canal constante devuelve cero por una regla adicional registrada; un rango promedio ordinario daría `2/(N+1)`. Para un empate en posiciones 1–2, el resultado es 2/3, no el promedio de recíprocos 3/4.

Verifiqué 1.806 vectores y 116.715 valores contra una derivación independiente por conteo de mayores/iguales y contra SciPy en los casos no constantes. Para comparar la salida float64 del helper, convertí los **rangos resultantes** de SciPy a float64 antes del recíproco; no convertí los scores antes de agrupar. Pasan igualdad de empates, monotonía, equivariancia por permutación, entrada intacta, salida independiente y concurrencia de ocho threads. Se preservan distinciones adyacentes de uint64/int64 extremos y longdouble; se rechazan nueve tipos/casos inválidos. Los nueve tests congelados pasan.

Todos los archivos `src/` son idénticos al freeze 90. Los únicos cambios de inventario son el helper, sus tests y protocolos de investigación. La política ordinal legacy es una definición válida: este ensayo no demuestra un bug API ni superioridad de recuperación. La nueva equivariancia pertenece a cada canal transformado; las otras 236 columnas y el desempate final por posición pueden conservar dependencia del orden. El ensayo combina rango promedio y neutralidad constante, por lo que un eventual cambio de calidad no aislaría sólo una de esas reglas.

El gate posterior debe comprobar las 15 columnas exactas, otras 236 idénticas, 37 bypass exactos intactos, 400 consultas y los 16 conjuntos de entrenamiento excluidos por repo. La conservación del esquema de 251 nombres no basta para reutilizar la política de features de un perfil anterior en una integración futura: la nueva semántica requerirá identidad/versionado explícitos y replay real. Ninguna adopción de runtime o aceptación privada se autoriza aquí.

Recibo, dtypes, propiedades y límites: `evidence-ties-v92-helper-review.json`.
