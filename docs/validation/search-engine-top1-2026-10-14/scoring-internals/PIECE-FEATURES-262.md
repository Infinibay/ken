# Las262 señales del candidato de piezas v126

Este bosque sólo se aplica a clase/módulo/archivo. Símbolos mantienen su orden nativo. No confundir estas columnas con las251 del bosque anterior.

Prefijos: original = consulta original contra todos los miembros; piece = consulta expandida contra todos los miembros; declaration = consulta expandida contra la declaración propia. Los campos son identity/signature/documentation/executable/calls/returns/path/all. Se deduplican textos y limitan a4096 términos por campo. Las estadísticas exact/stem/mean/min/p25/above50/above70/weighted/mean_cosine/log_words conservan las fórmulas de FEATURES-251.md; la rareza aquí se calcula entre las diez piezas, no entre owners.

| Índice0-based | Señal | Significado |
|---:|---|---|
| 0 | `native_score` | Score del mejor miembro recuperado de esta pieza. |
| 1 | `native_to_best` | Score anterior menos el score del primer miembro de la primera pieza nativa. |
| 2 | `native_rank` | 1/posición de la pieza en el top10 nativo, antes del nuevo bosque. |
| 3 | `member_log_count` | log(1+número de owners propios de la pieza). |
| 4 | `matched_log_count` | log(1+número de miembros recuperados en el pool). |
| 5 | `matched_fraction` | Miembros recuperados / miembros propios de la pieza. |
| 6 | `member_score_mean3` | Media de los scores de hasta tres mejores miembros recuperados. |
| 7 | `member_score_gap` | Score del mejor miembro menos el segundo; cero si sólo hay uno. |
| 8 | `declaration_present` | Hay descripción de la declaración canónica (clase/símbolo o owner global del archivo). |
| 9 | `declaration_in_matches` | La declaración, además de existir, apareció entre las propuestas. |
| 10 | `declaration_score_to_best` | Score de declaración recuperada menos mejor miembro;0 más flag si no apareció. |
| 11 | `log_owned_lines` | log(1+suma de líneas propias de los miembros). |
| 12 | `log_executable_lines` | log(1+suma de líneas ejecutables léxicas de los miembros). |
| 13 | `documentation_fraction` | 1 - executable_lines/max(1,owned_lines); aproximación léxica, distinta de la señal antigua. |
| 14 | `test_path` | Ruta con componente test/tests/typing_tests/platform-tests/spec/specs en v123. |
| 15 | `data_file` | Extensión json/yaml/yml/toml. |
| 16 | `request_tests` | Propósito público explícito tests; auto no se reclasifica en esta versión. |
| 17 | `request_documentation` | Propósito público explícito documentation. |
| 18 | `request_class` | 1 si la pieza solicitada es class. |
| 19 | `request_module` | 1 si la pieza solicitada es module. |
| 20 | `request_symbol` | 1 si la pieza solicitada es symbol. |
| 21 | `request_file` | 1 si la pieza solicitada es file. |
| 22 | `declaration_kind_class` | 1 si el tipo canónico de la declaración es class. |
| 23 | `declaration_kind_interface` | 1 si el tipo canónico de la declaración es interface. |
| 24 | `declaration_kind_enum` | 1 si el tipo canónico de la declaración es enum. |
| 25 | `declaration_kind_type` | 1 si el tipo canónico de la declaración es type. |
| 26 | `declaration_kind_function` | 1 si el tipo canónico de la declaración es function. |
| 27 | `declaration_kind_method` | 1 si el tipo canónico de la declaración es method. |
| 28 | `declaration_kind_module` | 1 si el tipo canónico de la declaración es module. |
| 29 | `declaration_kind_constant` | 1 si el tipo canónico de la declaración es constant. |
| 30 | `original_identity_exact` | Cobertura original_identity_exact según campo, consulta y estadística descritos arriba. |
| 31 | `original_identity_mean` | Cobertura original_identity_mean según campo, consulta y estadística descritos arriba. |
| 32 | `original_identity_min` | Cobertura original_identity_min según campo, consulta y estadística descritos arriba. |
| 33 | `original_identity_p25` | Cobertura original_identity_p25 según campo, consulta y estadística descritos arriba. |
| 34 | `original_identity_above50` | Cobertura original_identity_above50 según campo, consulta y estadística descritos arriba. |
| 35 | `original_identity_above70` | Cobertura original_identity_above70 según campo, consulta y estadística descritos arriba. |
| 36 | `original_identity_weighted` | Cobertura original_identity_weighted según campo, consulta y estadística descritos arriba. |
| 37 | `original_identity_mean_cosine` | Cobertura original_identity_mean_cosine según campo, consulta y estadística descritos arriba. |
| 38 | `original_identity_log_words` | Cobertura original_identity_log_words según campo, consulta y estadística descritos arriba. |
| 39 | `original_signature_exact` | Cobertura original_signature_exact según campo, consulta y estadística descritos arriba. |
| 40 | `original_signature_mean` | Cobertura original_signature_mean según campo, consulta y estadística descritos arriba. |
| 41 | `original_signature_min` | Cobertura original_signature_min según campo, consulta y estadística descritos arriba. |
| 42 | `original_signature_p25` | Cobertura original_signature_p25 según campo, consulta y estadística descritos arriba. |
| 43 | `original_signature_above50` | Cobertura original_signature_above50 según campo, consulta y estadística descritos arriba. |
| 44 | `original_signature_above70` | Cobertura original_signature_above70 según campo, consulta y estadística descritos arriba. |
| 45 | `original_signature_weighted` | Cobertura original_signature_weighted según campo, consulta y estadística descritos arriba. |
| 46 | `original_signature_mean_cosine` | Cobertura original_signature_mean_cosine según campo, consulta y estadística descritos arriba. |
| 47 | `original_signature_log_words` | Cobertura original_signature_log_words según campo, consulta y estadística descritos arriba. |
| 48 | `original_documentation_exact` | Cobertura original_documentation_exact según campo, consulta y estadística descritos arriba. |
| 49 | `original_documentation_mean` | Cobertura original_documentation_mean según campo, consulta y estadística descritos arriba. |
| 50 | `original_documentation_min` | Cobertura original_documentation_min según campo, consulta y estadística descritos arriba. |
| 51 | `original_documentation_p25` | Cobertura original_documentation_p25 según campo, consulta y estadística descritos arriba. |
| 52 | `original_documentation_above50` | Cobertura original_documentation_above50 según campo, consulta y estadística descritos arriba. |
| 53 | `original_documentation_above70` | Cobertura original_documentation_above70 según campo, consulta y estadística descritos arriba. |
| 54 | `original_documentation_weighted` | Cobertura original_documentation_weighted según campo, consulta y estadística descritos arriba. |
| 55 | `original_documentation_mean_cosine` | Cobertura original_documentation_mean_cosine según campo, consulta y estadística descritos arriba. |
| 56 | `original_documentation_log_words` | Cobertura original_documentation_log_words según campo, consulta y estadística descritos arriba. |
| 57 | `original_executable_exact` | Cobertura original_executable_exact según campo, consulta y estadística descritos arriba. |
| 58 | `original_executable_mean` | Cobertura original_executable_mean según campo, consulta y estadística descritos arriba. |
| 59 | `original_executable_min` | Cobertura original_executable_min según campo, consulta y estadística descritos arriba. |
| 60 | `original_executable_p25` | Cobertura original_executable_p25 según campo, consulta y estadística descritos arriba. |
| 61 | `original_executable_above50` | Cobertura original_executable_above50 según campo, consulta y estadística descritos arriba. |
| 62 | `original_executable_above70` | Cobertura original_executable_above70 según campo, consulta y estadística descritos arriba. |
| 63 | `original_executable_weighted` | Cobertura original_executable_weighted según campo, consulta y estadística descritos arriba. |
| 64 | `original_executable_mean_cosine` | Cobertura original_executable_mean_cosine según campo, consulta y estadística descritos arriba. |
| 65 | `original_executable_log_words` | Cobertura original_executable_log_words según campo, consulta y estadística descritos arriba. |
| 66 | `original_calls_exact` | Cobertura original_calls_exact según campo, consulta y estadística descritos arriba. |
| 67 | `original_calls_mean` | Cobertura original_calls_mean según campo, consulta y estadística descritos arriba. |
| 68 | `original_calls_min` | Cobertura original_calls_min según campo, consulta y estadística descritos arriba. |
| 69 | `original_calls_p25` | Cobertura original_calls_p25 según campo, consulta y estadística descritos arriba. |
| 70 | `original_calls_above50` | Cobertura original_calls_above50 según campo, consulta y estadística descritos arriba. |
| 71 | `original_calls_above70` | Cobertura original_calls_above70 según campo, consulta y estadística descritos arriba. |
| 72 | `original_calls_weighted` | Cobertura original_calls_weighted según campo, consulta y estadística descritos arriba. |
| 73 | `original_calls_mean_cosine` | Cobertura original_calls_mean_cosine según campo, consulta y estadística descritos arriba. |
| 74 | `original_calls_log_words` | Cobertura original_calls_log_words según campo, consulta y estadística descritos arriba. |
| 75 | `original_returns_exact` | Cobertura original_returns_exact según campo, consulta y estadística descritos arriba. |
| 76 | `original_returns_mean` | Cobertura original_returns_mean según campo, consulta y estadística descritos arriba. |
| 77 | `original_returns_min` | Cobertura original_returns_min según campo, consulta y estadística descritos arriba. |
| 78 | `original_returns_p25` | Cobertura original_returns_p25 según campo, consulta y estadística descritos arriba. |
| 79 | `original_returns_above50` | Cobertura original_returns_above50 según campo, consulta y estadística descritos arriba. |
| 80 | `original_returns_above70` | Cobertura original_returns_above70 según campo, consulta y estadística descritos arriba. |
| 81 | `original_returns_weighted` | Cobertura original_returns_weighted según campo, consulta y estadística descritos arriba. |
| 82 | `original_returns_mean_cosine` | Cobertura original_returns_mean_cosine según campo, consulta y estadística descritos arriba. |
| 83 | `original_returns_log_words` | Cobertura original_returns_log_words según campo, consulta y estadística descritos arriba. |
| 84 | `original_path_exact` | Cobertura original_path_exact según campo, consulta y estadística descritos arriba. |
| 85 | `original_path_mean` | Cobertura original_path_mean según campo, consulta y estadística descritos arriba. |
| 86 | `original_path_min` | Cobertura original_path_min según campo, consulta y estadística descritos arriba. |
| 87 | `original_path_p25` | Cobertura original_path_p25 según campo, consulta y estadística descritos arriba. |
| 88 | `original_path_above50` | Cobertura original_path_above50 según campo, consulta y estadística descritos arriba. |
| 89 | `original_path_above70` | Cobertura original_path_above70 según campo, consulta y estadística descritos arriba. |
| 90 | `original_path_weighted` | Cobertura original_path_weighted según campo, consulta y estadística descritos arriba. |
| 91 | `original_path_mean_cosine` | Cobertura original_path_mean_cosine según campo, consulta y estadística descritos arriba. |
| 92 | `original_path_log_words` | Cobertura original_path_log_words según campo, consulta y estadística descritos arriba. |
| 93 | `original_all_exact` | Cobertura original_all_exact según campo, consulta y estadística descritos arriba. |
| 94 | `original_all_mean` | Cobertura original_all_mean según campo, consulta y estadística descritos arriba. |
| 95 | `original_all_min` | Cobertura original_all_min según campo, consulta y estadística descritos arriba. |
| 96 | `original_all_p25` | Cobertura original_all_p25 según campo, consulta y estadística descritos arriba. |
| 97 | `original_all_above50` | Cobertura original_all_above50 según campo, consulta y estadística descritos arriba. |
| 98 | `original_all_above70` | Cobertura original_all_above70 según campo, consulta y estadística descritos arriba. |
| 99 | `original_all_weighted` | Cobertura original_all_weighted según campo, consulta y estadística descritos arriba. |
| 100 | `original_all_mean_cosine` | Cobertura original_all_mean_cosine según campo, consulta y estadística descritos arriba. |
| 101 | `original_all_log_words` | Cobertura original_all_log_words según campo, consulta y estadística descritos arriba. |
| 102 | `piece_identity_exact` | Cobertura piece_identity_exact según campo, consulta y estadística descritos arriba. |
| 103 | `piece_identity_stem` | Cobertura piece_identity_stem según campo, consulta y estadística descritos arriba. |
| 104 | `piece_identity_mean` | Cobertura piece_identity_mean según campo, consulta y estadística descritos arriba. |
| 105 | `piece_identity_min` | Cobertura piece_identity_min según campo, consulta y estadística descritos arriba. |
| 106 | `piece_identity_p25` | Cobertura piece_identity_p25 según campo, consulta y estadística descritos arriba. |
| 107 | `piece_identity_above50` | Cobertura piece_identity_above50 según campo, consulta y estadística descritos arriba. |
| 108 | `piece_identity_above70` | Cobertura piece_identity_above70 según campo, consulta y estadística descritos arriba. |
| 109 | `piece_identity_weighted` | Cobertura piece_identity_weighted según campo, consulta y estadística descritos arriba. |
| 110 | `piece_identity_mean_cosine` | Cobertura piece_identity_mean_cosine según campo, consulta y estadística descritos arriba. |
| 111 | `piece_identity_log_words` | Cobertura piece_identity_log_words según campo, consulta y estadística descritos arriba. |
| 112 | `piece_signature_exact` | Cobertura piece_signature_exact según campo, consulta y estadística descritos arriba. |
| 113 | `piece_signature_stem` | Cobertura piece_signature_stem según campo, consulta y estadística descritos arriba. |
| 114 | `piece_signature_mean` | Cobertura piece_signature_mean según campo, consulta y estadística descritos arriba. |
| 115 | `piece_signature_min` | Cobertura piece_signature_min según campo, consulta y estadística descritos arriba. |
| 116 | `piece_signature_p25` | Cobertura piece_signature_p25 según campo, consulta y estadística descritos arriba. |
| 117 | `piece_signature_above50` | Cobertura piece_signature_above50 según campo, consulta y estadística descritos arriba. |
| 118 | `piece_signature_above70` | Cobertura piece_signature_above70 según campo, consulta y estadística descritos arriba. |
| 119 | `piece_signature_weighted` | Cobertura piece_signature_weighted según campo, consulta y estadística descritos arriba. |
| 120 | `piece_signature_mean_cosine` | Cobertura piece_signature_mean_cosine según campo, consulta y estadística descritos arriba. |
| 121 | `piece_signature_log_words` | Cobertura piece_signature_log_words según campo, consulta y estadística descritos arriba. |
| 122 | `piece_documentation_exact` | Cobertura piece_documentation_exact según campo, consulta y estadística descritos arriba. |
| 123 | `piece_documentation_stem` | Cobertura piece_documentation_stem según campo, consulta y estadística descritos arriba. |
| 124 | `piece_documentation_mean` | Cobertura piece_documentation_mean según campo, consulta y estadística descritos arriba. |
| 125 | `piece_documentation_min` | Cobertura piece_documentation_min según campo, consulta y estadística descritos arriba. |
| 126 | `piece_documentation_p25` | Cobertura piece_documentation_p25 según campo, consulta y estadística descritos arriba. |
| 127 | `piece_documentation_above50` | Cobertura piece_documentation_above50 según campo, consulta y estadística descritos arriba. |
| 128 | `piece_documentation_above70` | Cobertura piece_documentation_above70 según campo, consulta y estadística descritos arriba. |
| 129 | `piece_documentation_weighted` | Cobertura piece_documentation_weighted según campo, consulta y estadística descritos arriba. |
| 130 | `piece_documentation_mean_cosine` | Cobertura piece_documentation_mean_cosine según campo, consulta y estadística descritos arriba. |
| 131 | `piece_documentation_log_words` | Cobertura piece_documentation_log_words según campo, consulta y estadística descritos arriba. |
| 132 | `piece_executable_exact` | Cobertura piece_executable_exact según campo, consulta y estadística descritos arriba. |
| 133 | `piece_executable_stem` | Cobertura piece_executable_stem según campo, consulta y estadística descritos arriba. |
| 134 | `piece_executable_mean` | Cobertura piece_executable_mean según campo, consulta y estadística descritos arriba. |
| 135 | `piece_executable_min` | Cobertura piece_executable_min según campo, consulta y estadística descritos arriba. |
| 136 | `piece_executable_p25` | Cobertura piece_executable_p25 según campo, consulta y estadística descritos arriba. |
| 137 | `piece_executable_above50` | Cobertura piece_executable_above50 según campo, consulta y estadística descritos arriba. |
| 138 | `piece_executable_above70` | Cobertura piece_executable_above70 según campo, consulta y estadística descritos arriba. |
| 139 | `piece_executable_weighted` | Cobertura piece_executable_weighted según campo, consulta y estadística descritos arriba. |
| 140 | `piece_executable_mean_cosine` | Cobertura piece_executable_mean_cosine según campo, consulta y estadística descritos arriba. |
| 141 | `piece_executable_log_words` | Cobertura piece_executable_log_words según campo, consulta y estadística descritos arriba. |
| 142 | `piece_calls_exact` | Cobertura piece_calls_exact según campo, consulta y estadística descritos arriba. |
| 143 | `piece_calls_stem` | Cobertura piece_calls_stem según campo, consulta y estadística descritos arriba. |
| 144 | `piece_calls_mean` | Cobertura piece_calls_mean según campo, consulta y estadística descritos arriba. |
| 145 | `piece_calls_min` | Cobertura piece_calls_min según campo, consulta y estadística descritos arriba. |
| 146 | `piece_calls_p25` | Cobertura piece_calls_p25 según campo, consulta y estadística descritos arriba. |
| 147 | `piece_calls_above50` | Cobertura piece_calls_above50 según campo, consulta y estadística descritos arriba. |
| 148 | `piece_calls_above70` | Cobertura piece_calls_above70 según campo, consulta y estadística descritos arriba. |
| 149 | `piece_calls_weighted` | Cobertura piece_calls_weighted según campo, consulta y estadística descritos arriba. |
| 150 | `piece_calls_mean_cosine` | Cobertura piece_calls_mean_cosine según campo, consulta y estadística descritos arriba. |
| 151 | `piece_calls_log_words` | Cobertura piece_calls_log_words según campo, consulta y estadística descritos arriba. |
| 152 | `piece_returns_exact` | Cobertura piece_returns_exact según campo, consulta y estadística descritos arriba. |
| 153 | `piece_returns_stem` | Cobertura piece_returns_stem según campo, consulta y estadística descritos arriba. |
| 154 | `piece_returns_mean` | Cobertura piece_returns_mean según campo, consulta y estadística descritos arriba. |
| 155 | `piece_returns_min` | Cobertura piece_returns_min según campo, consulta y estadística descritos arriba. |
| 156 | `piece_returns_p25` | Cobertura piece_returns_p25 según campo, consulta y estadística descritos arriba. |
| 157 | `piece_returns_above50` | Cobertura piece_returns_above50 según campo, consulta y estadística descritos arriba. |
| 158 | `piece_returns_above70` | Cobertura piece_returns_above70 según campo, consulta y estadística descritos arriba. |
| 159 | `piece_returns_weighted` | Cobertura piece_returns_weighted según campo, consulta y estadística descritos arriba. |
| 160 | `piece_returns_mean_cosine` | Cobertura piece_returns_mean_cosine según campo, consulta y estadística descritos arriba. |
| 161 | `piece_returns_log_words` | Cobertura piece_returns_log_words según campo, consulta y estadística descritos arriba. |
| 162 | `piece_path_exact` | Cobertura piece_path_exact según campo, consulta y estadística descritos arriba. |
| 163 | `piece_path_stem` | Cobertura piece_path_stem según campo, consulta y estadística descritos arriba. |
| 164 | `piece_path_mean` | Cobertura piece_path_mean según campo, consulta y estadística descritos arriba. |
| 165 | `piece_path_min` | Cobertura piece_path_min según campo, consulta y estadística descritos arriba. |
| 166 | `piece_path_p25` | Cobertura piece_path_p25 según campo, consulta y estadística descritos arriba. |
| 167 | `piece_path_above50` | Cobertura piece_path_above50 según campo, consulta y estadística descritos arriba. |
| 168 | `piece_path_above70` | Cobertura piece_path_above70 según campo, consulta y estadística descritos arriba. |
| 169 | `piece_path_weighted` | Cobertura piece_path_weighted según campo, consulta y estadística descritos arriba. |
| 170 | `piece_path_mean_cosine` | Cobertura piece_path_mean_cosine según campo, consulta y estadística descritos arriba. |
| 171 | `piece_path_log_words` | Cobertura piece_path_log_words según campo, consulta y estadística descritos arriba. |
| 172 | `piece_all_exact` | Cobertura piece_all_exact según campo, consulta y estadística descritos arriba. |
| 173 | `piece_all_stem` | Cobertura piece_all_stem según campo, consulta y estadística descritos arriba. |
| 174 | `piece_all_mean` | Cobertura piece_all_mean según campo, consulta y estadística descritos arriba. |
| 175 | `piece_all_min` | Cobertura piece_all_min según campo, consulta y estadística descritos arriba. |
| 176 | `piece_all_p25` | Cobertura piece_all_p25 según campo, consulta y estadística descritos arriba. |
| 177 | `piece_all_above50` | Cobertura piece_all_above50 según campo, consulta y estadística descritos arriba. |
| 178 | `piece_all_above70` | Cobertura piece_all_above70 según campo, consulta y estadística descritos arriba. |
| 179 | `piece_all_weighted` | Cobertura piece_all_weighted según campo, consulta y estadística descritos arriba. |
| 180 | `piece_all_mean_cosine` | Cobertura piece_all_mean_cosine según campo, consulta y estadística descritos arriba. |
| 181 | `piece_all_log_words` | Cobertura piece_all_log_words según campo, consulta y estadística descritos arriba. |
| 182 | `declaration_identity_exact` | Cobertura declaration_identity_exact según campo, consulta y estadística descritos arriba. |
| 183 | `declaration_identity_stem` | Cobertura declaration_identity_stem según campo, consulta y estadística descritos arriba. |
| 184 | `declaration_identity_mean` | Cobertura declaration_identity_mean según campo, consulta y estadística descritos arriba. |
| 185 | `declaration_identity_min` | Cobertura declaration_identity_min según campo, consulta y estadística descritos arriba. |
| 186 | `declaration_identity_p25` | Cobertura declaration_identity_p25 según campo, consulta y estadística descritos arriba. |
| 187 | `declaration_identity_above50` | Cobertura declaration_identity_above50 según campo, consulta y estadística descritos arriba. |
| 188 | `declaration_identity_above70` | Cobertura declaration_identity_above70 según campo, consulta y estadística descritos arriba. |
| 189 | `declaration_identity_weighted` | Cobertura declaration_identity_weighted según campo, consulta y estadística descritos arriba. |
| 190 | `declaration_identity_mean_cosine` | Cobertura declaration_identity_mean_cosine según campo, consulta y estadística descritos arriba. |
| 191 | `declaration_identity_log_words` | Cobertura declaration_identity_log_words según campo, consulta y estadística descritos arriba. |
| 192 | `declaration_signature_exact` | Cobertura declaration_signature_exact según campo, consulta y estadística descritos arriba. |
| 193 | `declaration_signature_stem` | Cobertura declaration_signature_stem según campo, consulta y estadística descritos arriba. |
| 194 | `declaration_signature_mean` | Cobertura declaration_signature_mean según campo, consulta y estadística descritos arriba. |
| 195 | `declaration_signature_min` | Cobertura declaration_signature_min según campo, consulta y estadística descritos arriba. |
| 196 | `declaration_signature_p25` | Cobertura declaration_signature_p25 según campo, consulta y estadística descritos arriba. |
| 197 | `declaration_signature_above50` | Cobertura declaration_signature_above50 según campo, consulta y estadística descritos arriba. |
| 198 | `declaration_signature_above70` | Cobertura declaration_signature_above70 según campo, consulta y estadística descritos arriba. |
| 199 | `declaration_signature_weighted` | Cobertura declaration_signature_weighted según campo, consulta y estadística descritos arriba. |
| 200 | `declaration_signature_mean_cosine` | Cobertura declaration_signature_mean_cosine según campo, consulta y estadística descritos arriba. |
| 201 | `declaration_signature_log_words` | Cobertura declaration_signature_log_words según campo, consulta y estadística descritos arriba. |
| 202 | `declaration_documentation_exact` | Cobertura declaration_documentation_exact según campo, consulta y estadística descritos arriba. |
| 203 | `declaration_documentation_stem` | Cobertura declaration_documentation_stem según campo, consulta y estadística descritos arriba. |
| 204 | `declaration_documentation_mean` | Cobertura declaration_documentation_mean según campo, consulta y estadística descritos arriba. |
| 205 | `declaration_documentation_min` | Cobertura declaration_documentation_min según campo, consulta y estadística descritos arriba. |
| 206 | `declaration_documentation_p25` | Cobertura declaration_documentation_p25 según campo, consulta y estadística descritos arriba. |
| 207 | `declaration_documentation_above50` | Cobertura declaration_documentation_above50 según campo, consulta y estadística descritos arriba. |
| 208 | `declaration_documentation_above70` | Cobertura declaration_documentation_above70 según campo, consulta y estadística descritos arriba. |
| 209 | `declaration_documentation_weighted` | Cobertura declaration_documentation_weighted según campo, consulta y estadística descritos arriba. |
| 210 | `declaration_documentation_mean_cosine` | Cobertura declaration_documentation_mean_cosine según campo, consulta y estadística descritos arriba. |
| 211 | `declaration_documentation_log_words` | Cobertura declaration_documentation_log_words según campo, consulta y estadística descritos arriba. |
| 212 | `declaration_executable_exact` | Cobertura declaration_executable_exact según campo, consulta y estadística descritos arriba. |
| 213 | `declaration_executable_stem` | Cobertura declaration_executable_stem según campo, consulta y estadística descritos arriba. |
| 214 | `declaration_executable_mean` | Cobertura declaration_executable_mean según campo, consulta y estadística descritos arriba. |
| 215 | `declaration_executable_min` | Cobertura declaration_executable_min según campo, consulta y estadística descritos arriba. |
| 216 | `declaration_executable_p25` | Cobertura declaration_executable_p25 según campo, consulta y estadística descritos arriba. |
| 217 | `declaration_executable_above50` | Cobertura declaration_executable_above50 según campo, consulta y estadística descritos arriba. |
| 218 | `declaration_executable_above70` | Cobertura declaration_executable_above70 según campo, consulta y estadística descritos arriba. |
| 219 | `declaration_executable_weighted` | Cobertura declaration_executable_weighted según campo, consulta y estadística descritos arriba. |
| 220 | `declaration_executable_mean_cosine` | Cobertura declaration_executable_mean_cosine según campo, consulta y estadística descritos arriba. |
| 221 | `declaration_executable_log_words` | Cobertura declaration_executable_log_words según campo, consulta y estadística descritos arriba. |
| 222 | `declaration_calls_exact` | Cobertura declaration_calls_exact según campo, consulta y estadística descritos arriba. |
| 223 | `declaration_calls_stem` | Cobertura declaration_calls_stem según campo, consulta y estadística descritos arriba. |
| 224 | `declaration_calls_mean` | Cobertura declaration_calls_mean según campo, consulta y estadística descritos arriba. |
| 225 | `declaration_calls_min` | Cobertura declaration_calls_min según campo, consulta y estadística descritos arriba. |
| 226 | `declaration_calls_p25` | Cobertura declaration_calls_p25 según campo, consulta y estadística descritos arriba. |
| 227 | `declaration_calls_above50` | Cobertura declaration_calls_above50 según campo, consulta y estadística descritos arriba. |
| 228 | `declaration_calls_above70` | Cobertura declaration_calls_above70 según campo, consulta y estadística descritos arriba. |
| 229 | `declaration_calls_weighted` | Cobertura declaration_calls_weighted según campo, consulta y estadística descritos arriba. |
| 230 | `declaration_calls_mean_cosine` | Cobertura declaration_calls_mean_cosine según campo, consulta y estadística descritos arriba. |
| 231 | `declaration_calls_log_words` | Cobertura declaration_calls_log_words según campo, consulta y estadística descritos arriba. |
| 232 | `declaration_returns_exact` | Cobertura declaration_returns_exact según campo, consulta y estadística descritos arriba. |
| 233 | `declaration_returns_stem` | Cobertura declaration_returns_stem según campo, consulta y estadística descritos arriba. |
| 234 | `declaration_returns_mean` | Cobertura declaration_returns_mean según campo, consulta y estadística descritos arriba. |
| 235 | `declaration_returns_min` | Cobertura declaration_returns_min según campo, consulta y estadística descritos arriba. |
| 236 | `declaration_returns_p25` | Cobertura declaration_returns_p25 según campo, consulta y estadística descritos arriba. |
| 237 | `declaration_returns_above50` | Cobertura declaration_returns_above50 según campo, consulta y estadística descritos arriba. |
| 238 | `declaration_returns_above70` | Cobertura declaration_returns_above70 según campo, consulta y estadística descritos arriba. |
| 239 | `declaration_returns_weighted` | Cobertura declaration_returns_weighted según campo, consulta y estadística descritos arriba. |
| 240 | `declaration_returns_mean_cosine` | Cobertura declaration_returns_mean_cosine según campo, consulta y estadística descritos arriba. |
| 241 | `declaration_returns_log_words` | Cobertura declaration_returns_log_words según campo, consulta y estadística descritos arriba. |
| 242 | `declaration_path_exact` | Cobertura declaration_path_exact según campo, consulta y estadística descritos arriba. |
| 243 | `declaration_path_stem` | Cobertura declaration_path_stem según campo, consulta y estadística descritos arriba. |
| 244 | `declaration_path_mean` | Cobertura declaration_path_mean según campo, consulta y estadística descritos arriba. |
| 245 | `declaration_path_min` | Cobertura declaration_path_min según campo, consulta y estadística descritos arriba. |
| 246 | `declaration_path_p25` | Cobertura declaration_path_p25 según campo, consulta y estadística descritos arriba. |
| 247 | `declaration_path_above50` | Cobertura declaration_path_above50 según campo, consulta y estadística descritos arriba. |
| 248 | `declaration_path_above70` | Cobertura declaration_path_above70 según campo, consulta y estadística descritos arriba. |
| 249 | `declaration_path_weighted` | Cobertura declaration_path_weighted según campo, consulta y estadística descritos arriba. |
| 250 | `declaration_path_mean_cosine` | Cobertura declaration_path_mean_cosine según campo, consulta y estadística descritos arriba. |
| 251 | `declaration_path_log_words` | Cobertura declaration_path_log_words según campo, consulta y estadística descritos arriba. |
| 252 | `declaration_all_exact` | Cobertura declaration_all_exact según campo, consulta y estadística descritos arriba. |
| 253 | `declaration_all_stem` | Cobertura declaration_all_stem según campo, consulta y estadística descritos arriba. |
| 254 | `declaration_all_mean` | Cobertura declaration_all_mean según campo, consulta y estadística descritos arriba. |
| 255 | `declaration_all_min` | Cobertura declaration_all_min según campo, consulta y estadística descritos arriba. |
| 256 | `declaration_all_p25` | Cobertura declaration_all_p25 según campo, consulta y estadística descritos arriba. |
| 257 | `declaration_all_above50` | Cobertura declaration_all_above50 según campo, consulta y estadística descritos arriba. |
| 258 | `declaration_all_above70` | Cobertura declaration_all_above70 según campo, consulta y estadística descritos arriba. |
| 259 | `declaration_all_weighted` | Cobertura declaration_all_weighted según campo, consulta y estadística descritos arriba. |
| 260 | `declaration_all_mean_cosine` | Cobertura declaration_all_mean_cosine según campo, consulta y estadística descritos arriba. |
| 261 | `declaration_all_log_words` | Cobertura declaration_all_log_words según campo, consulta y estadística descritos arriba. |
