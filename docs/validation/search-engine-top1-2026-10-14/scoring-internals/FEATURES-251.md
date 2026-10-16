# Las251 señales del ranking de owners

Orden exacto del vector del modelo v69/v120. El sentido de una señal no implica que siempre aumente el score: los árboles pueden usarla de forma condicional.

| Índice0-based | Señal | Qué mide y cómo |
|---:|---|---|
| 0 | `rrf` | Suma de votos 1/(60+posición) de las familias de propuestas; no es probabilidad. |
| 1 | `cosine_identity` | Similitud densa de identidad medida al recuperar candidatos; cero si falta esa señal. |
| 2 | `cosine_behavior` | Similitud densa de comportamiento medida al recuperar candidatos; cero si falta. |
| 3 | `bm25f` | log(1+máximo BM25F del owner entre sus pasajes recuperados). |
| 4 | `bm25_body` | log(1+BM25 del campo body); señal léxica de recuperación. |
| 5 | `bm25_documentation` | log(1+BM25 del campo documentation); señal léxica de recuperación. |
| 6 | `bm25_identity` | log(1+BM25 del campo identity); señal léxica de recuperación. |
| 7 | `bm25_signature` | log(1+BM25 del campo signature); señal léxica de recuperación. |
| 8 | `bm25_path` | log(1+BM25 del campo path); señal léxica de recuperación. |
| 9 | `role_match` | 1 si el rol del primer pasaje coincide con el propósito interpretado; no prueba que sea definición y no consumidor. |
| 10 | `class` | 1 si el owner puntuado es una clase; no significa que la consulta pida una clase. |
| 11 | `module` | 1 si qualname del owner es nulo. |
| 12 | `log_lines` | log(1+longitud máxima del entity_span de sus pasajes). |
| 13 | `name_overlap` | Fracción de tokens distintos de la consulta presentes en el nombre cualificado. |
| 14 | `body_overlap` | Máxima fracción de tokens distintos de consulta presentes en el body de un pasaje. |
| 15 | `is_exception` | 1 si el nombre final contiene exception o error; heurística léxica. |
| 16 | `is_constructor` | 1 si el nombre final es __init__, new o constructor. |
| 17 | `query_log_tokens` | log(1+número de tokens distintos de la consulta original). |
| 18 | `query_identifier` | 1 si interpret reconoce autoridad de búsqueda por identidad explícita. |
| 19 | `query_kind_class` | 1 si la intención de identidad nombrada lleva kind=class. No representa todas las consultas descriptivas de clase. |
| 20 | `identity_exact` | consulta original, identidad/nombre del owner: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 21 | `identity_mean` | consulta original, identidad/nombre del owner: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 22 | `identity_min` | consulta original, identidad/nombre del owner: mínimo de esos mejores productos: el término menos cubierto. |
| 23 | `identity_p25` | consulta original, identidad/nombre del owner: percentil25 de esos mejores productos. |
| 24 | `identity_above50` | consulta original, identidad/nombre del owner: fracción de términos de consulta con mejor producto >=0.5. |
| 25 | `identity_above70` | consulta original, identidad/nombre del owner: fracción de términos de consulta con mejor producto >=0.7. |
| 26 | `identity_weighted` | consulta original, identidad/nombre del owner: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 27 | `identity_mean_cosine` | consulta original, identidad/nombre del owner: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 28 | `identity_log_words` | consulta original, identidad/nombre del owner: log(1+número de términos distintos retenidos en el campo). |
| 29 | `signature_exact` | consulta original, firma del owner: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 30 | `signature_mean` | consulta original, firma del owner: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 31 | `signature_min` | consulta original, firma del owner: mínimo de esos mejores productos: el término menos cubierto. |
| 32 | `signature_p25` | consulta original, firma del owner: percentil25 de esos mejores productos. |
| 33 | `signature_above50` | consulta original, firma del owner: fracción de términos de consulta con mejor producto >=0.5. |
| 34 | `signature_above70` | consulta original, firma del owner: fracción de términos de consulta con mejor producto >=0.7. |
| 35 | `signature_weighted` | consulta original, firma del owner: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 36 | `signature_mean_cosine` | consulta original, firma del owner: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 37 | `signature_log_words` | consulta original, firma del owner: log(1+número de términos distintos retenidos en el campo). |
| 38 | `documentation_exact` | consulta original, documentación atribuida al owner: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 39 | `documentation_mean` | consulta original, documentación atribuida al owner: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 40 | `documentation_min` | consulta original, documentación atribuida al owner: mínimo de esos mejores productos: el término menos cubierto. |
| 41 | `documentation_p25` | consulta original, documentación atribuida al owner: percentil25 de esos mejores productos. |
| 42 | `documentation_above50` | consulta original, documentación atribuida al owner: fracción de términos de consulta con mejor producto >=0.5. |
| 43 | `documentation_above70` | consulta original, documentación atribuida al owner: fracción de términos de consulta con mejor producto >=0.7. |
| 44 | `documentation_weighted` | consulta original, documentación atribuida al owner: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 45 | `documentation_mean_cosine` | consulta original, documentación atribuida al owner: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 46 | `documentation_log_words` | consulta original, documentación atribuida al owner: log(1+número de términos distintos retenidos en el campo). |
| 47 | `body_exact` | consulta original, body original atribuido: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 48 | `body_mean` | consulta original, body original atribuido: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 49 | `body_min` | consulta original, body original atribuido: mínimo de esos mejores productos: el término menos cubierto. |
| 50 | `body_p25` | consulta original, body original atribuido: percentil25 de esos mejores productos. |
| 51 | `body_above50` | consulta original, body original atribuido: fracción de términos de consulta con mejor producto >=0.5. |
| 52 | `body_above70` | consulta original, body original atribuido: fracción de términos de consulta con mejor producto >=0.7. |
| 53 | `body_weighted` | consulta original, body original atribuido: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 54 | `body_mean_cosine` | consulta original, body original atribuido: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 55 | `body_log_words` | consulta original, body original atribuido: log(1+número de términos distintos retenidos en el campo). |
| 56 | `path_exact` | consulta original, ruta: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 57 | `path_mean` | consulta original, ruta: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 58 | `path_min` | consulta original, ruta: mínimo de esos mejores productos: el término menos cubierto. |
| 59 | `path_p25` | consulta original, ruta: percentil25 de esos mejores productos. |
| 60 | `path_above50` | consulta original, ruta: fracción de términos de consulta con mejor producto >=0.5. |
| 61 | `path_above70` | consulta original, ruta: fracción de términos de consulta con mejor producto >=0.7. |
| 62 | `path_weighted` | consulta original, ruta: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 63 | `path_mean_cosine` | consulta original, ruta: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 64 | `path_log_words` | consulta original, ruta: log(1+número de términos distintos retenidos en el campo). |
| 65 | `all_exact` | consulta original, unión de campos con el orden de proyección registrado: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 66 | `all_mean` | consulta original, unión de campos con el orden de proyección registrado: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 67 | `all_min` | consulta original, unión de campos con el orden de proyección registrado: mínimo de esos mejores productos: el término menos cubierto. |
| 68 | `all_p25` | consulta original, unión de campos con el orden de proyección registrado: percentil25 de esos mejores productos. |
| 69 | `all_above50` | consulta original, unión de campos con el orden de proyección registrado: fracción de términos de consulta con mejor producto >=0.5. |
| 70 | `all_above70` | consulta original, unión de campos con el orden de proyección registrado: fracción de términos de consulta con mejor producto >=0.7. |
| 71 | `all_weighted` | consulta original, unión de campos con el orden de proyección registrado: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 72 | `all_mean_cosine` | consulta original, unión de campos con el orden de proyección registrado: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 73 | `all_log_words` | consulta original, unión de campos con el orden de proyección registrado: log(1+número de términos distintos retenidos en el campo). |
| 74 | `rrf_relative` | Normalización por rango de rrf: (x-min)/max(1e-9,max-min) entre candidatos. |
| 75 | `rrf_rank` | 1/posición descendente estable según rrf. No es el puesto final. |
| 76 | `cosine_identity_relative` | Normalización por rango de cosine_identity: (x-min)/max(1e-9,max-min) entre candidatos. |
| 77 | `cosine_identity_rank` | 1/posición descendente estable según cosine_identity. No es el puesto final. |
| 78 | `cosine_behavior_relative` | Normalización por rango de cosine_behavior: (x-min)/max(1e-9,max-min) entre candidatos. |
| 79 | `cosine_behavior_rank` | 1/posición descendente estable según cosine_behavior. No es el puesto final. |
| 80 | `bm25f_relative` | Normalización por rango de bm25f: (x-min)/max(1e-9,max-min) entre candidatos. |
| 81 | `bm25f_rank` | 1/posición descendente estable según bm25f. No es el puesto final. |
| 82 | `bm25_body_relative` | Normalización por rango de bm25_body: (x-min)/max(1e-9,max-min) entre candidatos. |
| 83 | `bm25_body_rank` | 1/posición descendente estable según bm25_body. No es el puesto final. |
| 84 | `bm25_documentation_relative` | Normalización por rango de bm25_documentation: (x-min)/max(1e-9,max-min) entre candidatos. |
| 85 | `bm25_documentation_rank` | 1/posición descendente estable según bm25_documentation. No es el puesto final. |
| 86 | `bm25_identity_relative` | Normalización por rango de bm25_identity: (x-min)/max(1e-9,max-min) entre candidatos. |
| 87 | `bm25_identity_rank` | 1/posición descendente estable según bm25_identity. No es el puesto final. |
| 88 | `bm25_signature_relative` | Normalización por rango de bm25_signature: (x-min)/max(1e-9,max-min) entre candidatos. |
| 89 | `bm25_signature_rank` | 1/posición descendente estable según bm25_signature. No es el puesto final. |
| 90 | `bm25_path_relative` | Normalización por rango de bm25_path: (x-min)/max(1e-9,max-min) entre candidatos. |
| 91 | `bm25_path_rank` | 1/posición descendente estable según bm25_path. No es el puesto final. |
| 92 | `expanded_identity_exact` | consulta expandida, identidad/nombre del owner: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 93 | `expanded_identity_stem` | consulta expandida, identidad/nombre del owner: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 94 | `expanded_identity_mean` | consulta expandida, identidad/nombre del owner: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 95 | `expanded_identity_min` | consulta expandida, identidad/nombre del owner: mínimo de esos mejores productos: el término menos cubierto. |
| 96 | `expanded_identity_p25` | consulta expandida, identidad/nombre del owner: percentil25 de esos mejores productos. |
| 97 | `expanded_identity_above50` | consulta expandida, identidad/nombre del owner: fracción de términos de consulta con mejor producto >=0.5. |
| 98 | `expanded_identity_above70` | consulta expandida, identidad/nombre del owner: fracción de términos de consulta con mejor producto >=0.7. |
| 99 | `expanded_identity_weighted` | consulta expandida, identidad/nombre del owner: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 100 | `expanded_identity_mean_cosine` | consulta expandida, identidad/nombre del owner: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 101 | `expanded_identity_log_words` | consulta expandida, identidad/nombre del owner: log(1+número de términos distintos retenidos en el campo). |
| 102 | `expanded_signature_exact` | consulta expandida, firma del owner: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 103 | `expanded_signature_stem` | consulta expandida, firma del owner: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 104 | `expanded_signature_mean` | consulta expandida, firma del owner: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 105 | `expanded_signature_min` | consulta expandida, firma del owner: mínimo de esos mejores productos: el término menos cubierto. |
| 106 | `expanded_signature_p25` | consulta expandida, firma del owner: percentil25 de esos mejores productos. |
| 107 | `expanded_signature_above50` | consulta expandida, firma del owner: fracción de términos de consulta con mejor producto >=0.5. |
| 108 | `expanded_signature_above70` | consulta expandida, firma del owner: fracción de términos de consulta con mejor producto >=0.7. |
| 109 | `expanded_signature_weighted` | consulta expandida, firma del owner: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 110 | `expanded_signature_mean_cosine` | consulta expandida, firma del owner: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 111 | `expanded_signature_log_words` | consulta expandida, firma del owner: log(1+número de términos distintos retenidos en el campo). |
| 112 | `expanded_documentation_exact` | consulta expandida, documentación atribuida al owner: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 113 | `expanded_documentation_stem` | consulta expandida, documentación atribuida al owner: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 114 | `expanded_documentation_mean` | consulta expandida, documentación atribuida al owner: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 115 | `expanded_documentation_min` | consulta expandida, documentación atribuida al owner: mínimo de esos mejores productos: el término menos cubierto. |
| 116 | `expanded_documentation_p25` | consulta expandida, documentación atribuida al owner: percentil25 de esos mejores productos. |
| 117 | `expanded_documentation_above50` | consulta expandida, documentación atribuida al owner: fracción de términos de consulta con mejor producto >=0.5. |
| 118 | `expanded_documentation_above70` | consulta expandida, documentación atribuida al owner: fracción de términos de consulta con mejor producto >=0.7. |
| 119 | `expanded_documentation_weighted` | consulta expandida, documentación atribuida al owner: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 120 | `expanded_documentation_mean_cosine` | consulta expandida, documentación atribuida al owner: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 121 | `expanded_documentation_log_words` | consulta expandida, documentación atribuida al owner: log(1+número de términos distintos retenidos en el campo). |
| 122 | `expanded_implementation_exact` | consulta expandida, regiones propias desde implementation_start_line: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 123 | `expanded_implementation_stem` | consulta expandida, regiones propias desde implementation_start_line: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 124 | `expanded_implementation_mean` | consulta expandida, regiones propias desde implementation_start_line: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 125 | `expanded_implementation_min` | consulta expandida, regiones propias desde implementation_start_line: mínimo de esos mejores productos: el término menos cubierto. |
| 126 | `expanded_implementation_p25` | consulta expandida, regiones propias desde implementation_start_line: percentil25 de esos mejores productos. |
| 127 | `expanded_implementation_above50` | consulta expandida, regiones propias desde implementation_start_line: fracción de términos de consulta con mejor producto >=0.5. |
| 128 | `expanded_implementation_above70` | consulta expandida, regiones propias desde implementation_start_line: fracción de términos de consulta con mejor producto >=0.7. |
| 129 | `expanded_implementation_weighted` | consulta expandida, regiones propias desde implementation_start_line: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 130 | `expanded_implementation_mean_cosine` | consulta expandida, regiones propias desde implementation_start_line: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 131 | `expanded_implementation_log_words` | consulta expandida, regiones propias desde implementation_start_line: log(1+número de términos distintos retenidos en el campo). |
| 132 | `expanded_executable_exact` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 133 | `expanded_executable_stem` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 134 | `expanded_executable_mean` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 135 | `expanded_executable_min` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: mínimo de esos mejores productos: el término menos cubierto. |
| 136 | `expanded_executable_p25` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: percentil25 de esos mejores productos. |
| 137 | `expanded_executable_above50` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: fracción de términos de consulta con mejor producto >=0.5. |
| 138 | `expanded_executable_above70` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: fracción de términos de consulta con mejor producto >=0.7. |
| 139 | `expanded_executable_weighted` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 140 | `expanded_executable_mean_cosine` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 141 | `expanded_executable_log_words` | consulta expandida, líneas no vacías no reconocidas como comentarios por el filtro léxico: log(1+número de términos distintos retenidos en el campo). |
| 142 | `expanded_comments_exact` | consulta expandida, líneas reconocidas como comentarios por ese filtro: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 143 | `expanded_comments_stem` | consulta expandida, líneas reconocidas como comentarios por ese filtro: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 144 | `expanded_comments_mean` | consulta expandida, líneas reconocidas como comentarios por ese filtro: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 145 | `expanded_comments_min` | consulta expandida, líneas reconocidas como comentarios por ese filtro: mínimo de esos mejores productos: el término menos cubierto. |
| 146 | `expanded_comments_p25` | consulta expandida, líneas reconocidas como comentarios por ese filtro: percentil25 de esos mejores productos. |
| 147 | `expanded_comments_above50` | consulta expandida, líneas reconocidas como comentarios por ese filtro: fracción de términos de consulta con mejor producto >=0.5. |
| 148 | `expanded_comments_above70` | consulta expandida, líneas reconocidas como comentarios por ese filtro: fracción de términos de consulta con mejor producto >=0.7. |
| 149 | `expanded_comments_weighted` | consulta expandida, líneas reconocidas como comentarios por ese filtro: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 150 | `expanded_comments_mean_cosine` | consulta expandida, líneas reconocidas como comentarios por ese filtro: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 151 | `expanded_comments_log_words` | consulta expandida, líneas reconocidas como comentarios por ese filtro: log(1+número de términos distintos retenidos en el campo). |
| 152 | `expanded_calls_exact` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 153 | `expanded_calls_stem` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 154 | `expanded_calls_mean` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 155 | `expanded_calls_min` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: mínimo de esos mejores productos: el término menos cubierto. |
| 156 | `expanded_calls_p25` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: percentil25 de esos mejores productos. |
| 157 | `expanded_calls_above50` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: fracción de términos de consulta con mejor producto >=0.5. |
| 158 | `expanded_calls_above70` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: fracción de términos de consulta con mejor producto >=0.7. |
| 159 | `expanded_calls_weighted` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 160 | `expanded_calls_mean_cosine` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 161 | `expanded_calls_log_words` | consulta expandida, nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos: log(1+número de términos distintos retenidos en el campo). |
| 162 | `expanded_returns_exact` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 163 | `expanded_returns_stem` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 164 | `expanded_returns_mean` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 165 | `expanded_returns_min` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: mínimo de esos mejores productos: el término menos cubierto. |
| 166 | `expanded_returns_p25` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: percentil25 de esos mejores productos. |
| 167 | `expanded_returns_above50` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: fracción de términos de consulta con mejor producto >=0.5. |
| 168 | `expanded_returns_above70` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: fracción de términos de consulta con mejor producto >=0.7. |
| 169 | `expanded_returns_weighted` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 170 | `expanded_returns_mean_cosine` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 171 | `expanded_returns_log_words` | consulta expandida, líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo: log(1+número de términos distintos retenidos en el campo). |
| 172 | `expanded_path_exact` | consulta expandida, ruta: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 173 | `expanded_path_stem` | consulta expandida, ruta: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 174 | `expanded_path_mean` | consulta expandida, ruta: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 175 | `expanded_path_min` | consulta expandida, ruta: mínimo de esos mejores productos: el término menos cubierto. |
| 176 | `expanded_path_p25` | consulta expandida, ruta: percentil25 de esos mejores productos. |
| 177 | `expanded_path_above50` | consulta expandida, ruta: fracción de términos de consulta con mejor producto >=0.5. |
| 178 | `expanded_path_above70` | consulta expandida, ruta: fracción de términos de consulta con mejor producto >=0.7. |
| 179 | `expanded_path_weighted` | consulta expandida, ruta: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 180 | `expanded_path_mean_cosine` | consulta expandida, ruta: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 181 | `expanded_path_log_words` | consulta expandida, ruta: log(1+número de términos distintos retenidos en el campo). |
| 182 | `expanded_all_exact` | consulta expandida, unión de campos con el orden de proyección registrado: fracción de términos distintos de consulta presentes literalmente en el campo. |
| 183 | `expanded_all_stem` | consulta expandida, unión de campos con el orden de proyección registrado: fracción de raíces Snowball distintas de consulta presentes en el campo. |
| 184 | `expanded_all_mean` | consulta expandida, unión de campos con el orden de proyección registrado: media del mejor producto escalar de cada término de consulta contra términos del campo. |
| 185 | `expanded_all_min` | consulta expandida, unión de campos con el orden de proyección registrado: mínimo de esos mejores productos: el término menos cubierto. |
| 186 | `expanded_all_p25` | consulta expandida, unión de campos con el orden de proyección registrado: percentil25 de esos mejores productos. |
| 187 | `expanded_all_above50` | consulta expandida, unión de campos con el orden de proyección registrado: fracción de términos de consulta con mejor producto >=0.5. |
| 188 | `expanded_all_above70` | consulta expandida, unión de campos con el orden de proyección registrado: fracción de términos de consulta con mejor producto >=0.7. |
| 189 | `expanded_all_weighted` | consulta expandida, unión de campos con el orden de proyección registrado: media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners. |
| 190 | `expanded_all_mean_cosine` | consulta expandida, unión de campos con el orden de proyección registrado: producto del vector de consulta con la media normalizada de vectores de términos distintos del campo. |
| 191 | `expanded_all_log_words` | consulta expandida, unión de campos con el orden de proyección registrado: log(1+número de términos distintos retenidos en el campo). |
| 192 | `expanded_kind_function` | 1 si el tipo canónico del owner es function. |
| 193 | `expanded_kind_method` | 1 si el tipo canónico del owner es method. |
| 194 | `expanded_kind_class` | 1 si el tipo canónico del owner es class. |
| 195 | `expanded_kind_struct` | 1 si el tipo canónico del owner es struct. |
| 196 | `expanded_kind_interface` | 1 si el tipo canónico del owner es interface. |
| 197 | `expanded_kind_enum` | 1 si el tipo canónico del owner es enum. |
| 198 | `expanded_kind_trait` | 1 si el tipo canónico del owner es trait. |
| 199 | `expanded_kind_type` | 1 si el tipo canónico del owner es type. |
| 200 | `expanded_kind_module` | 1 si el tipo canónico del owner es module. |
| 201 | `expanded_kind_constant` | 1 si el tipo canónico del owner es constant. |
| 202 | `expanded_kind_property` | 1 si el tipo canónico del owner es property. |
| 203 | `expanded_kind_variable` | 1 si el tipo canónico del owner es variable. |
| 204 | `expanded_kind_constructor` | 1 si el tipo canónico del owner es constructor. |
| 205 | `expanded_log_executable_lines` | log(1+líneas ejecutables léxicas propias). |
| 206 | `expanded_log_comment_lines` | log(1+líneas de comentario léxicas propias). |
| 207 | `expanded_log_owned_lines` | log(1+líneas en regiones atribuidas al owner). |
| 208 | `expanded_log_regions` | log(1+número de pasajes/regiones únicos del owner). |
| 209 | `expanded_documentation_fraction` | 1 - implementation_lines/max(1,owned_lines); no es una medida de calidad documental. |
| 210 | `expanded_query_negation` | 1 si la consulta expandida contiene not/without/never/no/sin; no resuelve el alcance de la negación. |
| 211 | `expanded_query_test` | 1 si interpret clasifica la consulta expandida como petición de tests. |
| 212 | `expanded_op_return` | log(1+apariciones léxicas de return en executable). |
| 213 | `expanded_op_raise` | log(1+apariciones léxicas de raise en executable). |
| 214 | `expanded_op_throw` | log(1+apariciones léxicas de throw en executable). |
| 215 | `expanded_op_panic` | log(1+apariciones léxicas de panic en executable). |
| 216 | `expanded_op_if` | log(1+apariciones léxicas de if en executable). |
| 217 | `expanded_op_else` | log(1+apariciones léxicas de else en executable). |
| 218 | `expanded_op_try` | log(1+apariciones léxicas de try en executable). |
| 219 | `expanded_op_catch` | log(1+apariciones léxicas de catch en executable). |
| 220 | `expanded_op_except` | log(1+apariciones léxicas de except en executable). |
| 221 | `expanded_op_for` | log(1+apariciones léxicas de for en executable). |
| 222 | `expanded_op_while` | log(1+apariciones léxicas de while en executable). |
| 223 | `expanded_op_match` | log(1+apariciones léxicas de match en executable). |
| 224 | `expanded_op_switch` | log(1+apariciones léxicas de switch en executable). |
| 225 | `expanded_op_await` | log(1+apariciones léxicas de await en executable). |
| 226 | `expanded_op_yield` | log(1+apariciones léxicas de yield en executable). |
| 227 | `code_original_raw` | code_original: producto escalar medido. |
| 228 | `code_original_to_max` | code_original: valor - máximo del pool (no cociente). |
| 229 | `code_original_range_relative` | code_original: (valor-mínimo)/max(1e-9,máximo-mínimo). |
| 230 | `code_original_reciprocal_rank` | code_original: 1/posición descendente estable dentro del pool. |
| 231 | `code_expanded_raw` | code_expanded: producto escalar medido. |
| 232 | `code_expanded_to_max` | code_expanded: valor - máximo del pool (no cociente). |
| 233 | `code_expanded_range_relative` | code_expanded: (valor-mínimo)/max(1e-9,máximo-mínimo). |
| 234 | `code_expanded_reciprocal_rank` | code_expanded: 1/posición descendente estable dentro del pool. |
| 235 | `view_contract_original_raw` | view_contract_original: producto escalar medido. |
| 236 | `view_contract_original_to_max` | view_contract_original: valor - máximo del pool (no cociente). |
| 237 | `view_contract_original_range_relative` | view_contract_original: (valor-mínimo)/max(1e-9,máximo-mínimo). |
| 238 | `view_contract_original_reciprocal_rank` | view_contract_original: 1/posición descendente estable dentro del pool. |
| 239 | `view_contract_expanded_raw` | view_contract_expanded: producto escalar medido. |
| 240 | `view_contract_expanded_to_max` | view_contract_expanded: valor - máximo del pool (no cociente). |
| 241 | `view_contract_expanded_range_relative` | view_contract_expanded: (valor-mínimo)/max(1e-9,máximo-mínimo). |
| 242 | `view_contract_expanded_reciprocal_rank` | view_contract_expanded: 1/posición descendente estable dentro del pool. |
| 243 | `view_implementation_original_raw` | view_implementation_original: producto escalar medido. |
| 244 | `view_implementation_original_to_max` | view_implementation_original: valor - máximo del pool (no cociente). |
| 245 | `view_implementation_original_range_relative` | view_implementation_original: (valor-mínimo)/max(1e-9,máximo-mínimo). |
| 246 | `view_implementation_original_reciprocal_rank` | view_implementation_original: 1/posición descendente estable dentro del pool. |
| 247 | `view_implementation_expanded_raw` | view_implementation_expanded: producto escalar medido. |
| 248 | `view_implementation_expanded_to_max` | view_implementation_expanded: valor - máximo del pool (no cociente). |
| 249 | `view_implementation_expanded_range_relative` | view_implementation_expanded: (valor-mínimo)/max(1e-9,máximo-mínimo). |
| 250 | `view_implementation_expanded_reciprocal_rank` | view_implementation_expanded: 1/posición descendente estable dentro del pool. |
