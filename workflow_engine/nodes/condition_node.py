from __future__ import annotations

import ast
import operator
import re as _re_module
import logging
from typing import Any
from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_progress, _sse_node_ended

logger = logging.getLogger(__name__)

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

# 安全白名单：允许调用的内置函数
_SAFE_BUILTINS: dict[str, Any] = {
    'len': len,
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
    'abs': abs,
    'min': min,
    'max': max,
    'sum': sum,
    'round': round,
    'isinstance': isinstance,
    'type': type,
    'list': list,
    'dict': dict,
    'tuple': tuple,
    'set': set,
}

# 安全白名单：允许通过属性访问的模块（仅 re）
_SAFE_MODULES: dict[str, Any] = {
    're': _re_module,
}


def _resolve_provider() -> tuple[dict, str]:
    """解析 provider 配置的公共函数（供 condition prompt 模式使用）。"""
    try:
        import json
        import os
        from zaowu_paths import get_project_root
        providers_file = os.path.join(get_project_root(), 'providers.json')
        with open(providers_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('providers', []), providers_file
    except Exception:
        return [], ''


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
    if isinstance(node, ast.Call):
        return _eval_call(node, variables)
    if isinstance(node, ast.Attribute):
        return _eval_attribute(node, variables)
    raise ValueError('不允许的表达式类型')


def _eval_call(node: ast.Call, variables: dict) -> Any:
    """安全执行函数调用，仅允许白名单函数和模块方法。"""
    func_name = None
    if isinstance(node.func, ast.Name):
        func_name = node.func.id
        if func_name in _SAFE_BUILTINS:
            fn = _SAFE_BUILTINS[func_name]
        elif func_name in _SAFE_MODULES:
            # 不允许直接调用模块本身
            raise ValueError(f'模块 {func_name} 不可直接调用')
        else:
            raise ValueError(f'不允许的函数: {func_name}')
    elif isinstance(node.func, ast.Attribute):
        attr_val = _eval_attribute(node.func, variables)
        fn = attr_val
        func_name = str(attr_val)
    else:
        raise ValueError('不允许的调用形式')

    args = [_eval_node(a, variables) for a in node.args]
    kwargs = {kw.arg: _eval_node(kw.value, variables) for kw in node.keywords}
    return fn(*args, **kwargs)


def _eval_attribute(node: ast.Attribute, variables: dict) -> Any:
    """安全执行属性访问。支持白名单模块的属性、也支持变量对象的方法链访问。"""
    if isinstance(node.value, ast.Name):
        name = node.value.id
        if name in _SAFE_MODULES:
            module = _SAFE_MODULES[name]
            attr_name = node.attr
            if attr_name.startswith('__'):
                raise ValueError(f'不允许访问私有属性: {attr_name}')
            return getattr(module, attr_name, None)
        # 不是模块名 → 当作变量，允许对其返回值做属性访问（如 input.upper()）
        if name in variables:
            obj = variables[name]
            if node.attr.startswith('__'):
                raise ValueError(f'不允许访问私有属性: {node.attr}')
            return getattr(obj, node.attr)
        raise ValueError(f'变量 {name} 未定义')
    # 链式属性访问（如 input.upper().startswith(...)）
    obj = _eval_node(node.value, variables)
    if node.attr.startswith('__'):
        raise ValueError(f'不允许访问私有属性: {node.attr}')
    return getattr(obj, node.attr)


class ConditionNode(BaseNode):
    node_type = 'condition'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        condition_cfg = self.config.get('conditionConfig') or self.config
        mode = condition_cfg.get('mode') or self.config.get('judgeMode') or 'simple'
        raw_input = ctx.resolve('{{input}}', ctx_node.inputs)

        # 兼容旧配置：code → expression, llm → prompt
        if mode == 'code':
            mode = 'expression'
        elif mode == 'llm':
            mode = 'prompt'

        if mode == 'expression':
            expression = condition_cfg.get('expression', 'True')
            try:
                result = safe_eval(expression, {'input': raw_input})
                branch = 'true' if result else 'false'
            except Exception as e:
                ctx_node.error = f'条件表达式求值失败: {e}'
                branch = condition_cfg.get('fallbackBranch', 'false')

        elif mode == 'prompt':
            judge_prompt = (
                condition_cfg.get('judgePrompt')
                or condition_cfg.get('naturalLanguage', '')
            )
            model_config = condition_cfg.get('modelConfig') or {}
            provider_id = model_config.get('providerId', '')
            model_id = model_config.get('modelId', '')
            temperature = model_config.get('temperature', 0.7)
            max_tokens = model_config.get('maxTokens', 512)

            if not provider_id or not model_id:
                ctx_node.error = '提示词模式下需要配置模型（providerId + modelId）'
                branch = condition_cfg.get('fallbackBranch', 'false')
            else:
                try:
                    import json
                    import os
                    from zaowu_paths import get_project_root
                    providers_file = os.path.join(get_project_root(), 'providers.json')
                    with open(providers_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    providers_list = data.get('providers', [])
                    provider = next((p for p in providers_list if p['id'] == provider_id), {})
                except Exception:
                    provider = {}

                from agent_modules.agent_core.llm_stream import llm_stream

                full_content = ''
                try:
                    async for part in llm_stream(
                        provider=provider,
                        model_id=model_id,
                        messages=[{
                            'role': 'system',
                            'content': 'You are a boolean judge. Reply with only "true" or "false".',
                        }, {
                            'role': 'user',
                            'content': ctx.resolve(judge_prompt, ctx_node.inputs),
                        }],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tool_choice='none',
                        stop_event=stop_event,
                    ):
                        if part.get('type') == 'delta':
                            full_content += part.get('delta', '')
                    branch = _parse_bool(full_content.strip(),
                                         condition_cfg.get('defaultBranch', 'false'))
                except Exception as e:
                    ctx_node.error = f'提示词模式 LLM 调用失败: {e}'
                    branch = condition_cfg.get('fallbackBranch', 'false')

        else:
            # simple 模式（默认）
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


def _parse_bool(raw: str, default_branch: str = 'false') -> str:
    """解析 LLM 返回的布尔值文本。"""
    s = raw.lower()
    if s in ('true', 'yes', '1', 't', 'y'):
        return 'true'
    if s in ('false', 'no', '0', 'f', 'n', ''):
        return 'false'
    logger.warning(f'提示词模式返回不可识别内容: "{raw}"，使用默认分支 {default_branch}')
    return default_branch
