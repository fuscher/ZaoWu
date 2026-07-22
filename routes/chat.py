import os
import json
import uuid
import asyncio
import logging
import threading
import requests
import httpx
from datetime import datetime, timezone
from quart import Blueprint, request, jsonify, Response
from zaowu_paths import get_project_root

_log = logging.getLogger('zaowu.routes.chat')
chat_bp = Blueprint('chat', __name__)

BASE_DIR = get_project_root()
PROVIDERS_FILE = os.path.join(BASE_DIR, 'providers.json')
CONFIG_FILE = os.path.join(BASE_DIR, 'chat_config.json')
PRESETS_FILE = os.path.join(BASE_DIR, 'chat_presets.json')

from services.data_lock import conversation_lock as _chat_lock
_stop_events = {}


def _get_store():
    """延迟导入 ConversationStore（避免循环依赖）。"""
    from server_quart import get_conversation_store
    return get_conversation_store()


def _read_json(filepath, default):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def _write_json(filepath, data):
    with _chat_lock:
        tmp = filepath + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)


def _init_data_files():
    if not os.path.exists(PROVIDERS_FILE):
        _write_json(PROVIDERS_FILE, {'providers': []})
    if not os.path.exists(CONFIG_FILE):
        _write_json(CONFIG_FILE, {
            'defaultProviderId': '',
            'defaultModelId': '',
            'temperature': 0.7,
            'maxTokens': 4096,
            'topP': 1.0,
            'systemPrompt': 'You are a helpful assistant.',
        })
    if not os.path.exists(PRESETS_FILE):
        _write_json(PRESETS_FILE, {'presets': []})


_init_data_files()


# ── Providers ──────────────────────────────────────────────

@chat_bp.route('/providers', methods=['GET'])
def get_providers():
    data = _read_json(PROVIDERS_FILE, {'providers': []})
    return jsonify({'ok': True, 'providers': data.get('providers', [])})


@chat_bp.route('/providers', methods=['POST'])
async def save_providers():
    body = await request.get_json(silent=True)
    if not body or 'providers' not in body:
        return jsonify({'ok': False, 'error': 'missing providers'}), 400

    providers = body['providers']
    if not isinstance(providers, list):
        return jsonify({'ok': False, 'error': 'providers must be a list'}), 400

    # 逐条校验 provider 字段，防止恶意 apiBase 注入
    validated = []
    for p in providers:
        if not isinstance(p, dict):
            return jsonify({'ok': False, 'error': 'each provider must be an object'}), 400
        # id: 必须是非空字符串
        pid = p.get('id')
        if not isinstance(pid, str) or not pid.strip():
            return jsonify({'ok': False, 'error': 'provider id is required'}), 400
        # name: 可选，但必须是字符串
        pname = p.get('name', pid)
        if not isinstance(pname, str):
            return jsonify({'ok': False, 'error': 'provider name must be a string'}), 400
        # apiBase: 必须是合法 HTTPS/HTTP URL
        api_base = p.get('apiBase', '')
        if isinstance(api_base, str) and api_base.strip():
            if not api_base.strip().startswith(('http://', 'https://')):
                return jsonify({'ok': False, 'error': f'provider {pid}: apiBase must start with http:// or https://'}), 400
            # 防止内网地址注入（攻击者设置 apiBase 为内部服务，窃取 apiKey）
            if '\x00' in api_base or '\r' in api_base or '\n' in api_base:
                return jsonify({'ok': False, 'error': f'provider {pid}: apiBase contains invalid characters'}), 400
        # apiKey: 类型校验
        api_key = p.get('apiKey', '')
        if not isinstance(api_key, str):
            return jsonify({'ok': False, 'error': f'provider {pid}: apiKey must be a string'}), 400
        validated.append(p)

    _write_json(PROVIDERS_FILE, {'providers': validated})
    return jsonify({'ok': True})


# ── Models (proxy to provider API) ────────────────────────

@chat_bp.route('/models/<provider_id>', methods=['GET'])
def get_models(provider_id):
    data = _read_json(PROVIDERS_FILE, {'providers': []})
    provider = next((p for p in data.get('providers', []) if p['id'] == provider_id), None)
    if not provider:
        return jsonify({'ok': False, 'error': 'provider not found'}), 404

    api_base = provider.get('apiBase', '').rstrip('/')
    api_key = provider.get('apiKey', '')

    if not api_base or not api_key:
        return jsonify({'ok': True, 'models': [m for m in provider.get('models', [])]})

    try:
        headers = {'Authorization': f'Bearer {api_key}'}
        resp = requests.get(f'{api_base}/models', headers=headers, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            models = []
            for m in result.get('data', []):
                models.append({
                    'id': m.get('id', ''),
                    'name': m.get('id', ''),
                    'contextLength': m.get('context_length'),
                })
            provider['models'] = models
            _write_json(PROVIDERS_FILE, data)
            return jsonify({'ok': True, 'models': models})
        else:
            return jsonify({'ok': True, 'models': provider.get('models', [])})
    except Exception:
        return jsonify({'ok': True, 'models': provider.get('models', [])})


# ── Conversations ──────────────────────────────────────────

@chat_bp.route('/conversations', methods=['GET'])
async def list_conversations():
    store = _get_store()
    convs = await store.list_all()
    return jsonify({'ok': True, 'conversations': convs})


@chat_bp.route('/conversations', methods=['POST'])
async def create_conversation():
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400

    config = _read_json(CONFIG_FILE, {})
    conv_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conv = {
        'id': conv_id,
        'title': body.get('title', '新对话'),
        'providerId': body.get('providerId', config.get('defaultProviderId', '')),
        'modelId': body.get('modelId', config.get('defaultModelId', '')),
        'systemPrompt': body.get('systemPrompt', config.get('systemPrompt', '')),
        'messages': [],
        'createdAt': now,
        'updatedAt': now,
        'agentConfig': body.get('agentConfig', {
            'enabled': False,
            'maxIterations': 10,
            'requiresApproval': False,
        }),
    }

    await _get_store().create(conv)
    return jsonify({'ok': True, 'conversation': conv})


@chat_bp.route('/conversations/<conv_id>', methods=['GET'])
async def get_conversation(conv_id):
    conv = await _get_store().get(conv_id)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404
    return jsonify({'ok': True, 'conversation': conv})


@chat_bp.route('/conversations/<conv_id>', methods=['PATCH'])
async def update_conversation(conv_id):
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400

    store = _get_store()
    conv = await store.get(conv_id)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404

    for key in ('title', 'providerId', 'modelId', 'systemPrompt'):
        if key in body:
            conv[key] = body[key]

    # 支持更新 agentConfig
    if 'agentConfig' in body:
        agent_config = body['agentConfig'] or {}
        selected_skill = agent_config.get('selectedSkill')
        if selected_skill == '':
            agent_config['selectedSkill'] = None
            selected_skill = None
        if selected_skill is not None:
            from services.skill_registry import SkillRegistry
            registry = SkillRegistry.get_instance()
            skill = registry.get(selected_skill)
            if skill is None:
                return jsonify({'ok': False, 'error': f'skill {selected_skill!r} not found'}), 400
            if not registry.is_enabled(selected_skill):
                return jsonify({'ok': False, 'error': f'skill {selected_skill!r} is disabled'}), 400
        conv['agentConfig'] = agent_config

    conv['updatedAt'] = datetime.now(timezone.utc).isoformat()
    await store.update(conv_id, conv)
    return jsonify({'ok': True, 'conversation': conv})


@chat_bp.route('/conversations/<conv_id>', methods=['DELETE'])
async def delete_conversation(conv_id):
    store = _get_store()
    if not await store.exists(conv_id):
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404
    await store.delete(conv_id)
    return jsonify({'ok': True})


@chat_bp.route('/conversations/<conv_id>/clear', methods=['POST'])
async def clear_conversation(conv_id):
    store = _get_store()
    conv = await store.get(conv_id)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404

    await store.clear_messages(conv_id)
    now = datetime.now(timezone.utc).isoformat()
    await store.update(conv_id, {'updatedAt': now})
    conv['messages'] = []
    conv['updatedAt'] = now
    return jsonify({'ok': True, 'conversation': conv})


# ── Send Message (SSE streaming) ───────────────────────────

@chat_bp.route('/conversations/<conv_id>/messages', methods=['POST'])
async def send_message(conv_id):
    body = await request.get_json(silent=True)
    if not body or 'content' not in body:
        return jsonify({'ok': False, 'error': 'missing content'}), 400
    # F15: 校验空内容，与 /agent-messages 行为一致
    if not body['content'] or not body['content'].strip():
        return jsonify({'ok': False, 'error': 'content is empty'}), 400

    store = _get_store()
    conv = await store.get(conv_id)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404

    providers = _read_json(PROVIDERS_FILE, {'providers': []}).get('providers', [])
    provider = next((p for p in providers if p['id'] == conv.get('providerId')), None)

    config = _read_json(CONFIG_FILE, {})
    now = datetime.now(timezone.utc).isoformat()

    user_msg = {
        'id': str(uuid.uuid4()),
        'role': 'user',
        'content': body['content'],
        'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
        'updatedAt': now,
    }
    conv['messages'].append(user_msg)

    if not conv.get('messages') or sum(1 for m in conv['messages'] if m['role'] == 'user') == 1:
        title = body['content'][:50] + ('...' if len(body['content']) > 50 else '')
        await store.update(conv_id, {'title': title, 'updatedAt': now})
        conv['title'] = title

    conv['updatedAt'] = now
    await store.append_message(conv_id, user_msg)

    assistant_msg_id = str(uuid.uuid4())
    stop_event = threading.Event()
    _stop_events[assistant_msg_id] = stop_event

    async def generate():
        full_content = ''

        def _sse(payload):
            return f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'

        try:
            if not provider:
                error_text = '未配置 LLM 提供商，请先在设置中添加 Provider。'
                yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
                full_content = error_text
                return

            api_base = provider.get('apiBase', '').rstrip('/')
            api_key = provider.get('apiKey', '')
            model_id = conv.get('modelId', provider.get('models', [{}])[0].get('id', '') if provider.get('models') else '')

            if not api_base or not api_key:
                error_text = 'Provider API 配置不完整，请检查 apiBase 和 apiKey。'
                yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
                full_content = error_text
                return

            messages = []
            system_prompt = conv.get('systemPrompt') or config.get('systemPrompt', '')
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            for msg in conv.get('messages', []):
                role = msg.get('role')
                # F01: 跳过 tool 结果消息 — 普通聊天不需要，OpenAI 会因缺少配套 tools 定义而报 400
                if role == 'tool':
                    continue
                # F01: 跳过含 tool_calls 的 assistant 消息（content 通常为 None，只有工具调用）
                if role == 'assistant' and msg.get('tool_calls'):
                    continue
                messages.append({'role': role, 'content': msg.get('content')})

            temperature = body.get('temperature', config.get('temperature', 0.7))
            max_tokens = body.get('maxTokens', config.get('maxTokens', 4096))
            top_p = body.get('topP', config.get('topP', 1.0))

            payload = {
                'model': model_id,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'top_p': top_p,
                'stream': True,
            }

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }

            # F14: 迁移到 httpx.AsyncClient 异步流式调用（与 Agent 模式保持一致），
            # 消除 async 路由内同步 requests.post 阻塞事件循环的问题。
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                async with client.stream(
                    'POST',
                    f'{api_base}/chat/completions',
                    json=payload,
                    headers=headers,
                ) as resp:
                    # 强制使用 UTF-8 解码上游 SSE，避免部分 Provider 未声明 charset 时
                    # 默认按 ISO-8859-1 解码导致中文乱码。
                    resp.encoding = 'utf-8'

                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        error_text = f'API 请求失败 (HTTP {resp.status_code}): {error_body.decode(errors="replace")[:200]}'
                        yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
                        full_content = error_text
                        return

                    async for line in resp.aiter_lines():
                        if stop_event.is_set():
                            break
                        if not line:
                            continue
                        if line.startswith('data: '):
                            payload_str = line[6:]
                            if payload_str.strip() == '[DONE]':
                                break
                            try:
                                chunk = json.loads(payload_str)
                                delta = chunk.get('choices', [{}])[0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    full_content += content
                                    yield _sse({"id": assistant_msg_id, "delta": content, "done": False})
                            except json.JSONDecodeError:
                                continue

        except httpx.TimeoutException:
            error_text = '请求超时，请检查网络连接或 API 地址。'
            yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
            full_content = error_text
        except httpx.ConnectError:
            error_text = '无法连接到 API 服务器，请检查 apiBase 配置。'
            yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
            full_content = error_text
        except Exception as e:
            error_text = f'发生未知错误: {str(e)}'
            yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
            full_content = error_text
        finally:
            _stop_events.pop(assistant_msg_id, None)
            # F14: generate() 改为 async def 后可直接 await store，不再需要
            # _save_assistant_message 同步桥接辅助函数。
            # F10: 持久化失败警告必须在 done 事件前发送，故 done:True 集中在 finally 末尾，
            # 确保任何持久化警告（若有）都先于 done 事件抵达前端。
            try:
                await _get_store().append_message(conv_id, {
                    'id': assistant_msg_id,
                    'role': 'assistant',
                    'content': full_content,
                    'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
                    'model': conv.get('modelId', ''),
                    'updatedAt': datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                _log.exception('failed to persist assistant message for conversation %s', conv_id)
                yield _sse({"id": assistant_msg_id, "delta": "\n\n⚠️ 消息持久化失败，刷新后可能丢失此回复", "done": False})
            yield _sse({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})

    return Response(
        generate(),
        mimetype='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@chat_bp.route('/stop', methods=['POST'])
async def stop_generation():
    body = await request.get_json(silent=True)
    if not body or 'messageId' not in body:
        return jsonify({'ok': False, 'error': 'missing messageId'}), 400
    stop_event = _stop_events.get(body['messageId'])
    if stop_event:
        stop_event.set()
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'message not found'}), 404


# ── Config ─────────────────────────────────────────────────

@chat_bp.route('/config', methods=['GET'])
def get_config():
    config = _read_json(CONFIG_FILE, {})
    return jsonify({'ok': True, 'config': config})


@chat_bp.route('/config', methods=['POST'])
async def save_config():
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400
    config = _read_json(CONFIG_FILE, {})

    # 逐字段校验参数类型和范围，防止越界值导致 LLM 异常行为
    if 'defaultProviderId' in body:
        v = body['defaultProviderId']
        if not isinstance(v, str):
            return jsonify({'ok': False, 'error': 'defaultProviderId must be a string'}), 400
        config['defaultProviderId'] = v

    if 'defaultModelId' in body:
        v = body['defaultModelId']
        if not isinstance(v, str):
            return jsonify({'ok': False, 'error': 'defaultModelId must be a string'}), 400
        config['defaultModelId'] = v

    if 'temperature' in body:
        v = body['temperature']
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'temperature must be a number'}), 400
        if not (0.0 <= v <= 2.0):
            return jsonify({'ok': False, 'error': 'temperature must be between 0 and 2'}), 400
        config['temperature'] = float(v)

    if 'maxTokens' in body:
        v = body['maxTokens']
        if not isinstance(v, int) or isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'maxTokens must be an integer'}), 400
        if not (1 <= v <= 128000):
            return jsonify({'ok': False, 'error': 'maxTokens must be between 1 and 128000'}), 400
        config['maxTokens'] = v

    if 'topP' in body:
        v = body['topP']
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'topP must be a number'}), 400
        if not (0.0 <= v <= 1.0):
            return jsonify({'ok': False, 'error': 'topP must be between 0 and 1'}), 400
        config['topP'] = float(v)

    if 'systemPrompt' in body:
        v = body['systemPrompt']
        if not isinstance(v, str):
            return jsonify({'ok': False, 'error': 'systemPrompt must be a string'}), 400
        if len(v) > 10000:
            return jsonify({'ok': False, 'error': 'systemPrompt exceeds max length 10000'}), 400
        config['systemPrompt'] = v

    _write_json(CONFIG_FILE, config)
    return jsonify({'ok': True, 'config': config})


# ── Presets ────────────────────────────────────────────────

@chat_bp.route('/presets', methods=['GET'])
def list_presets():
    data = _read_json(PRESETS_FILE, {'presets': []})
    return jsonify({'ok': True, 'presets': data.get('presets', [])})


@chat_bp.route('/presets', methods=['POST'])
async def save_preset():
    body = await request.get_json(silent=True)
    if not body or 'name' not in body:
        return jsonify({'ok': False, 'error': 'missing name'}), 400

    data = _read_json(PRESETS_FILE, {'presets': []})
    preset_id = body.get('id', str(uuid.uuid4()))

    existing = next((p for p in data['presets'] if p['id'] == preset_id), None)
    if existing:
        for key in ('name', 'systemPrompt', 'temperature', 'maxTokens', 'topP'):
            if key in body:
                existing[key] = body[key]
    else:
        data['presets'].append({
            'id': preset_id,
            'name': body['name'],
            'systemPrompt': body.get('systemPrompt', ''),
            'temperature': body.get('temperature', 0.7),
            'maxTokens': body.get('maxTokens', 4096),
            'topP': body.get('topP', 1.0),
        })

    _write_json(PRESETS_FILE, data)
    return jsonify({'ok': True, 'id': preset_id})


@chat_bp.route('/presets/<preset_id>', methods=['DELETE'])
def delete_preset(preset_id):
    data = _read_json(PRESETS_FILE, {'presets': []})
    data['presets'] = [p for p in data['presets'] if p['id'] != preset_id]
    _write_json(PRESETS_FILE, data)
    return jsonify({'ok': True})


# ── Agent mode (Stage 8) ─────────────────────────────────────

from typing import Dict, Any

# 智能体停止事件字典（convId 键 + asyncio.Event，独立于 _stop_events）
agent_stop_events: Dict[str, asyncio.Event] = {}

# 当前活跃的智能体服务实例（convId -> AgentService），供确认端点查找
active_agents: Dict[str, Any] = {}


@chat_bp.route('/conversations/<conv_id>/agent-messages', methods=['POST'])
async def send_agent_message(conv_id):
    """智能体模式消息路由（异步 SSE 流）"""
    from services.tool_registry import ToolRegistry  # lazy import avoids circular dep
    from agent_modules.agent_core import AgentService
    body = await request.get_json(silent=True)
    if not body or 'content' not in body:
        return jsonify({'ok': False, 'error': 'missing content'}), 400
    # F15: 校验空内容，避免空消息触发 Agent 循环
    if not body['content'] or not body['content'].strip():
        return jsonify({'ok': False, 'error': 'content is empty'}), 400

    store = _get_store()
    conv = await store.get(conv_id)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404

    # F07: 校验 agent mode 是否启用；未启用则拒绝，避免普通对话误用 Agent 端点
    agent_config = conv.get('agentConfig') or {}
    if not agent_config.get('enabled', False):
        return jsonify({'ok': False, 'error': 'agent mode not enabled for this conversation'}), 400

    providers = _read_json(PROVIDERS_FILE, {'providers': []}).get('providers', [])
    provider = next((p for p in providers if p['id'] == conv.get('providerId')), None)

    if not provider:
        return jsonify({'ok': False, 'error': 'provider not configured'}), 400

    now = datetime.now(timezone.utc).isoformat()
    user_msg = {
        'id': str(uuid.uuid4()),
        'role': 'user',
        'content': body['content'],
        'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    conv['messages'].append(user_msg)

    if len(conv['messages']) <= 2:
        title = body['content'][:50] + ('...' if len(body['content']) > 50 else '')
        await store.update(conv_id, {'title': title, 'updatedAt': now})
        conv['title'] = title

    conv['updatedAt'] = now
    await store.append_message(conv_id, user_msg)

    # 将"限缩过滤器"与"系统提示词展示路径"解耦
    # limit_path 来自 agentConfig.projectPath（未设置时为 None，触发多项目白名单）
    # display_path 用于系统提示词 <<PROJECT_PATH>> 占位符展示
    agent_config = conv.get('agentConfig') or {}
    limit_path = agent_config.get('projectPath') or None  # None → 多项目白名单
    display_path = _resolve_project_for_conversation(conv)

    registry = ToolRegistry.get_instance()
    model_id = conv.get('modelId', '') or next(
        iter(provider.get('models') or [{}]), {}
    ).get('id', '')

    # F03/F16: 并发检查 + 原子注册。检查与注册之间不得插入 await，避免并发空窗。
    # 所有提前返回路径（provider not found、enabled 校验失败等）均在此注册之前，
    # 因此不会出现 agent_stop_events / active_agents 残留泄漏。
    if conv_id in active_agents:
        return jsonify({
            'ok': False,
            'error': 'agent is already running for this conversation',
            'code': 'AGENT_BUSY',
        }), 409

    agent_stop_events[conv_id] = asyncio.Event()
    agent = AgentService(registry, display_path, model_id=model_id,
                         stop_event=agent_stop_events[conv_id],
                         limit_path=limit_path)
    active_agents[conv_id] = agent

    async def generate():
        try:
            async for event_str in agent.process_message(conv_id, body['content']):
                yield event_str.encode('utf-8')
        finally:
            await agent.close()
            agent_stop_events.pop(conv_id, None)
            active_agents.pop(conv_id, None)

    return Response(
        generate(),
        mimetype='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


def _resolve_project_for_conversation(conv: dict) -> str:
    """解析对话关联的项目路径（仅用于系统提示词展示，不影响路径白名单）

    优先级：
    1. conv.agentConfig.projectPath（对话级显式绑定）
    2. 第一个注册项目（回退）
    3. 用户主目录 ~/.ZaoWu 安全沙箱（F19 最终回退，避免暴露服务器源码目录）
    """
    agent_config = conv.get('agentConfig') or {}
    project_path = agent_config.get('projectPath', '')
    if project_path and os.path.isdir(project_path):
        return project_path

    try:
        from routes.explorer import read_projects
        projects = read_projects()
        if projects:
            return projects[0].get('path', os.getcwd())
    except Exception:
        pass

    # F19: 无项目时回退到 ~/.ZaoWu 安全沙箱，而非 os.getcwd()（服务器启动目录）
    home_zaowu = os.path.join(os.path.expanduser('~'), '.ZaoWu')
    os.makedirs(home_zaowu, exist_ok=True)
    return home_zaowu


@chat_bp.route('/agent-stop', methods=['POST'])
async def agent_stop():
    """停止智能体模式生成（convId 键，非 messageId）"""
    body = await request.get_json(silent=True)
    if not body or 'convId' not in body:
        return jsonify({'ok': False, 'error': 'missing convId'}), 400

    # F11: 设置停止事件，立即中断 Agent 循环与确认等待
    stop_event = agent_stop_events.get(body['convId'])
    if stop_event:
        stop_event.set()

    # F11: 同时拒绝所有待确认操作，立即释放确认等待（防御 stop_event 传播失败的场景）。
    # 遍历 _pending_confirmation_ids（F12 权威待确认集合），覆盖 event 尚未创建的竞态。
    agent = active_agents.get(body['convId'])
    if agent:
        for request_id in list(agent._pending_confirmation_ids):
            agent.submit_confirmation(request_id, False)

    return jsonify({'ok': True})


@chat_bp.route('/conversations/<conv_id>/confirm-tool', methods=['POST'])
async def confirm_tool(conv_id):
    """用户对需要确认的工具调用进行批准/拒绝"""
    body = await request.get_json(silent=True) or {}
    request_id = body.get('requestId')
    approved = body.get('approved')

    if not request_id:
        return jsonify({'ok': False, 'error': 'missing requestId'}), 400
    if not isinstance(approved, bool):
        return jsonify({'ok': False, 'error': 'approved must be boolean'}), 400

    agent = active_agents.get(conv_id)
    if not agent:
        return jsonify({'ok': False, 'error': 'no active agent for this conversation'}), 404

    ok = agent.submit_confirmation(request_id, approved)
    if not ok:
        # F17: request_id 既不在待确认集合中，也没有正在等待的 event（已过期/重复/伪造）
        return jsonify({
            'ok': False,
            'error': 'confirmation event not found or already resolved',
        }), 410  # Gone
    return jsonify({'ok': True})
