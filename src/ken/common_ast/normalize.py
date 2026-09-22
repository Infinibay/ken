"""Normalize lossless Tree-sitter operations into a source-language-neutral AST."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import re
from ken.structural.model import IR
from ken.structural.type_refs import parse_type
from .model import Node, Scope, Program, Link
from .kinds import classify, role

DECLARATIONS={'CLASS':'type_declaration','INTERFACE':'type_declaration','TRAIT':'type_declaration',
              'STRUCT':'type_declaration','ENUM':'type_declaration','CALLABLE':'callable','PARAMETER':'parameter'}
BLOCK_LANGUAGES={'javascript','typescript','java','csharp','cpp','go','rust'}
CLOSURES={'lambda','lambda_expression','arrow_function','closure_expression','func_literal','function_expression','generator_function','block','do_block'}
OPERATORS={'+','-','*','/','//','%','**','=','+=','-=','*=','/=','%=','<','>','<=','>=','==','!=','===','!==','&&','||','and','or','not','!','&','|','^','~','<<','>>','>>>','++','--','in','is','??',':='}


def normalize(ir: IR) -> Program:
    operations={op.id:op for op in ir.operations}
    children: dict[str | None,list[str]]=defaultdict(list)
    for op in ir.operations:
        children[op.parent if op.parent in operations else None].append(op.id)
    for siblings in children.values():
        siblings.sort(key=lambda key:(operations[key].start,-operations[key].end,key))
    def spelling(key: str) -> str:
        op=operations[key]
        if 'text' in op.attrs: return str(op.attrs['text'])
        return '.'.join(filter(None,(spelling(c) for c in children[key])))
    package=''
    for op in ir.operations:
        if op.native_kind in ('package_clause','package_declaration'):
            package='.'.join(filter(None,(spelling(c) for c in children[op.id])))
    entities={(e.attrs.get('start_byte'),e.attrs.get('end_byte'),e.attrs.get('native_kind')):e
              for e in ir.entities.values() if e.kind in DECLARATIONS}
    operators: dict[str,list[tuple[int,str]]]=defaultdict(list)
    for fact in ir.facts:
        if fact.relation=='OPERATOR':
            operators[fact.subject].append((fact.attrs.get('position',0),fact.object))
    nodes: list[Node]=[]
    scopes: list[Scope]=[]
    source_ids: dict[str,int]={}
    stack: list[tuple[str,int | None,int,int,bool]]=[(key,None,ordinal,0,False) for ordinal,key in reversed(list(enumerate(children[None])))]
    while stack:
        key,parent,ordinal,inherited,exit_node=stack.pop()
        if exit_node:
            i=source_ids[key]
            nodes[i]=replace(nodes[i],subtree_end=len(nodes))
            continue
        op=operations[key]
        i=len(nodes); source_ids[key]=i
        kind,category=classify(op,parent is None)
        if ir.language=='ruby' and op.native_kind in ('do_block','block'):
            kind,category='callable','expression'
        entity=entities.get((op.start,op.end,op.native_kind))
        name=entity.name if entity else ''
        if entity:
            kind,category=DECLARATIONS[entity.kind],'declaration'
        if kind=='identifier' and parent is not None and nodes[parent].kind=='parameters':
            kind,category='parameter','declaration'
        if op.native_kind in {'variable_declarator','init_declarator','let_declaration','short_var_declaration','var_spec','const_spec'}:
            kind,category='variable_declaration','declaration'
        if kind=='literal' and any(operations[c].native_kind in ('interpolation','string_interpolation','interpolation_expression') for c in children[key]):
            kind='interpolated_string'
        if not name and kind in ('namespace','callable','type_declaration','implementation'):
            names=[operations[c] for c in children[key] if operations[c].role==('type' if kind=='implementation' else 'name')]
            if names:
                name=spelling(names[0].id)
        if kind=='module':
            name=ir.path
        text=str(op.attrs.get('text',''))
        if kind=='identifier': name=text
        flags=set()
        if op.attrs.get('async') or 'async' in op.attrs.get('tokens',()) or kind=='deferred_block': flags.add('async')
        if op.attrs.get('delegated'): flags.add('delegated')
        if op.attrs.get('execution')=='unreachable': flags.add('unreachable')
        if op.native_kind in CLOSURES and kind=='callable': flags.add('closure')
        if entity:
            for field in ('static','constructor','generator','receiver'):
                if entity.attrs.get(field): flags.add(field)
        if kind=='opaque': flags.add('normalization_unknown')
        token_ops=[value for _,value in sorted(operators.get(key,()))]
        if not token_ops and kind in ('assignment','variable_declaration','binary','unary','compare','update'):
            token_ops=[str(t) for t in op.attrs.get('tokens',()) if t in OPERATORS]
        operator=' '.join(token_ops)
        operator={'&&':'and','||':'or','!':'not',':=':'='}.get(operator,operator)
        type_kind=''
        if entity:
            annotation=entity.attrs.get('native_return_type' if kind=='callable' else 'native_type','')
            type_kind=parse_type(annotation,ir.language).kind if annotation else 'unknown'
        elif kind=='literal':
            native=op.native_kind
            type_kind=('bool' if text in ('true','false','True','False') else 'null' if text in ('None','null','nil') else
                       'char' if 'char' in native or 'rune' in native else 'str' if 'string' in native else
                       'float' if any(part in native for part in ('float','real')) or native in ('number','number_literal') and
                       ('.' in text or not re.match(r'0[xob]',text,re.I) and bool(re.search(r'[eEfFdD]',text))) else 'int')
        elif kind in ('array','map','tuple','set'):
            type_kind=kind
        scope=inherited
        if parent is None:
            scope=len(scopes)
            scopes.append(Scope(scope,None,i,'module',ir.path,package or ir.path,None))
        node=Node(i,kind,category,parent,ordinal,role(nodes[parent].kind,op.role) if parent is not None else '',
                  op.role,op.native_kind,key,op.start,op.end,op.line,scope,op.owner,name,text,operator,type_kind,tuple(sorted(flags)))
        nodes.append(node)
        child_scope=scope
        introduces=kind in ('namespace','callable','type_declaration','implementation','comprehension','deferred_block') or kind in ('block','for','catch') and ir.language in BLOCK_LANGUAGES
        if parent is not None and introduces:
            scope_kind='callable' if kind=='callable' else 'type' if kind in ('type_declaration','implementation') else kind
            sid=len(scopes)
            lookup: int | None=scope
            if ir.language=='python' and kind in ('callable','comprehension'):
                while lookup is not None and scopes[lookup].kind=='type': lookup=scopes[lookup].lookup_parent
            if ir.language=='ruby' and kind=='callable' and 'closure' not in flags:
                lookup=None
            component=name or f'<{kind}@{op.start}>'
            # Anonymous blocks share the nearest named namespace; identities
            # remain their distinct scope IDs. No full environment is copied.
            namespace=scopes[scope].namespace+('.'+component if name else '')
            scopes.append(Scope(sid,scope,i,scope_kind,name,namespace,lookup))
            child_scope=sid
        stack.append((key,parent,ordinal,scope,True))
        for position,child in reversed(list(enumerate(children[key]))):
            native_role=operations[child].role
            selected_scope=scope if introduces and native_role in ('name','superclass','superclasses','interfaces','decorator') else child_scope
            if ir.language=='python' and kind=='parameter' and native_role in ('value','type'):
                # Defaults/annotations are evaluated where the function is defined.
                outer_scope=scopes[scope].parent
                selected_scope=outer_scope if outer_scope is not None else scope
            if ir.language=='python' and kind=='comprehension_clause' and native_role=='right':
                siblings=children[op.parent]
                first=next((c for c in siblings if operations[c].native_kind=='for_in_clause'),None)
                if key==first and scopes[scope].kind=='comprehension':
                    outer_scope=scopes[scope].parent
                    selected_scope=outer_scope if outer_scope is not None else scope
            stack.append((child,i,position,selected_scope,False))
    links=[]
    canonical={'OPERAND':'operand','CONTROL_CONDITION':'condition','CONTROL_BODY':'body','CONTROL_ALTERNATIVE':'else',
               'CONTROL_INITIALIZER':'init','CONTROL_UPDATE':'step'}
    for fact in ir.facts:
        if fact.relation in canonical and fact.subject in source_ids and fact.object in source_ids:
            links.append(Link(source_ids[fact.subject],canonical[fact.relation],source_ids[fact.object],fact.attrs.get('position',0)))
    node_children: dict[int,list[int]]=defaultdict(list)
    for node in nodes:
        if node.parent is not None: node_children[node.parent].append(node.id)
    for call in nodes:
        if call.kind!='call': continue
        groups=[nodes[c] for c in node_children[call.id] if nodes[c].kind=='arguments' and nodes[c].native_role!='type_arguments']
        for group in groups:
            expanded=False
            arguments=[nodes[c] for c in node_children[group.id] if nodes[c].category!='trivia']
            for position,argument in enumerate(arguments):
                tokens=raw_tokens=operations[argument.source_id].attrs.get('tokens',())
                named=[nodes[c] for c in node_children[argument.id] if nodes[c].native_role=='name']
                keyword=named[0].text if named and argument.native_kind in ('keyword_argument','named_argument','argument') else ''
                spread=argument.kind=='spread' or any(t in ('*','**','...') for t in tokens)
                arg_kind=('spread_named' if '**' in raw_tokens else 'spread_positional') if spread else 'named' if keyword else 'positional'
                effective=None if expanded or spread or keyword else position
                expanded |= spread
                nodes[argument.id]=replace(argument,argument_kind=arg_kind,argument_name=keyword,argument_position=effective,source_position=position)
                links.append(Link(call.id,'argument',argument.id,position))
    from .symbols import bind
    symbols,references,nodes=bind(ir,nodes,scopes)
    if len(nodes)!=len(operations):
        raise ValueError('source operations do not form a rooted syntax forest')
    result=Program(ir.path,ir.language,tuple(nodes),tuple(scopes),symbols,references,
                   tuple(sorted(set(links),key=lambda l:(l.source,l.relation,l.ordinal,l.target))),tuple(ir.diagnostics))
    result.validate()
    return result
