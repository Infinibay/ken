"""Lexical symbols and occurrence resolution with explicit unavailable/unknown states.

Visibility is not proof of initialization, borrow legality, or runtime dispatch.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from ken.structural.model import IR
from ken.structural.type_refs import parse_type
from .model import Node, Scope, Symbol, Reference, Knowledge

DECLARATORS={'variable_declarator','init_declarator','let_declaration','short_var_declaration','var_spec','const_spec'}
IDENTIFIERS={'identifier','name','field_identifier','property_identifier','shorthand_property_identifier_pattern','constant','instance_variable','global_variable','class_variable'}


def bind(ir: IR, nodes: list[Node], scopes: list[Scope]) -> tuple[tuple[Symbol,...],tuple[Reference,...],list[Node]]:
    children: dict[int,list[int]]=defaultdict(list)
    for node in nodes:
        if node.parent is not None: children[node.parent].append(node.id)
    raw={o.id:o for o in ir.operations}
    introduced={scope.node:scope.id for scope in scopes}
    declarations=set()
    symbols: list[Symbol]=[]
    by_name: dict[tuple[int,str],list[int]]=defaultdict(list)
    overrides: dict[tuple[int,str],str]={}
    entities={(e.attrs.get('start_byte'),e.attrs.get('end_byte')):e for e in ir.entities.values()
              if e.kind in ('STORAGE','PARAMETER','CALLABLE','CLASS','INTERFACE','TRAIT')}
    parameter_properties={f.object:f.attrs for f in ir.facts if f.relation=='HAS_PARAMETER'}

    def descendants(i: int):
        return nodes[i+1:nodes[i].subtree_end]

    def ancestry(i: int):
        parent=nodes[i].parent
        while parent is not None:
            yield nodes[parent]
            parent=nodes[parent].parent

    def local_scope(scope: int) -> int:
        while scopes[scope].parent is not None and scopes[scope].kind not in ('callable','module','type'):
            parent=scopes[scope].parent
            assert parent is not None
            scope=parent
        return scope

    def target_names(i: int) -> list[int]:
        node=nodes[i]
        if node.native_kind in IDENTIFIERS:
            return [i]
        if node.kind in ('member','index','call','literal','type_name'):
            return []
        candidates=[c for c in children[i] if nodes[c].native_role in ('name','pattern','declarator','left')]
        if not candidates:
            candidates=[c for c in children[i] if nodes[c].kind not in ('type_name','modifier') and nodes[c].native_role not in ('type','value','right')]
        return [name for c in candidates for name in target_names(c)]

    for node in nodes:
        if node.kind in ('global','nonlocal'):
            for child in descendants(node.id):
                if child.kind=='identifier':
                    overrides[(local_scope(node.scope),child.text)]=node.kind
                    declarations.add(child.id)

    for context in list(scopes):
        scopes[context.id]=replace(context,
            global_names=tuple(sorted(name for (sid,name),kind in overrides.items() if sid==context.id and kind=='global')),
            nonlocal_names=tuple(sorted(name for (sid,name),kind in overrides.items() if sid==context.id and kind=='nonlocal')))

    def add(name: str, target: int, scope: int, kind: str, container: int, *, hoisted: bool=False, unique: bool=True, implicit: bool=False) -> None:
        if not name or name.startswith('anonymous@') or name=='_':
            return
        node=nodes[target]; outer=nodes[container]
        if ir.language=='python':
            directive=overrides.get((local_scope(scope),name))
            if directive=='global': scope=0
            elif directive=='nonlocal': return  # resolved through outer scope below
        key=(scope,name)
        if unique and by_name[key]:
            return
        declarations.add(target)
        tokens=set(raw[outer.source_id].attrs.get('tokens',()))
        for parent in ancestry(container):
            if parent.scope!=outer.scope or parent.kind not in ('variable_declaration','assignment','expression_statement'):
                break
            tokens.update(raw[parent.source_id].attrs.get('tokens',()))
        mutable=None
        if kind=='variable':
            mutable=('mut' in tokens) if ir.language=='rust' else not bool(tokens & {'const','final','readonly'})
        values=[nodes[c] for c in children[container] if nodes[c].native_role in ('right','value')]
        initializer_end=max((n.end for n in values),default=None)
        if kind=='variable' and ir.language in ('javascript','typescript'):
            initializer_end=0 if hoisted else initializer_end if initializer_end is not None else outer.end
        if kind in ('parameter','callable','type','import','namespace'):
            initializer_end=0 if hoisted or kind=='parameter' else outer.end
        flags=set()
        if any(parent.kind in ('if','for','while','loop','try','catch','match','conditional') for parent in ancestry(container)
               if parent.scope==outer.scope or parent.kind!='callable'):
            flags.add('conditional_init')
        if implicit: flags.add('implicit')
        if kind=='import': flags.add('external')
        if hoisted: flags.add('hoisted')
        if ir.language in ('javascript','typescript') and kind=='variable' and not hoisted: flags.add('tdz')
        annotation=''
        entity=entities.get((node.start,node.end)) or entities.get((outer.start,outer.end))
        if entity:
            annotation=str(entity.attrs.get('native_type',''))
            if entity.attrs.get('receiver'): flags.add('receiver')
        if not annotation:
            type_nodes=[nodes[c] for c in children[container] if nodes[c].native_role=='type']
            if type_nodes:
                t=type_nodes[0]
                annotation=t.text or ''.join(n.text for n in descendants(t.id) if n.text)
        type_kind=parse_type(annotation,ir.language).kind if annotation else 'unknown'
        visible=0 if hoisted or ir.language=='python' else node.start
        if ir.language=='rust' and kind=='variable': visible=outer.end
        if 'tdz' in flags: visible=0  # shadows outer name throughout the scope
        symbol=Symbol(len(symbols),name,scope,target,kind,entity.id if entity else node.source_id,
                      visible,initializer_end,type_kind,annotation,mutable,tuple(sorted(flags)),
                      parameter_properties.get(entity.id,{}).get('position') if entity is not None and kind=='parameter' else None,
                      str(entity.attrs.get('parameter_kind',entity.attrs.get('kind_',''))) if entity is not None and kind=='parameter' else '',
                      entity.attrs.get('position') if entity is not None and kind=='parameter' else None)
        by_name[key].append(symbol.id); symbols.append(symbol)
        if node.kind=='identifier':
            nodes[target]=replace(node,kind='binding_declaration',category='declaration',name=name,type_kind=type_kind)

    for node in list(nodes):
        if node.kind in ('callable','type_declaration','namespace'):
            if 'closure' in node.flags and not node.name: continue
            scope=introduced.get(node.id,node.scope) if node.native_kind in ('function_expression','generator_function') else node.scope
            name=node.name
            name_children=[c for c in children[node.id] if nodes[c].native_role=='name']
            declarations.update(name_children)
            add(name,node.id,scope,'callable' if node.kind=='callable' else 'type' if node.kind=='type_declaration' else 'namespace',node.id,
                hoisted=ir.language in ('javascript','typescript','java','csharp','go','rust'),unique=False)
        elif node.kind=='parameter':
            names=[c for c in children[node.id] if nodes[c].native_role in ('name','pattern')]
            parameter_targets=(target_names(names[0]) if names else target_names(node.id))
            if node.name and not parameter_targets: parameter_targets=[node.id]
            for i in parameter_targets:
                add(node.name or nodes[i].text,i,node.scope,'parameter',node.id,hoisted=True)
            declarations.add(node.id)
        elif node.kind=='alias_pattern' and ir.language=='python':
            for child in children[node.id]:
                if nodes[child].native_role=='alias':
                    for target in target_names(child):
                        add(nodes[target].text,target,local_scope(node.scope),'variable',node.id,implicit=True)
        elif node.kind=='variable_declaration' and (node.native_kind in DECLARATORS or not any(n.native_kind in DECLARATORS for n in descendants(node.id))):
            candidates=[c for c in children[node.id] if nodes[c].native_role in ('name','pattern','declarator','left')]
            for target in [t for c in candidates for t in target_names(c)]:
                scope=node.scope
                tokens=set(raw[node.source_id].attrs.get('tokens',()))
                for parent in ancestry(node.id):
                    if parent.kind not in ('variable_declaration','expression_statement'): break
                    tokens.update(raw[parent.source_id].attrs.get('tokens',()))
                hoisted=ir.language in ('javascript','typescript') and 'var' in tokens
                if hoisted: scope=local_scope(scope)
                add(nodes[target].text,target,scope,'variable',node.id,hoisted=hoisted,
                    unique=ir.language!='rust')
        elif node.kind=='assignment' and ir.language in ('python','ruby'):
            targets=[c for c in children[node.id] if nodes[c].native_role in ('left','name')]
            for target in [t for c in targets for t in target_names(c)]:
                add(nodes[target].text,target,local_scope(node.scope),'variable',node.id,implicit=True)
        elif node.kind in ('for','comprehension_clause'):
            targets=[c for c in children[node.id] if nodes[c].native_role in ('left','name','pattern','declarator')]
            for target in [t for c in targets for t in target_names(c)]:
                scope=introduced.get(node.id,node.scope)
                if ir.language in ('python','ruby'): scope=local_scope(scope) if scopes[scope].kind!='comprehension' else scope
                add(nodes[target].text,target,scope,'variable',node.id,implicit=ir.language in ('python','ruby'))

    # Import aliases introduce lexical bindings; resolving the exported target
    # of the external module is a separate linking operation.
    for node in list(nodes):
        if node.kind!='import' or any(p.kind=='import' for p in ancestry(node.id)):
            continue
        ids=[n.id for n in descendants(node.id) if n.kind=='identifier']
        declarations.update(ids)
        targets=[]
        if ir.language=='python':
            for c in children[node.id]:
                item=nodes[c]
                if item.native_role!='name': continue
                aliases=[n.id for n in descendants(c) if n.native_role=='alias']
                identifiers=[n.id for n in ([item]+list(descendants(c))) if n.kind=='identifier']
                if aliases: targets.extend(aliases)
                elif identifiers: targets.append(identifiers[0])
        elif ir.language in ('javascript','typescript'):
            for item in descendants(node.id):
                if item.kind=='import_binding':
                    aliases=[c for c in children[item.id] if nodes[c].native_role=='alias']
                    names=[c for c in children[item.id] if nodes[c].kind=='identifier']
                    targets.extend(aliases or names[-1:])
                elif item.kind=='identifier' and item.parent is not None and nodes[item.parent].native_kind=='import_clause':
                    targets.append(item.id)
        elif ir.language=='java' and ids and '*' not in raw[node.source_id].attrs.get('tokens',()):
            targets=ids[-1:]
        elif ir.language=='csharp':
            targets=[c for c in children[node.id] if nodes[c].native_role=='name' and nodes[c].kind=='identifier']
        elif ir.language=='go':
            targets=[i for i in ids if nodes[i].native_role=='name']
        elif ir.language=='rust':
            def imported(i: int) -> list[int]:
                item=nodes[i]
                if item.kind=='import_binding':
                    return [c for c in children[i] if nodes[c].native_role=='alias']
                if item.native_kind=='scoped_use_list':
                    return [t for c in children[i] if nodes[c].native_role=='list' for t in imported(c)]
                if item.kind=='qualified_reference':
                    return [c for c in children[i] if nodes[c].native_role=='name']
                if item.kind=='identifier': return [i]
                return [t for c in children[i] for t in imported(c)]
            targets=imported(node.id)
        for target in targets:
            add(nodes[target].text,target,node.scope,'import',node.id,hoisted=ir.language in ('javascript','typescript','java','csharp','go','rust'))

    # Parameter ordinals exclude grammar separators and implicit receivers.
    positions: dict[int,int]=defaultdict(int)
    for i,symbol in enumerate(symbols):
        if symbol.kind!='parameter': continue
        position=None if 'receiver' in symbol.flags else positions[symbol.scope]
        symbols[i]=replace(symbol,position=position)
        if position is not None: positions[symbol.scope]+=1

    # Syntax alone cannot certify initialization after deletion/dynamic execution.
    # Keep lexical identity, but deliberately withhold the availability claim.
    uncertain=set()
    deleted: set[str]=set()
    for node in nodes:
        if node.kind=='delete':
            deleted.update(n.text for n in descendants(node.id) if n.kind=='identifier')
        if node.kind=='call' and any(nodes[c].text in ('exec','eval') for c in children[node.id]):
            uncertain.add(local_scope(node.scope))
    symbols=[replace(s,flags=tuple(sorted(set(s.flags)|{'uncertain_lifetime'})))
             if s.name in deleted or local_scope(s.scope) in uncertain else s for s in symbols]
    from .environment import Environment
    environment=Environment(scopes,symbols,language=ir.language)

    references=[]
    for node in nodes:
        if node.kind!='identifier' or node.id in declarations:
            continue
        parent=nodes[node.parent] if node.parent is not None else None
        if parent is not None and (parent.kind=='package' or parent.argument_kind=='named' and node.native_role=='name'):
            continue
        if not node.text or node.native_role in ('type','label') or parent is not None and parent.kind in ('type_name','modifier','import','export'):
            continue
        name=node.text
        if parent is not None and parent.kind in ('member','qualified_reference') and node.native_role in ('attribute','field','property','name'):
            references.append(Reference(node.id,name,node.scope,'member',None,'unknown','member_dispatch_required'))
            continue
        mode='read'
        if parent is not None and parent.kind in ('assignment','variable_declaration') and node.role=='target':
            mode='read_write' if parent.operator not in ('', '=') else 'write'
        if parent is not None and parent.kind=='update': mode='read_write'
        resolved=environment.resolve(name,node.scope,node.start)
        references.append(Reference(node.id,name,node.scope,mode,resolved.symbol,resolved.status,resolved.reason,resolved.availability))
    return tuple(symbols),tuple(references),nodes
