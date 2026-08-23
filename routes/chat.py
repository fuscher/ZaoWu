import os
import json
import uuid
import asyncio
import logging
import threading
import ipaddress
import socket
import requests
import httpx
from datetime import datetime, timezone
from urllib.parse import urlparse
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


# OpenAI 兼容服务上下文窗口字段名清单：不同服务字段名不一，
# 取第一个可解析为 int 的字段值（如 131072 / "131072" / "128K"）。
_CONTEXT_LENGTH_KEYS = (
    'context_length', 'contextLength', 'context_window',
    'max_context_length', 'max_model_len', 'max_length', 'context_size',
)


def _pick_context_length(model: dict):
    for key in _CONTEXT_LENGTH_KEYS:
        v = model.get(key)
        if v is None:
            continue
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace('K', '000')
            if s.isdigit():
                return int(s)
    return None


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
            'maxTokensAuto': True,
            'topP': 1.0,
            'systemPrompt': 'You are a helpful assistant.',
        })
    if not os.path.exists(PRESETS_FILE):
        _write_json(PRESETS_FILE, {'presets': []})


_init_data_files()


# SSRF 防护：拒绝私网、链路本地及元数据地址。
# 允许回环地址（127.0.0.0/8、localhost、::1），以兼容本地 LLM 服务（Ollama/LM Studio）。
_PRIVATE_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('0.0.0.0/32'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]


def _is_private_host(hostname: str) -> bool:
    """判断主机名是否解析到私网或链路本地地址（回环地址除外）。"""
    if not hostname:
        return True
    hostname_lower = hostname.lower()
    # 明确允许 localhost / 127.* / ::1，但继续拦截 0.0.0.0
    if hostname_lower == '0.0.0.0':
        return True
    if hostname_lower == 'localhost' or hostname_lower.startswith('127.'):
        return False
    try:
        addr = ipaddress.ip_address(hostname)
        # 显式放行回环（IPv4 127/8 已由字符串判断覆盖；此处处理 ::1）
        if addr.is_loopback:
            return False
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None)
        for info in infos:
            ip = info[4][0]
            try:
                addr = ipaddress.ip_address(ip)
                if addr.is_loopback:
                    return False
                if any(addr in net for net in _PRIVATE_NETWORKS):
                    return True
            except ValueError:
                continue
    except socket.gaierror:
        # 无法解析的主机名无法确认安全，保守拒绝
        return True
    return False


def validate_api_base(api_base: str) -> tuple[bool, str]:
    """校验 apiBase 是否指向可公开访问的 HTTP/HTTPS URL，防止 SSRF。

    拒绝私网、链路本地及元数据地址；允许回环地址以支持本地模型服务；
    DNS 解析失败则拒绝。
    """
    if not isinstance(api_base, str) or not api_base.strip():
        return True, ''
    api_base = api_base.strip()

    if not api_base.startswith(('http://', 'https://')):
        return False, 'apiBase must start with http:// or https://'
    if '\x00' in api_base or '\r' in api_base or '\n' in api_base:
        return False, 'apiBase contains invalid characters'

    try:
        parsed = urlparse(api_base)
    except ValueError:
        return False, 'apiBase is not a valid URL'

    hostname = parsed.hostname
    if not hostname:
        return False, 'apiBase has no valid host'

    if _is_private_host(hostname):
        return False, 'apiBase points to a private or local address which is not allowed'

    return True, ''


# ── Provider Presets ─────────────────────────────────────────

# 内置主流供应商预设：用户仅需填入 API Key 即可完成快捷配置。
# protocol: openai=OpenAI 兼容 /chat/completions；anthropic=Messages API。
# authType: bearer=Authorization: Bearer；x-api-key=请求头 x-api-key；none=无需鉴权。
PROVIDER_PRESETS = [
    {
        'id': 'openai',
        'name': 'OpenAI',
        'apiBase': 'https://api.openai.com/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://platform.openai.com/api-keys',
        'modelHint': ['gpt-5.5', 'gpt-5.4-mini'],
    },
    {
        'id': 'deepseek',
        'name': 'DeepSeek',
        'apiBase': 'https://api.deepseek.com/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://platform.deepseek.com/api_keys',
        'modelHint': ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp'],
    },
    {
        'id': 'zhipu',
        'name': '智谱 AI (GLM)',
        'apiBase': 'https://open.bigmodel.cn/api/paas/v4',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://open.bigmodel.cn/usercenter/apikeys',
        'modelHint': ['glm-5.1', 'glm-5.2', 'glm-5.3'],
    },
    {
        'id': 'qwen',
        'name': '通义千问 (DashScope)',
        'apiBase': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://bailian.console.aliyun.com/',
        'modelHint': ['qwen-max', 'qwen-plus', 'qwen-turbo'],
    },
    {
        'id': 'moonshot',
        'name': 'Kimi (Moonshot)',
        'apiBase': 'https://api.moonshot.cn/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://platform.moonshot.cn/console/api-keys',
        'modelHint': ['kimi-k2.7-code', 'kimi-k3', 'kimi-k2.6'],
    },
    {
        'id': 'gemini',
        'name': 'Google Gemini',
        'apiBase': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://aistudio.google.com/apikey',
        'modelHint': ['gemini-3.5-flash', 'gemini-2.5-flash', 'gemini-2.0-flash'],
    },
    {
        'id': 'anthropic',
        'name': 'Anthropic Claude',
        'apiBase': 'https://api.anthropic.com',
        'protocol': 'anthropic',
        'authType': 'x-api-key',
        'chatPath': '/v1/messages',
        'docsUrl': 'https://console.anthropic.com/settings/keys',
        'modelHint': ['claude-sonnet-4.6', 'claude-opus-4.8', 'claude-haiku-4.5'],
    },
    {
        'id': 'Xiaomi MiMo',
        'name': '小米MiMo',
        'apiBase': 'https://platform.xiaomimimo.com/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://mimo.mi.com',
        'modelHint': ['mimo-v2.5-pro', 'mimo-v2.5'],
    },
    {
        'id': 'Xiaomi MiMo Token Plan',
        'name': '小米MiMo Token Plan',
        'apiBase': 'https://token-plan-cn.xiaomimimo.com/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://mimo.mi.com',
        'modelHint': ['mimo-v2.5-pro', 'mimo-v2.5'],
    },
    {
        'id': 'openrouter',
        'name': 'OpenRouter',
        'apiBase': 'https://openrouter.ai/api/v1',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://openrouter.ai/keys',
        'modelHint': [],
    },
    {
        'id': 'ollama',
        'name': 'Ollama（本地）',
        'apiBase': 'http://localhost:11434/v1',
        'protocol': 'openai',
        'authType': 'none',
        'docsUrl': 'https://ollama.com/',
        'modelHint': [],
    },
    {
        'id': 'qianfan',
        'name': '百度千帆',
        'apiBase': 'https://qianfan.baidubce.com/v2',
        'protocol': 'openai',
        'authType': 'bearer',
        'docsUrl': 'https://console.bce.baidu.com/qianfan/',
        'modelHint': ['qianfan-code-latest'],
    },
]

# 预设备份：按 id 索引
_PRESET_BY_ID = {p['id']: p for p in PROVIDER_PRESETS}


def _models_url_for(api_base: str, protocol: str) -> str:
    """按协议推导模型列表端点。

    openai 兼容：{apiBase}/models（apiBase 通常已含 /v1）；
    anthropic：{apiBase}/v1/models（官方 Messages API 的模型端点）。
    """
    base = api_base.rstrip('/')
    if protocol == 'anthropic':
        return f'{base}/v1/models'
    return f'{base}/models'


def _auth_headers(api_key: str, auth_type: str, protocol: str) -> dict:
    """按鉴权方式构造请求头。auth_type: bearer | x-api-key | none"""
    headers = {'Content-Type': 'application/json'}
    key = (api_key or '').strip()
    if auth_type == 'x-api-key':
        headers['x-api-key'] = key
        if protocol == 'anthropic':
            headers['anthropic-version'] = '2023-06-01'
    elif auth_type != 'none' and key:
        headers['Authorization'] = f'Bearer {key}'
    return headers


def _parse_models_response(raw) -> list:
    """结构容错解析模型列表响应：兼容 {data:[...]} 与裸数组两种形态。"""
    result = raw if isinstance(raw, dict) else {}
    raw_list = result.get('data') if isinstance(result, dict) else raw
    models = []
    for m in raw_list or []:
        if not isinstance(m, dict):
            continue
        mid = m.get('id', '')
        if not mid:
            continue
        models.append({
            'id': mid,
            # 显示名称：anthropic 用 display_name；openai 兼容服务用 id 兜底
            'name': m.get('display_name') or m.get('name') or mid,
            # 字段名兜底：不同 OpenAI 兼容服务上下文窗口字段名不一
            'contextLength': _pick_context_length(m),
        })
    return models


@chat_bp.route('/provider-presets', methods=['GET'])
def get_provider_presets():
    return jsonify({'ok': True, 'presets': PROVIDER_PRESETS})


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
        # apiBase: 必须是可公开访问的 HTTPS/HTTP URL，防止 SSRF
        api_base = p.get('apiBase', '')
        if isinstance(api_base, str) and api_base.strip():
            valid, err = validate_api_base(api_base.strip())
            if not valid:
                return jsonify({'ok': False, 'error': f'provider {pid}: {err}'}), 400
        # apiKey: 类型校验
        api_key = p.get('apiKey', '')
        if not isinstance(api_key, str):
            return jsonify({'ok': False, 'error': f'provider {pid}: apiKey must be a string'}), 400
        # 可选字段类型校验（预设标记 / 协议 / 鉴权 / 自定义路径），向后兼容旧数据
        for field in ('presetId', 'protocol', 'authType', 'chatPath'):
            v = p.get(field)
            if v is not None and not isinstance(v, str):
                return jsonify({'ok': False, 'error': f'provider {pid}: {field} must be a string'}), 400
        if p.get('protocol') not in (None, 'openai', 'anthropic'):
            return jsonify({'ok': False, 'error': f'provider {pid}: protocol must be openai or anthropic'}), 400
        if p.get('authType') not in (None, 'bearer', 'x-api-key', 'none'):
            return jsonify({'ok': False, 'error': f'provider {pid}: authType must be bearer, x-api-key or none'}), 400
        validated.append(p)

    _write_json(PROVIDERS_FILE, {'providers': validated})
    return jsonify({'ok': True})


# ── Models (proxy to provider API) ────────────────────────

def _fetch_models_sync(api_base: str, api_key: str, protocol: str = 'openai',
                       auth_type: str = 'bearer') -> tuple[bool, str, list]:
    """按协议/鉴权方式拉取供应商模型列表（同步阻塞，仅用于模型管理接口）。

    返回 (ok, error, models)：ok=False 时 error 为失败原因，models 为空。
    """
    valid, err = validate_api_base(api_base)
    if not valid:
        return False, err, []
    try:
        headers = _auth_headers(api_key, auth_type, protocol)
        resp = requests.get(
            _models_url_for(api_base, protocol), headers=headers, timeout=10
        )
        if resp.status_code != 200:
            return False, f'HTTP {resp.status_code}: {resp.text[:200]}', []
        try:
            result = resp.json()
        except ValueError:
            return False, '响应不是合法 JSON', []
        return True, '', _parse_models_response(result)
    except requests.RequestException as e:
        return False, f'网络错误: {e}', []


@chat_bp.route('/models/fetch', methods=['POST'])
async def fetch_models_by_config():
    """临时拉取模型列表（不落盘）：供设置弹窗在保存供应商前预览/导入。

    body: {apiBase, apiKey?, protocol?, authType?, chatPath?}
    与 GET /models/<provider_id> 复用同一协议感知逻辑，但配置来自请求体。
    """
    body = await request.get_json(silent=True)
    if not body or not isinstance(body.get('apiBase'), str) or not body['apiBase'].strip():
        return jsonify({'ok': False, 'error': 'apiBase is required'}), 400
    api_base = body['apiBase'].strip()
    api_key = body.get('apiKey', '')
    if not isinstance(api_key, str):
        return jsonify({'ok': False, 'error': 'apiKey must be a string'}), 400
    protocol = body.get('protocol') or 'openai'
    if protocol not in ('openai', 'anthropic'):
        return jsonify({'ok': False, 'error': 'protocol must be openai or anthropic'}), 400
    auth_type = body.get('authType') or 'bearer'
    if auth_type not in ('bearer', 'x-api-key', 'none'):
        return jsonify({'ok': False, 'error': 'authType must be bearer, x-api-key or none'}), 400

    ok, err, models = _fetch_models_sync(api_base, api_key, protocol, auth_type)
    if not ok:
        return jsonify({'ok': False, 'error': f'拉取模型失败: {err}'}), 502
    return jsonify({'ok': True, 'models': models})


@chat_bp.route('/models/<provider_id>', methods=['GET'])
def get_models(provider_id):
    data = _read_json(PROVIDERS_FILE, {'providers': []})
    provider = next((p for p in (data.get('providers') or []) if p['id'] == provider_id), None)
    if not provider:
        return jsonify({'ok': False, 'error': 'provider not found'}), 404

    api_base = provider.get('apiBase', '').rstrip('/')
    api_key = provider.get('apiKey', '')
    protocol = provider.get('protocol') or 'openai'
    auth_type = provider.get('authType') or 'bearer'

    if not api_base:
        return jsonify({'ok': True, 'models': provider.get('models', [])})
    # 无鉴权且未填 Key 的协议（如 Ollama）允许直接拉取；否则 Key 缺失则回退本地列表
    if auth_type not in ('none',) and not api_key:
        return jsonify({'ok': True, 'models': provider.get('models', [])})

    ok, err, models = _fetch_models_sync(api_base, api_key, protocol, auth_type)
    if ok:
        provider['models'] = models
        _write_json(PROVIDERS_FILE, data)
        return jsonify({'ok': True, 'models': models})
    # 拉取失败（网络/鉴权等）：回退本地已存模型，避免前端报错
    _log.warning('get_models provider=%s fetch failed: %s', provider_id, err)
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

    # 类型校验：与 PATCH 一致，防止非字符串/非 dict 写入后破坏字符串拼接或 .get 调用
    for key in ('title', 'providerId', 'modelId', 'systemPrompt'):
        if key in body and not isinstance(body[key], str):
            return jsonify({'ok': False, 'error': f'{key} must be a string'}), 400
    # maxTokens 类型/范围校验：与 POST /config 一致（int、拒绝 bool、1~1000000）
    if 'maxTokens' in body:
        v = body['maxTokens']
        if not isinstance(v, int) or isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'maxTokens must be an integer'}), 400
        if not (1 <= v <= 1000000):
            return jsonify({'ok': False, 'error': 'maxTokens must be between 1 and 1000000'}), 400
    agent_config = body.get('agentConfig')
    if agent_config is not None and not isinstance(agent_config, dict):
        return jsonify({'ok': False, 'error': 'agentConfig must be an object'}), 400
    if isinstance(agent_config, dict):
        sp = agent_config.get('systemPrompt')
        if sp is not None and not isinstance(sp, str):
            return jsonify({'ok': False, 'error': 'agentConfig.systemPrompt must be a string'}), 400

    conv = {
        'id': conv_id,
        'title': body.get('title', '新对话'),
        'providerId': body.get('providerId', config.get('defaultProviderId', '')),
        'modelId': body.get('modelId', config.get('defaultModelId', '')),
        'systemPrompt': body.get('systemPrompt', config.get('systemPrompt', '')),
        'maxTokens': body.get('maxTokens', config.get('maxTokens', 4096)),
        'messages': [],
        'createdAt': now,
        'updatedAt': now,
        'agentConfig': agent_config or {
            'enabled': False,
            'maxIterations': 10,
            'requiresApproval': False,
        },
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

    # 字符串字段类型校验：非字符串（dict/list/int/null）写入后会破坏后续字符串拼接
    # （如 context_service 的 body += ...）或前端展示（title: null 覆盖为 NULL）。
    # 必须为字符串，null 也不接受（与已修的 NoneType 崩溃同族：类型假设被打破）。
    for key in ('title', 'providerId', 'modelId', 'systemPrompt'):
        if key in body and not isinstance(body[key], str):
            return jsonify({'ok': False, 'error': f'{key} must be a string'}), 400

    for key in ('title', 'providerId', 'modelId', 'systemPrompt'):
        if key in body:
            conv[key] = body[key]

    # maxTokens 类型/范围校验：与 POST /config 一致（int、拒绝 bool、1~1000000）
    if 'maxTokens' in body:
        v = body['maxTokens']
        if not isinstance(v, int) or isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'maxTokens must be an integer'}), 400
        if not (1 <= v <= 1000000):
            return jsonify({'ok': False, 'error': 'maxTokens must be between 1 and 1000000'}), 400
        conv['maxTokens'] = v

    # 支持更新 agentConfig
    if 'agentConfig' in body:
        agent_config = body['agentConfig']
        # null → 空对象（与历史 `or {}` 行为兼容）；非 dict（str/list/int）直接拒绝，
        # 否则 .pop/.get 会在 PATCH 自身或后续 agent_service._build_approval_rules
        # 里抛 AttributeError → 500 / 对话中断。
        if agent_config is None:
            agent_config = {}
        elif not isinstance(agent_config, dict):
            return jsonify({'ok': False, 'error': 'agentConfig must be an object'}), 400
        # agentConfig.systemPrompt 必须为字符串：context_service.build 用 `body += str`
        # 拼接技能段，非字符串会 TypeError 中断整轮对话。
        sp = agent_config.get('systemPrompt')
        if sp is not None and not isinstance(sp, str):
            return jsonify({'ok': False, 'error': 'agentConfig.systemPrompt must be a string'}), 400
        # selectedSkill 字段废弃（技能改为「全部启用即生效」）：
        # 若客户端仍传，静默忽略（不校验、不存储）。skillConfig 仍按 per-skill 透传。
        agent_config.pop('selectedSkill', None)
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

    providers = _read_json(PROVIDERS_FILE, {'providers': []}).get('providers') or []
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
            protocol = provider.get('protocol') or 'openai'
            auth_type = provider.get('authType') or 'bearer'
            # 自定义请求路径：预设/自定义供应商可覆盖；默认按协议推导
            chat_path = provider.get('chatPath') or (
                '/v1/messages' if protocol == 'anthropic' else '/chat/completions'
            )
            model_id = conv.get('modelId', provider.get('models', [{}])[0].get('id', '') if provider.get('models') else '')

            if not api_base:
                error_text = 'Provider API 配置不完整，请检查 apiBase。'
                yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
                full_content = error_text
                return

            # 鉴权方式为 none（如 Ollama）时允许缺 Key；其余协议 Key 必填
            if auth_type != 'none' and not api_key:
                error_text = 'Provider API 配置不完整，请检查 apiKey。'
                yield _sse({"id": assistant_msg_id, "delta": error_text, "done": False})
                full_content = error_text
                return

            valid, err = validate_api_base(api_base)
            if not valid:
                error_text = f'Provider apiBase 不安全: {err}'
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
            # maxTokens 作为压缩预算可配置到 1M；作为 LLM 生成参数需钳制到 API 上限
            # （实测 opencode 等 API 拒绝 >131072 的 max_tokens；Anthropic 上限更低）
            max_tokens = min(
                body.get('maxTokens', config.get('maxTokens', 4096)),
                64000 if protocol == 'anthropic' else 131072,
            )
            top_p = body.get('topP', config.get('topP', 1.0))

            if protocol == 'anthropic':
                # Anthropic Messages API：system 独立字段，messages 剔除 system role；
                # max_tokens 必填。SSE 事件为 content_block_delta → delta.text。
                system_text = ''
                anthropic_messages = []
                for msg in messages:
                    if msg.get('role') == 'system':
                        system_text = msg.get('content') or ''
                    else:
                        anthropic_messages.append(msg)
                payload = {
                    'model': model_id,
                    'system': system_text,
                    'messages': anthropic_messages,
                    'max_tokens': max_tokens,
                    'temperature': temperature,
                    'stream': True,
                }
            else:
                payload = {
                    'model': model_id,
                    'messages': messages,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'top_p': top_p,
                    'stream': True,
                }

            headers = _auth_headers(api_key, auth_type, protocol)
            url = f'{api_base}{chat_path}'

            # F14: 迁移到 httpx.AsyncClient 异步流式调用（与 Agent 模式保持一致），
            # 消除 async 路由内同步 requests.post 阻塞事件循环的问题。
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                async with client.stream(
                    'POST',
                    url,
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
                                if protocol == 'anthropic':
                                    # 仅取文本增量；message_start / message_delta 等事件返回空
                                    delta_obj = chunk.get('delta') or {}
                                    content = delta_obj.get('text', '') if chunk.get('type') == 'content_block_delta' else ''
                                else:
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
        if not (1 <= v <= 1000000):
            return jsonify({'ok': False, 'error': 'maxTokens must be between 1 and 1000000'}), 400
        config['maxTokens'] = v

    if 'maxTokensAuto' in body:
        v = body['maxTokensAuto']
        if not isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'maxTokensAuto must be a boolean'}), 400
        config['maxTokensAuto'] = v

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
# 注意：停止/确认依赖这两个进程内字典，仅适用于单 worker 部署（当前 onedir 单进程打包）。
# 多 worker（如 uvicorn --workers >1）下 SSE 流与停止/确认请求可能落到不同进程导致失效；
# 如需多 worker，应改用共享存储（如 Redis）分发停止/确认事件。
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

    # maxTokens 类型/范围校验：与 POST /config 一致（int、拒绝 bool、1~1000000）。
    # 请求体携带 = 显式会话级设置；不带则不覆盖会话既有值。
    if 'maxTokens' in body:
        v = body['maxTokens']
        if not isinstance(v, int) or isinstance(v, bool):
            return jsonify({'ok': False, 'error': 'maxTokens must be an integer'}), 400
        if not (1 <= v <= 1000000):
            return jsonify({'ok': False, 'error': 'maxTokens must be between 1 and 1000000'}), 400
        conv['maxTokens'] = v

    providers = _read_json(PROVIDERS_FILE, {'providers': []}).get('providers') or []
    provider = next((p for p in providers if p['id'] == conv.get('providerId')), None)

    if not provider:
        return jsonify({'ok': False, 'error': 'provider not configured'}), 400

    # Agent 链路（llm_stream）仅支持 OpenAI 兼容协议：Anthropic 供应商在此明确拒绝，
    # 避免 401/404 模糊报错（普通聊天路径已适配 anthropic，不受影响）。
    if provider.get('protocol') == 'anthropic':
        return jsonify({
            'ok': False,
            'error': 'Agent 模式暂不支持 Anthropic 协议，请切换到 OpenAI 兼容供应商',
            'code': 'PROTOCOL_UNSUPPORTED',
        }), 400

    api_base = provider.get('apiBase', '').rstrip('/')
    valid, err = validate_api_base(api_base)
    if not valid:
        return jsonify({'ok': False, 'error': f'provider apiBase 不安全: {err}'}), 400

    now = datetime.now(timezone.utc).isoformat()
    user_msg = {
        'id': str(uuid.uuid4()),
        'role': 'user',
        'content': body['content'],
        'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    conv['messages'].append(user_msg)

    update_fields = {'updatedAt': now}
    if len(conv['messages']) <= 2:
        title = body['content'][:50] + ('...' if len(body['content']) > 50 else '')
        update_fields['title'] = title
        conv['title'] = title
    # maxTokens 随本次消息显式落库（AgentService 内部 _get_conversation 重读时生效）
    if 'maxTokens' in body:
        update_fields['maxTokens'] = conv['maxTokens']
    if len(update_fields) > 1:
        await store.update(conv_id, update_fields)

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
    """用户对需要确认的工具调用进行批准/拒绝（阶段三 6.1 三态确认）。

    请求体：
    - ``requestId``: 工具调用 request_id
    - ``approved``: bool，是否批准
    - ``scope``: 'once'（默认）| 'always'。always=批准时持久化为会话级 allow 规则
    - ``feedback``: str，拒绝原因（approved=False 时回喂模型）
    旧客户端只传 {requestId, approved} 仍兼容（scope=once, feedback=None）。
    """
    body = await request.get_json(silent=True) or {}
    request_id = body.get('requestId')
    approved = body.get('approved')
    scope = body.get('scope', 'once')
    feedback = body.get('feedback')

    if not request_id:
        return jsonify({'ok': False, 'error': 'missing requestId'}), 400
    if not isinstance(approved, bool):
        return jsonify({'ok': False, 'error': 'approved must be boolean'}), 400
    if scope not in ('once', 'always'):
        return jsonify({'ok': False, 'error': "scope must be 'once' or 'always'"}), 400

    agent = active_agents.get(conv_id)
    if not agent:
        return jsonify({'ok': False, 'error': 'no active agent for this conversation'}), 404

    ok = agent.submit_confirmation(request_id, approved, scope=scope, feedback=feedback)
    if not ok:
        # F17: request_id 既不在待确认集合中，也没有正在等待的 event（已过期/重复/伪造）
        return jsonify({
            'ok': False,
            'error': 'confirmation event not found or already resolved',
        }), 410  # Gone
    return jsonify({'ok': True})
