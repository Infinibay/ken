"""Explain the actual v126 piece decisions, reusing only already exposed labels."""
from pathlib import Path
import csv
import gzip
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
FROZEN=ROOT/'output/frozen/piece-path-identity-v126'
sys.path[:0]=[str(FROZEN/'src'),str(FROZEN/'experiments/search-engine')]
import numpy as np
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.piece_ranking import PIECE_FEATURES
from verifiable_grading import identity_hit

OUT=ROOT/'docs/validation/search-engine-top1-2026-10-14/scoring-internals'
CONTROL=ROOT/'output/development/piece-path-identity-control-v126'
CAPTURE=ROOT/'output/development/whole-piece-features-v123'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rows(path):return [json.loads(line) for line in Path(path).read_text().splitlines()]
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))


SCALARS={
 'native_score':'Score del mejor miembro recuperado de esta pieza.',
 'native_to_best':'Score anterior menos el score del primer miembro de la primera pieza nativa.',
 'native_rank':'1/posición de la pieza en el top10 nativo, antes del nuevo bosque.',
 'member_log_count':'log(1+número de owners propios de la pieza).',
 'matched_log_count':'log(1+número de miembros recuperados en el pool).',
 'matched_fraction':'Miembros recuperados / miembros propios de la pieza.',
 'member_score_mean3':'Media de los scores de hasta tres mejores miembros recuperados.',
 'member_score_gap':'Score del mejor miembro menos el segundo; cero si sólo hay uno.',
 'declaration_present':'Hay descripción de la declaración canónica (clase/símbolo o owner global del archivo).',
 'declaration_in_matches':'La declaración, además de existir, apareció entre las propuestas.',
 'declaration_score_to_best':'Score de declaración recuperada menos mejor miembro;0 más flag si no apareció.',
 'log_owned_lines':'log(1+suma de líneas propias de los miembros).',
 'log_executable_lines':'log(1+suma de líneas ejecutables léxicas de los miembros).',
 'documentation_fraction':'1 - executable_lines/max(1,owned_lines); aproximación léxica, distinta de la señal antigua.',
 'test_path':'Ruta con componente test/tests/typing_tests/platform-tests/spec/specs en v123.',
 'data_file':'Extensión json/yaml/yml/toml.',
 'request_tests':'Propósito público explícito tests; auto no se reclasifica en esta versión.',
 'request_documentation':'Propósito público explícito documentation.',
}


def main():
    source=verify_frozen_source(FROZEN)
    registration=json.loads((CONTROL/'registration.json').read_text())
    assert registration['status']=='ALL200 repository-excluded orders closed'
    assert sha(CONTROL/'answers.jsonl')==registration['answers_sha256']
    feature_reg=json.loads((CAPTURE/'registration.json').read_text())
    assert sha(CAPTURE/'registration.json')==registration['feature_capture_sha256']
    assert feature_reg['features']==list(PIECE_FEATURES)
    original={r['id']:r for r in rows(ROOT/'output/development/native-ranking-diagnostics-owned-report-v120/failures.jsonl')}
    answers={r['id']:r for r in rows(CONTROL/'answers.jsonl')};assert len(answers)==200
    cases={r['id']:r for r in rows(ROOT/'output/development/verifiable-pieces-v98-public/cases.jsonl')}
    groups={};matrices={};models={}
    for repo,pins in feature_reg['closed'].items():
        assert all(sha(CAPTURE/repo/name)==digest for name,digest in pins.items())
        data=np.load(CAPTURE/repo/'features.npz',allow_pickle=False)
        candidates=rows(CAPTURE/repo/'candidates.jsonl')
        for i,row in enumerate(candidates):groups.setdefault(row['id'],{})[canonical(row['unit'])]=i
        matrices[repo]=data['x']
        pin=next(f for f in registration['folds'] if f['held_out']==repo)
        path=CONTROL/(repo+'-numeric.json');assert sha(path)==pin['model_sha256']
        models[repo]=NumericRanker.from_dict(json.loads(path.read_text()))
    glossary=['# Las262 señales del candidato de piezas v126','',
      'Este bosque sólo se aplica a clase/módulo/archivo. Símbolos mantienen su orden nativo. No confundir estas columnas con las251 del bosque anterior.','',
      'Prefijos: original = consulta original contra todos los miembros; piece = consulta expandida contra todos los miembros; declaration = consulta expandida contra la declaración propia. Los campos son identity/signature/documentation/executable/calls/returns/path/all. Se deduplican textos y limitan a4096 términos por campo. Las estadísticas exact/stem/mean/min/p25/above50/above70/weighted/mean_cosine/log_words conservan las fórmulas de FEATURES-251.md; la rareza aquí se calcula entre las diez piezas, no entre owners.','',
      '| Índice0-based | Señal | Significado |','|---:|---|---|']
    for i,name in enumerate(PIECE_FEATURES):
        if name in SCALARS:definition=SCALARS[name]
        elif name.startswith('request_'):definition='1 si la pieza solicitada es '+name[8:]+'.'
        elif name.startswith('declaration_kind_'):definition='1 si el tipo canónico de la declaración es '+name[17:]+'.'
        else:definition='Cobertura '+name+' según campo, consulta y estadística descritos arriba.'
        glossary.append(f'| {i} | `{name}` | {definition} |')
    (OUT/'PIECE-FEATURES-262.md').write_text('\n'.join(glossary)+'\n')
    (OUT/'piece-cases').mkdir(exist_ok=True)
    index=['# Fallos restantes con el candidato de piezas v126','',
      '175/200 correctos. Los25errores siguientes son un subconjunto de los32fallos nativos: no hay pérdidas frente al baseline. Hay22aceptables en top10. De esos22,7son símbolos deliberadamente sin nuevo ranking y15decisiones del bosque de piezas. Otros3aceptables están fuera de la ventana top10.','',
      '| Caso | Tipo | Estado | Evidencia |','|---|---|---|---|']
    complete=[];counts={'remaining':0,'piece_numeric_pairs':0,'unchanged_symbols':0,'outside_top10':0}
    with (OUT/'piece-pair-feature-values.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['case','feature_index','feature','selected','acceptable','difference','first_divergent_tree_margin'])
        for qid,old in original.items():
            answer=answers[qid];accepted=old['acceptable_units']
            if identity_hit({'unit':answer['units'][0]},accepted):continue
            counts['remaining']+=1;case=cases[qid]
            correct=next((u for u in answer['units'] if identity_hit({'unit':u},accepted)),None)
            if case['target_kind']=='symbol':
                counts['unchanged_symbols']+=1
                index.append(f'| {qid} | symbol | Orden nativo sin cambios | [251valores reales](cases/{qid}.md) |')
                continue
            if correct is None:
                counts['outside_top10']+=1
                index.append(f'| {qid} | {case["target_kind"]} | Aceptable fuera de la ventana fija | [posición nativa y par antiguo](cases/{qid}.md) |')
                continue
            counts['piece_numeric_pairs']+=1
            indices=groups[qid];chosen=answer['units'][0];X=matrices[case['repo_id']];model=models[case['repo_id']]
            left=X[indices[canonical(chosen)]];right=X[indices[canonical(correct)]]
            numeric=model.explain_pair(left,right)
            assert numeric['left_score']==answer['scores'][0]
            assert numeric['right_score']==answer['scores'][answer['units'].index(correct)]
            complete.append({'id':qid,'query':case['query'],'chosen':chosen,'acceptable':correct,
                             'feature_names':list(PIECE_FEATURES),'left':left.tolist(),'right':right.tolist(),'numeric':numeric})
            doc=[f'# {qid} — decisión del bosque de piezas v126','',case['query'],'',
                '**Elegido:** `'+canonical(chosen)+'`','**Aceptable:** `'+canonical(correct)+'`','',
                f'Scores {numeric["left_score"]!r} frente a{numeric["right_score"]!r}; margen{numeric["margin"]!r}; residuo{numeric["rounding_residual"]!r}.','',
                'La suma de diferencias de hojas explica esta decisión; agrupar por primera rama divergente no equivale a importancia causal. Árboles completos:piece-forest-pairs.jsonl.gz.','',
                '| Señal | Elegido | Aceptable | Diferencia | Margen de árboles |','|---|---:|---:|---:|---:|']
            for i,name in enumerate(PIECE_FEATURES):
                a,b=float(left[i]),float(right[i]);delta=numeric['branch_margin_by_feature'].get(name,0.)
                writer.writerow([qid,i,name,repr(a),repr(b),repr(a-b),repr(delta)])
                doc.append(f'| `{name}` | {a!r} | {b!r} | {a-b!r} | {delta!r} |')
            (OUT/'piece-cases'/(qid+'.md')).write_text('\n'.join(doc)+'\n')
            index.append(f'| {qid} | {case["target_kind"]} | Score de pieza | [262valores reales](piece-cases/{qid}.md) |')
    assert counts=={'remaining':25,'piece_numeric_pairs':15,'unchanged_symbols':7,'outside_top10':3},counts
    (OUT/'PIECE-CASES-V126.md').write_text('\n'.join(index)+'\n')
    data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in complete).encode()
    (OUT/'piece-forest-pairs.jsonl.gz').write_bytes(gzip.compress(data,compresslevel=6,mtime=0))
    receipt={'counts':counts,'feature_pairs':15*262,'source_receipt':source,
       'producer_sha256':sha(__file__),'control_registration_sha256':sha(CONTROL/'registration.json'),
       'files':{str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()
           and p.name!='PIECE-VALUES-MANIFEST.json'
           and (p.parent.name=='piece-cases' or p.name.startswith(('piece-','PIECE-')))}}
    (OUT/'PIECE-VALUES-MANIFEST.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt['counts']))


if __name__=='__main__':main()
