"""Auditable grammar-to-common-AST vocabulary; unfamiliar syntax stays opaque."""
from ken.structural.model import Operation

NATIVE: dict[str,tuple[str,str]] = {}

def group(kind: str, category: str, words: str) -> None:
    for word in words.split():
        NATIVE[word]=(kind,category)


group('module','declaration','module program translation_unit source_file compilation_unit')
group('namespace','declaration','namespace_definition namespace_declaration file_scoped_namespace_declaration mod_item internal_module')
group('package','declaration','package_clause package_declaration')
group('implementation','declaration','impl_item')
group('block','region','block statement_block compound_statement declaration_list class_body interface_body enum_body body_statement then else else_clause statement_list')
group('parameters','syntax','parameters formal_parameters parameter_list bracketed_parameter_list block_parameters lambda_parameters')
group('parameter','declaration','parameter formal_parameter optional_parameter required_parameter default_parameter typed_parameter typed_default_parameter simple_parameter variadic_parameter spread_parameter')
group('arguments','syntax','arguments argument_list bracketed_argument_list type_arguments')
group('argument','expression','argument keyword_argument named_argument')
group('parameter_pack','declaration','list_splat_pattern dictionary_splat_pattern')
group('parameter_separator','syntax','positional_separator keyword_separator')
group('parameters','syntax','closure_parameters')
group('literal_fragment','syntax','string_start string_end string_content string_fragment escape_sequence format_specifier')
group('interpolation','expression','interpolation string_interpolation interpolation_expression')
group('qualified_reference','expression','dotted_name')
group('index','expression','subscript subscript_expression element_access_expression')
group('slice','expression','slice')
group('pattern','syntax','pattern_list as_pattern_target')
group('alias_pattern','syntax','as_pattern')
group('import','declaration','future_import_statement')
group('resource_items','syntax','with_clause')
group('resource_item','syntax','with_item')
group('annotated_declaration','declaration','decorated_definition')
group('concatenation','expression','concatenated_string')
group('set','expression','set')
group('literal','expression','ellipsis')
group('type_name','type','union_type channel_type map_type')
group('comment','trivia','line_continuation')
group('modifier','syntax','function_modifiers')
group('deferred_block','expression','async_block')
group('spawn','statement','go_statement')
group('defer','statement','defer_statement')
group('send','statement','send_statement')
group('select','statement','select_statement')
group('select_arm','region','communication_case default_case')
group('borrow','expression','reference_expression')
group('pointer_operation','expression','pointer_expression')
group('variable_declaration','declaration','lexical_declaration variable_declaration local_variable_declaration local_declaration_statement declaration let_declaration var_declaration const_declaration var_spec const_spec')
group('identifier','expression','identifier name field_identifier property_identifier shorthand_property_identifier shorthand_property_identifier_pattern constant this self super instance_variable class_variable global_variable')
group('identifier','expression','package_identifier namespace_identifier')
group('qualified_reference','expression','scoped_identifier')
group('type_name','type','type_identifier predefined_type primitive_type integral_type floating_point_type boolean_type void_type generic_type scoped_type_identifier qualified_name user_type type_annotation type')
group('literal','expression','integer integer_literal decimal_integer_literal hex_integer_literal octal_integer_literal binary_integer_literal int_literal float float_literal floating_point_literal real_literal decimal_floating_point_literal string string_literal raw_string_literal interpreted_string_literal char_literal character_literal true false null nil none null_literal boolean_literal rune_literal')
group('literal','expression','number number_literal')
group('binary','expression','binary')
group('unary','expression','unary')
group('array','expression','array array_expression array_creation_expression list list_expression slice_literal')
group('map','expression','dictionary dictionary_comprehension object hash map_type')
group('tuple','expression','tuple tuple_expression tuple_pattern')
group('pair','expression','pair association key_value_element')
group('group','expression','parenthesized_expression parenthesized_list condition_clause')
group('expression_statement','statement','expression_statement')
group('expression_list','syntax','expression_list')
group('if','statement','if_statement if_expression if unless elsif elif_clause')
group('conditional','expression','conditional_expression ternary_expression')
group('while','statement','while_statement while_expression while until until_modifier while_modifier')
group('for','statement','for_statement for_expression for_in_statement enhanced_for_statement for_each_statement foreach_statement for_range_loop for')
group('do_while','statement','do_statement')
group('loop','statement','loop_expression')
group('for_control','syntax','for_clause range_clause')
group('try','statement','try_statement try_with_resources_statement try_expression begin')
group('catch','region','except_clause catch_clause rescue rescue_clause')
group('finally','region','finally_clause finally ensure')
group('break','statement','break_statement break_expression break')
group('continue','statement','continue_statement continue_expression next')
group('return','statement','return_statement return_expression return')
group('throw','statement','throw_statement throw_expression raise_statement')
group('yield','expression','yield yield_expression yield_statement')
group('await','expression','await await_expression')
group('import','declaration','import_statement import_from_statement import_declaration use_declaration using_directive import_spec')
group('import_binding','declaration','aliased_import import_specifier namespace_import use_as_clause')
group('import_group','syntax','import_clause named_imports use_list scoped_use_list')
group('export','declaration','export_statement export_clause')
group('comprehension','expression','list_comprehension set_comprehension dictionary_comprehension generator_expression')
group('comprehension_clause','syntax','for_in_clause if_clause')
group('match','statement','match_expression match_statement switch_expression switch_statement case')
group('match_arm','region','match_arm case_statement switch_section switch_block_statement_group case_clause when')
group('pattern','syntax','tuple_pattern list_pattern slice_pattern record_pattern object_pattern rest_pattern')
group('comment','trivia','comment line_comment block_comment')
group('empty','statement','empty_statement pass_statement')
group('modifier','syntax','modifiers modifier visibility_modifier access_specifier mutability_specifier storage_class_specifier')
group('annotation','syntax','annotation marker_annotation decorator')
group('global','declaration','global_statement')
group('nonlocal','declaration','nonlocal_statement')
group('delete','statement','delete_statement')
group('synchronized','statement','synchronized_statement lock_statement')
group('resource_scope','statement','with_statement using_statement')
group('error','opaque','ERROR')

OPERATIONS = {
 'TYPE':('type_declaration','declaration'), 'FUNCTION':('callable','declaration'),
 'CALL':('call','expression'), 'ASSIGN':('assignment','expression'),
 'DECLARATION':('variable_declaration','declaration'), 'MEMBER':('member','expression'),
 'INDEX':('index','expression'), 'BINARY':('binary','expression'), 'COMPARE':('compare','expression'),
 'UNARY':('unary','expression'), 'UPDATE':('update','expression'), 'SPREAD':('spread','expression'),
 'VARIADIC':('parameter_pack','declaration'), 'TYPE_PARAMETER':('type_parameter','declaration'),
 'DISCARD':('discard','expression'), 'DECORATOR':('annotation','syntax'),
}


def classify(operation: Operation, root: bool = False) -> tuple[str,str]:
    if root:
        return 'module','declaration'
    if operation.native_kind=='map_type': return 'type_name','type'
    if operation.native_kind=='unary_expression': return 'unary','expression'
    return NATIVE.get(operation.native_kind,OPERATIONS.get(operation.kind,('opaque','opaque')))


def role(kind: str, native: str) -> str:
    if native in ('consequence','then'):
        return 'then'
    if native == 'alternative':
        return 'else'
    if native in ('initializer','initialization'):
        return 'init'
    if native in ('increment','update'):
        return 'step'
    if kind in ('assignment','variable_declaration'):
        return {'left':'target','name':'target','pattern':'target','declarator':'target','right':'value'}.get(native,native)
    if kind in ('binary','compare','unary','update'):
        return {'argument':'operand'}.get(native,native)
    if kind=='call':
        return {'function':'callee','name':'callee'}.get(native,native)
    return native
