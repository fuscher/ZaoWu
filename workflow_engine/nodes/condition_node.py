from __future__ import annotations

import ast
import operator
from typing import Any
from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_ended

_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Not: operator.not_,
    ast.In: lambda a, b: a in b,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str, variables: dict) -> Any:
    tree = ast.parse(expression, mode='eval')
    return _eval_node(tree.body, variables)


def _eval_node(node, variables) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise NameError(f'变量 {node.id} 未定义')
        return variables[node.id]
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_OPERATORS.get(type(node.op))
        if not op:
            raise ValueError('不允许的二元操作符')
        return op(_eval_node(node.left, variables), _eval_node(node.right, variables))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, variables)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _ALLOWED_OPERATORS.get(type(op_node))
            if not op:
                raise ValueError('不允许的比较操作符')
            right = _eval_node(comparator, variables)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        result = _eval_node(node.values[0], variables)
        for val_node in node.values[1:]:
            if is_and and not result:
                return result
            if not is_and and result:
                return result
            result = _ALLOWED_OPERATORS[type(node.op)](result, _eval_node(val_node, variables))
        return result
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_OPERATORS.get(type(node.op))
        if not op:
            raise ValueError('不允许的一元操作符')
        return op(_eval_node(node.operand, variables))
    raise ValueError('不允许的表达式类型')


class ConditionNode(BaseNode):
    node_type = 'condition'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        condition_cfg = self.config.get('conditionConfig') or self.config
        mode = condition_cfg.get('mode') or self.config.get('judgeMode') or 'simple'
        raw_input = ctx.resolve('{{input}}', ctx_node.inputs)

        if mode == 'code':
            expression = condition_cfg.get('expression', 'True')
            try:
                result = safe_eval(expression, {'input': raw_input})
                branch = 'true' if result else 'false'
            except Exception as e:
                ctx_node.error = f'条件表达式求值失败: {e}'
                branch = condition_cfg.get('fallbackBranch', 'false')
        else:
            branch = condition_cfg.get('defaultBranch', 'false')
            for rule in condition_cfg.get('rules', []):
                if _match_rule(rule, raw_input):
                    branch = rule.get('branch', 'true')
                    break

        ctx_node.outputs = {'branch': branch, 'default': raw_input}
        yield _sse_node_ended(ctx, ctx_node)


def _match_rule(rule: dict, value) -> bool:
    import re as _re
    field = rule.get('field')
    if field and isinstance(value, dict):
        actual = value.get(field, value.get('default', ''))
    else:
        actual = value
    op = rule.get('operator', 'eq')
    target = rule.get('value')
    try:
        if op == 'eq':
            return str(actual) == str(target)
        if op == 'ne':
            return str(actual) != str(target)
        if op == 'contains':
            return str(target) in str(actual)
        if op == 'gt':
            return float(actual) > float(target)
        if op == 'gte':
            return float(actual) >= float(target)
        if op == 'lt':
            return float(actual) < float(target)
        if op == 'lte':
            return float(actual) <= float(target)
        if op == 'regex':
            return bool(_re.search(str(target), str(actual)))
    except (ValueError, TypeError):
        return False
    return False
