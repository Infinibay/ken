"""Publish the closed scoring investigation without rerunning or changing ranking."""
from pathlib import Path
from collections import Counter
import csv
import gzip
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / 'output/frozen/ranking-diagnostics-owned-v120'
sys.path[:0] = [str(FROZEN / 'src')]
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.numeric_ranker import NumericRanker

REPORT = ROOT / 'output/development/native-ranking-diagnostics-owned-report-v120'
OUT = ROOT / 'docs/validation/search-engine-top1-2026-10-14/scoring-internals'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def label(unit):
    entity = unit.get('entity') or {}
    return unit['path'] + ('::' + entity['qualname'] if entity.get('qualname') else '')


BASE = {
    'rrf': 'Suma de votos 1/(60+posición) de las familias de propuestas; no es probabilidad.',
    'cosine_identity': 'Similitud densa de identidad medida al recuperar candidatos; cero si falta esa señal.',
    'cosine_behavior': 'Similitud densa de comportamiento medida al recuperar candidatos; cero si falta.',
    'bm25f': 'log(1+máximo BM25F del owner entre sus pasajes recuperados).',
    **{f'bm25_{f}': 'log(1+BM25 del campo '+f+'); señal léxica de recuperación.'
       for f in ('body','documentation','identity','signature','path')},
    'role_match': '1 si el rol del primer pasaje coincide con el propósito interpretado; no prueba que sea definición y no consumidor.',
    'class': '1 si el owner puntuado es una clase; no significa que la consulta pida una clase.',
    'module': '1 si qualname del owner es nulo.',
    'log_lines': 'log(1+longitud máxima del entity_span de sus pasajes).',
    'name_overlap': 'Fracción de tokens distintos de la consulta presentes en el nombre cualificado.',
    'body_overlap': 'Máxima fracción de tokens distintos de consulta presentes en el body de un pasaje.',
    'is_exception': '1 si el nombre final contiene exception o error; heurística léxica.',
    'is_constructor': '1 si el nombre final es __init__, new o constructor.',
    'query_log_tokens': 'log(1+número de tokens distintos de la consulta original).',
    'query_identifier': '1 si interpret reconoce autoridad de búsqueda por identidad explícita.',
    'query_kind_class': '1 si la intención de identidad nombrada lleva kind=class. No representa todas las consultas descriptivas de clase.',
}
STATS = {
    'exact': 'fracción de términos distintos de consulta presentes literalmente en el campo',
    'stem': 'fracción de raíces Snowball distintas de consulta presentes en el campo',
    'mean': 'media del mejor producto escalar de cada término de consulta contra términos del campo',
    'min': 'mínimo de esos mejores productos: el término menos cubierto',
    'p25': 'percentil25 de esos mejores productos',
    'above50': 'fracción de términos de consulta con mejor producto >=0.5',
    'above70': 'fracción de términos de consulta con mejor producto >=0.7',
    'weighted': 'media de mejores productos ponderada por log(1+N/(1+df(t))) en el pool de owners',
    'mean_cosine': 'producto del vector de consulta con la media normalizada de vectores de términos distintos del campo',
    'log_words': 'log(1+número de términos distintos retenidos en el campo)',
}
FIELDS = {
    'identity': 'identidad/nombre del owner', 'signature': 'firma del owner',
    'documentation': 'documentación atribuida al owner', 'body': 'body original atribuido',
    'path': 'ruta', 'all': 'unión de campos con el orden de proyección registrado',
    'implementation': 'regiones propias desde implementation_start_line',
    'executable': 'líneas no vacías no reconocidas como comentarios por el filtro léxico',
    'comments': 'líneas reconocidas como comentarios por ese filtro',
    'calls': 'nombres extraídos por regex antes de un paréntesis; no destinos de llamadas resueltos',
    'returns': 'líneas ejecutables que contienen return/throw/raise/yield; no análisis de flujo',
}
SHAPES = {
    'log_executable_lines': 'log(1+líneas ejecutables léxicas propias)',
    'log_comment_lines': 'log(1+líneas de comentario léxicas propias)',
    'log_owned_lines': 'log(1+líneas en regiones atribuidas al owner)',
    'log_regions': 'log(1+número de pasajes/regiones únicos del owner)',
    'documentation_fraction': '1 - implementation_lines/max(1,owned_lines); no es una medida de calidad documental',
    'query_negation': '1 si la consulta expandida contiene not/without/never/no/sin; no resuelve el alcance de la negación',
    'query_test': '1 si interpret clasifica la consulta expandida como petición de tests',
}


def explain_feature(name):
    if name in BASE:
        return BASE[name]
    if name.startswith('code_') or name.startswith('view_'):
        stat = next(s for s in ('range_relative','reciprocal_rank','to_max','raw') if name.endswith('_'+s))
        source = name[:-len(stat)-1]
        formula = {'raw':'producto escalar medido', 'to_max':'valor - máximo del pool (no cociente)',
            'range_relative':'(valor-mínimo)/max(1e-9,máximo-mínimo)',
            'reciprocal_rank':'1/posición descendente estable dentro del pool'}[stat]
        return source + ': ' + formula + '.'
    if name.endswith('_relative') and name[:-9] in BASE:
        return 'Normalización por rango de '+name[:-9]+': (x-min)/max(1e-9,max-min) entre candidatos.'
    if name.endswith('_rank') and name[:-5] in BASE:
        return '1/posición descendente estable según '+name[:-5]+'. No es el puesto final.'
    if name.startswith('expanded_kind_'):
        return '1 si el tipo canónico del owner es '+name[len('expanded_kind_'):]+'.'
    if name.startswith('expanded_op_'):
        return 'log(1+apariciones léxicas de '+name[len('expanded_op_'):]+' en executable).'
    if name.startswith('expanded_'):
        tail = name[len('expanded_'):]
        if tail in SHAPES:
            return SHAPES[tail]+'.'
        query = 'consulta expandida'
    else:
        tail = name; query = 'consulta original'
    for field in sorted(FIELDS, key=len, reverse=True):
        if tail.startswith(field+'_') and tail[len(field)+1:] in STATS:
            return query+', '+FIELDS[field]+': '+STATS[tail[len(field)+1:]]+'.'
    raise ValueError('Feature without a documented meaning: '+name)


NOTES = {
 'vp-cs-001':'Consumidor/generador CodeGen frente a la representación _Code. La clase elegida hereda el score de CodeGen.object.',
 'vp-cs-005':'CodeGen.try construye/gestiona un bloque; la pregunta pide la clase Try. El mejor método promueve a su clase contenedora.',
 'vp-mf-047':'Coincidencia de tipos JSON Schema frente a implementación de serialización JTD; el prior de recuperación favorece al módulo de tipos.',
 'vp-mf-077':'Esquema JSON de datos frente al código del validador. El aceptable queda fuera del top10; reordenar esos diez no lo recupera.',
 'vp-mf-080':'Comprobaciones de dependencias de propiedades frente a límites de cantidad de propiedades; comportamientos cercanos.',
 'vp-mf-083':'KeywordCxt.subschema es el punto consumidor/agregador; el módulo solicitado contiene la implementación específica de contexto.',
 'vp-cs-022':'asdict usa el filtro; include construye el filtro solicitado.',
 'vp-cs-024':'Constructor Converter frente a composición pipe; tipo relacionado frente a operación pedida.',
 'vp-mf-037':'Módulo de pruebas de tipado que usa la API frente al módulo que define decorador y campos.',
 'vp-cs-036':'unquote frente a unquote_to_bytes: el tipo de salida bytes distingue la operación correcta.',
 'vp-cs-037':'Constructor del lector frente al método read; identidad de clase correcta, operación incorrecta.',
 'vp-mf-065':'Aplicación/consumidor HTML frente al archivo de la biblioteca Table.',
 'vp-cs-041':'CSVParser frente a CSVRecord; el contrato solicitado combina Iterable<String>, acceso a campos y estado transient.',
 'vp-cs-044':'get sobrecargado frente a putIn; lectura frente a transferencia al mapa solicitado.',
 'vp-cs-045':'validate frente al setter Builder.setDelimiter; validación general frente a la operación concreta.',
 'vp-mf-100':'Método que configura una política frente al enum que declara los modos de esa política.',
 'vp-cs-055':'StreamInterceptor frente al buffer anidado RewindableByteArrayOutputStream; consumidor frente a estado/operaciones del buffer.',
 'vp-mf-089':'Visitor consumidor del ordenamiento frente a la interfaz MethodOrderer que define el contrato.',
 'vp-mf-091':'TempDirectory consume la configuración frente a TempDir, que declara la API de inyección.',
 'vp-mf-092':'Evaluador de la condición frente a la anotación que la declara.',
 'vp-mf-095':'Helper ProcessStarter frente al entrypoint ConsoleLauncher. Aceptable en posición73, fuera del top10.',
 'vp-cs-065':'_Parser delega en el renderer; la pregunta pide la clase que emite HTML.',
 'vp-cs-066':'Renderer HTML frente a TextRenderer que descarta markup y conserva texto/raw.',
 'vp-mf-084':'Constructor Lexer que consume reglas frente al archivo que define las reglas.',
 'vp-mf-086':'walkTokens consumidor frente al archivo de tipos/representación Token.',
 'vp-cs-086':'Pylock.to_dict consumidor frente a _toml_dict_factory, que decide la construcción del diccionario.',
 'vp-mf-006':'Generador tasks/licenses frente al módulo de datos SPDX que necesita la consulta.',
 'vp-mf-055':'Operaciones de rangos de producción frente al benchmark de resolución solicitado explícitamente.',
 'vp-mf-008':'ExceptionInfo.__repr__ consumidor frente al módulo saferepr que realiza el formateo seguro.',
 'vp-mf-013':'Carga general de configuración/conftest frente al módulo cacheprovider pedido; revisar las condiciones concretas de la consulta.',
 'vp-mf-014':'Helper genérico de importación frente al módulo doctest solicitado; aceptable en posición18.',
 'vp-mf-057':'LFPlugin y StepwisePlugin comparten hook; se confunden comportamientos cercanos dentro de la colección.',
}


def main():
    verify_frozen_source(FROZEN)
    backup = json.loads((ROOT/'output/checkpoints/native-ranking-diagnostics-v120/MANIFEST.json').read_text())
    for name in ('summary.json','failures.jsonl'):
        path = REPORT/name
        pin = next(r for r in backup['files'] if r['path']==str(path.relative_to(ROOT)))
        assert sha(path)==pin['uncompressed_sha256']
    summary = json.loads((REPORT/'summary.json').read_text())
    failures = [json.loads(line) for line in (REPORT/'failures.jsonl').read_text().splitlines()]
    assert len(failures)==32 and sum(r['correct_piece_rank']<=10 for r in failures)==29
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'cases').mkdir(exist_ok=True)
    models={}
    for repo,pin in summary['pins']['models'].items():
        path=ROOT/'output/analysis/source7-context-views-ranking-v69/contract_body251'/(repo+'-numeric.json')
        assert sha(path)==pin['sha256']
        models[repo]=NumericRanker.from_dict(json.loads(path.read_text()))
    names=next(iter(models.values())).features
    assert len(names)==251 and all(model.features==names for model in models.values())
    glossary=['# Las251 señales del ranking de owners','',
        'Orden exacto del vector del modelo v69/v120. El sentido de una señal no implica que siempre aumente el score: los árboles pueden usarla de forma condicional.',
        '', '| Índice0-based | Señal | Qué mide y cómo |','|---:|---|---|']
    for index,name in enumerate(names):glossary.append(f'| {index} | `{name}` | {explain_feature(name)} |')
    (OUT/'FEATURES-251.md').write_text('\n'.join(glossary)+'\n')
    index=['# Todos los fallos nativos de top1','',
        'Snapshot cerrado v120:32fallos;29con aceptable en top10. Cada ficha contiene251valores por candidato, el margen atribuido de todos los árboles, señales crudas y la identidad del owner que representa a la pieza.',
        '', '| Caso | Tipo | Posición aceptable | Margen elegido-aceptable | Ficha |','|---|---|---:|---:|---|']
    with (OUT/'pair-feature-values.csv').open('w',newline='') as stream:
        writer=csv.writer(stream,lineterminator='\n');writer.writerow(['case','kind','acceptable_rank','feature_index','feature','selected','acceptable','difference','first_divergent_tree_margin'])
        for row in failures:
            pair=row['comparison'];numeric=pair['numeric'];model=models[row['repo_id']]
            actual=model.explain_pair(pair['left']['feature_values'],pair['right']['feature_values'])
            assert actual==numeric
            index.append(f'| {row["id"]} | {row["target_kind"]} | {row["correct_piece_rank"]} | {numeric["margin"]:.9g} | [detalle](cases/{row["id"]}.md) |')
            doc=[f'# {row["id"]} — {row["target_kind"]}', '',row['query'],'',
                '**Pieza elegida:** `'+label(row['selected']['unit'])+'`',
                '**Pieza aceptable:** `'+label(row['best_acceptable']['unit'])+f'` — posición{row["correct_piece_rank"]}.','',
                'Owner representante elegido: `'+str(pair['left']['entity']['qualname'])+f'`; puesto de owner{pair["left"]["rank"]}.',
                'Owner representante aceptable: `'+str(pair['right']['entity']['qualname'])+f'`; puesto de owner{pair["right"]["rank"]}.','',
                '**Interpretación del caso (hipótesis de dominio):** '+NOTES[row['id']],'',
                '**Mecanismo numérico comprobado:** orden por `'+pair['ordering_reason']+'`; '
                f'score elegido={numeric["left_score"]!r}; aceptable={numeric["right_score"]!r}; margen={numeric["margin"]!r}.',
                f'Residuo de acumulación flotante={numeric["rounding_residual"]!r}.', '',
                'Los márgenes de árboles se agrupan por su primera rama divergente. Signo positivo favorece al elegido y negativo al aceptable. La suma más el residuo reproduce el margen; no son pesos lineales ni efectos causales aislados. Los caminos completos están en forest-pairs.jsonl.gz.', '',
                '| Señal | Elegido | Aceptable | Diferencia de valor | Margen de árboles |','|---|---:|---:|---:|---:|']
            for i,name in enumerate(names):
                a,b=pair['left']['feature_values'][i],pair['right']['feature_values'][i]
                delta=numeric['branch_margin_by_feature'].get(name,0.)
                writer.writerow([row['id'],row['target_kind'],row['correct_piece_rank'],i,name,repr(a),repr(b),repr(a-b),repr(delta)])
                doc.append(f'| `{name}` | {a!r} | {b!r} | {a-b!r} | {delta!r} |')
            doc+=['','## Señales crudas de recuperación','',
                  'Estos valores preceden al vector; por ejemplo BM25 pasa por log1p. No sumarlos al score del bosque.','',
                  '| Señal | Elegido | Aceptable |','|---|---:|---:|']
            for name in sorted(pair['left']['signals'].keys()|pair['right']['signals'].keys()):
                doc.append(f'| `{name}` | {pair["left"]["signals"].get(name,"ausente")} | {pair["right"]["signals"].get(name,"ausente")} |')
            (OUT/'cases'/(row['id']+'.md')).write_text('\n'.join(doc)+'\n')
    (OUT/'CASES.md').write_text('\n'.join(index)+'\n')
    data=(REPORT/'failures.jsonl').read_bytes()
    (OUT/'forest-pairs.jsonl.gz').write_bytes(gzip.compress(data,compresslevel=6,mtime=0))
    assert gzip.decompress((OUT/'forest-pairs.jsonl.gz').read_bytes())==data
    manifest={'scope':'32 already exposed development failures; all251 owner values, actual tree paths and raw signals; no private acceptance',
        'producer_sha256':sha(__file__),'source_receipt':verify_frozen_source(FROZEN),
        'source_summary_sha256':sha(REPORT/'summary.json'),'source_failures_sha256':sha(REPORT/'failures.jsonl'),
        'cases':32,'cases_with_correct_in_top10':29,'feature_pairs':32*251,
        'positions':dict(Counter(r['correct_piece_rank'] for r in failures)),
        'files':{str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and
            (p.parent.name=='cases' or p.name in {'FEATURES-251.md','CASES.md','pair-feature-values.csv','forest-pairs.jsonl.gz'})}}
    (OUT/'VALUES-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({k:manifest[k] for k in ('cases','cases_with_correct_in_top10','feature_pairs','source_receipt')}))


if __name__=='__main__':main()
