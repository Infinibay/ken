"""Create a fixed old240 two-view scale diagnostic from already closed source/logits."""
from pathlib import Path
p=Path('output/analysis/capture-bounded-operation-policies-v213.py');s=p.read_text()
s=s.replace('from relational_operations import OperationWitnesses, requested_operations, prefer_operations','from ken.retrieval.source_operations import OperationWitnesses\nfrom ken.retrieval.symbol_requirements import requested_operations, prefer_operations, requests_test_case, is_test_case')
s=s.replace('from explicit_code_terms import explicit_code_terms, prefer_explicit_code_terms','from ken.retrieval.symbol_requirements import explicit_code_terms, prefer_explicit_code_terms')
s=s.replace('from requested_test_piece import prefer_requested_test_piece','')
s=s.replace('from ken.retrieval.best_resources import default_resources','')
anchor='def sha(path):\n';helper='''def prefer_requested_test_piece(query, units, catalog):
    order=list(range(len(units)))
    if requests_test_case(SearchRequest(query)):
        order.sort(key=lambda i:not is_test_case(EntityKey(path=units[i]['path'],**units[i]['entity']),catalog))
    return order


def composition_orders(card, code, native):
    import numpy as np
    stable=sorted(range(len(card)),key=lambda i:native[i])
    means=[(a+b)/2 for a,b in zip(card,code,strict=True)]
    card_order=sorted(stable,key=lambda i:-card[i]);code_order=sorted(stable,key=lambda i:-code[i])
    a_rank={i:r for r,i in enumerate(card_order,1)};b_rank={i:r for r,i in enumerate(code_order,1)}
    fused=[1/(60+a_rank[i])+1/(60+b_rank[i]) for i in range(len(card))]
    a=np.asarray(card);b=np.asarray(code);standardized=(a-a.mean())/(a.std() or 1)+(b-b.mean())/(b.std() or 1)
    return {'baseline_mean':sorted(stable,key=lambda i:-means[i]),'code_only':code_order,
        'rank_fusion':sorted(stable,key=lambda i:-fused[i]),'standardized_mean':sorted(stable,key=lambda i:-standardized[i])}


''';assert anchor in s;s=s.replace(anchor,helper+anchor)
s=s.replace("out = w / 'output/development/bounded-operation-policies-v213'", "out = w / 'output/analysis/view-scale-v288-old240'")
s=s.replace("'variants': ['current_rrf', 'neural_test_piece_operator', 'two_views_test_piece_operator', 'neural_cause', 'neural_snapshot_write', 'neural_flag_refresh', 'neural_all_relations', 'two_views_all_relations']", "'variants': ['baseline_mean','code_only','rank_fusion','standardized_mean']")
s=s.replace("'hypothesis': 'V213same211semantic policies, source projection budget guard: atomic fallback to original current card if >64owned executable lines, full projection>12000chars or complete query+code pair>1024tokens. No prefix cuts in second view. V211 relational syntax rather than pooled operation counts. Query explicitly requests exception chaining, snapshot keyed update, or returned flag short-circuit refresh. Stable preference for direct source witnesses; preserve unknown candidates and all identities. Test each signal separately then combined on rawNN and fixed209equalmean. No learned scores/weights, source names, query IDs or repository names in policy.'", "'hypothesis': 'Actual source-card and complete-code views use the same model but their raw-logit scales need not be interchangeable. Compare unchanged equal mean with code-only, fixed k60 rank fusion and within-query standardized mean. All prior source constraints/paths/exact bypass and budgets unchanged. No learned parameters or per-language/repository routing. Pure already-closed-logit diagnostic; no model inference or blind acceptance.'")
old="'policy_sources': {name: sha(w / 'experiments/search-engine' / name) for name in ['requested_test_piece.py', 'explicit_code_terms.py', 'relational_operations.py', 'lexical_code_view.py', 'source_syntax_view.py']}"
new="'policy_sources': {name: sha(Path('/Users/andres/.codex/worktrees/compact-default-output/ken/src/ken/retrieval') / name) for name in ['symbol_requirements.py','source_operations.py','description.py','piece_catalog.py','intent.py']}";assert old in s;s=s.replace(old,new)
s=s.replace("checker = default_resources().neural\nchecker._load()\nassert checker._max_tokens == 1024", "previous_budget_root=w/'output/development/bounded-operation-policies-v213'\nprevious_budget_reg=json.loads((previous_budget_root/'registration.json').read_text())\nassert sha(previous_budget_root/'budgets.jsonl')==previous_budget_reg['budgets_sha256']\nprevious_budgets={(r['id'],json.dumps(r['unit'],sort_keys=True)):r for r in rows(previous_budget_root/'budgets.jsonl')}")
s=s.replace("with project_connection(root) as connection:\n            catalog", "with project_connection(root) as connection:\n            connection.execute('PRAGMA query_only=ON')\n            catalog")
s=s.replace("length = len(checker._query_tokenizer.encode(case['query'], full).ids)", "old_budget=previous_budgets[(query_id,json.dumps(unit,sort_keys=True))]\n                length=old_budget['full_pair_tokens']\n                assert len(full)==old_budget['full_chars']")
start=s.index('            for name, base, allowed in [');end=s.index('                facts = ',start)
s=s[:start]+"            for name,indices in composition_orders([r['neural_score'] for r in signals],code_scores,[r['native_rank'] for r in signals]).items():\n                base=[units[i] for i in indices];allowed=requested\n"+s[end:]
s=s.replace("for name in protocol['variants'][1:]:", "for name in protocol['variants']:")
anchor="(out / 'budgets.jsonl').write_text";pos=s.index(anchor)
proof='''# Before any new grading, reproduce every old production first-to-tenth identity.
actual={}
for cohort in ('original','symbols'):
    historical=w/f'output/development/public-bounded-symbol-ranking-v214-{cohort}'
    registration=json.loads((historical/'capture/registration.json').read_text())
    for repo,digests in registration['closed'].items():
        path=historical/'capture'/repo/'answers.jsonl';assert sha(path)==digests['answers.jsonl']
        actual.update({r['id']:r['units'] for r in rows(path) if r['id'] in cases})
assert len(actual)==240
for prediction in predictions:assert prediction['orders']['baseline_mean']==actual[prediction['id']],('baseline order differs',prediction['id'])
protocol['old240_baseline_orders_reproduced']=True
protocol['no_model_inference']=True
'''
s=s[:pos]+proof+s[pos:]
s=s.replace("from pathlib import Path", "from pathlib import Path")
q=Path('output/analysis/repoqa-diagnosis-v236/source/replay_view_scale_v288.py');q.write_text(s);compile(s,str(q),'exec');print(q)
