import os
import json
import uuid
import threading
import requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response

chat_bp = Blueprint('chat', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROVIDERS_FILE = os.path.join(BASE_DIR, 'providers.json')
CONVERSATIONS_FILE = os.path.join(BASE_DIR, 'conversations.json')
CONFIG_FILE = os.path.join(BASE_DIR, 'chat_config.json')
PRESETS_FILE = os.path.join(BASE_DIR, 'chat_presets.json')

_chat_lock = threading.Lock()
_stop_events = {}


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
    if not os.path.exists(CONVERSATIONS_FILE):
        _write_json(CONVERSATIONS_FILE, {'conversations': []})
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
def save_providers():
    body = request.get_json(silent=True)
    if not body or 'providers' not in body:
        return jsonify({'ok': False, 'error': 'missing providers'}), 400
    _write_json(PROVIDERS_FILE, {'providers': body['providers']})
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
def list_conversations():
    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    convs = data.get('conversations', [])
    convs.sort(key=lambda c: c.get('updatedAt', ''), reverse=True)
    summary = [{
        'id': c['id'],
        'title': c.get('title', ''),
        'providerId': c.get('providerId', ''),
        'modelId': c.get('modelId', ''),
        'createdAt': c.get('createdAt', ''),
        'updatedAt': c.get('updatedAt', ''),
        'messageCount': len(c.get('messages', [])),
    } for c in convs]
    return jsonify({'ok': True, 'conversations': summary})


@chat_bp.route('/conversations', methods=['POST'])
def create_conversation():
    body = request.get_json(silent=True)
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
    }

    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    data['conversations'].append(conv)
    _write_json(CONVERSATIONS_FILE, data)

    return jsonify({'ok': True, 'conversation': conv})


@chat_bp.route('/conversations/<conv_id>', methods=['GET'])
def get_conversation(conv_id):
    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    conv = next((c for c in data['conversations'] if c['id'] == conv_id), None)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404
    return jsonify({'ok': True, 'conversation': conv})


@chat_bp.route('/conversations/<conv_id>', methods=['PATCH'])
def update_conversation(conv_id):
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400

    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    conv = next((c for c in data['conversations'] if c['id'] == conv_id), None)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404

    for key in ('title', 'providerId', 'modelId', 'systemPrompt'):
        if key in body:
            conv[key] = body[key]
    conv['updatedAt'] = datetime.now(timezone.utc).isoformat()

    _write_json(CONVERSATIONS_FILE, data)
    return jsonify({'ok': True, 'conversation': conv})


@chat_bp.route('/conversations/<conv_id>', methods=['DELETE'])
def delete_conversation(conv_id):
    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    data['conversations'] = [c for c in data['conversations'] if c['id'] != conv_id]
    _write_json(CONVERSATIONS_FILE, data)
    return jsonify({'ok': True})


@chat_bp.route('/conversations/<conv_id>/clear', methods=['POST'])
def clear_conversation(conv_id):
    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    conv = next((c for c in data['conversations'] if c['id'] == conv_id), None)
    if not conv:
        return jsonify({'ok': False, 'error': 'conversation not found'}), 404

    conv['messages'] = []
    conv['updatedAt'] = datetime.now(timezone.utc).isoformat()
    _write_json(CONVERSATIONS_FILE, data)
    return jsonify({'ok': True, 'conversation': conv})


# ── Send Message (SSE streaming) ───────────────────────────

@chat_bp.route('/conversations/<conv_id>/messages', methods=['POST'])
def send_message(conv_id):
    body = request.get_json(silent=True)
    if not body or 'content' not in body:
        return jsonify({'ok': False, 'error': 'missing content'}), 400

    data = _read_json(CONVERSATIONS_FILE, {'conversations': []})
    conv = next((c for c in data['conversations'] if c['id'] == conv_id), None)
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
    }
    conv['messages'].append(user_msg)

    if not conv['messages'] or len(conv['messages']) == 1:
        conv['title'] = body['content'][:50] + ('...' if len(body['content']) > 50 else '')

    conv['updatedAt'] = now
    _write_json(CONVERSATIONS_FILE, data)

    assistant_msg_id = str(uuid.uuid4())
    stop_event = threading.Event()
    _stop_events[assistant_msg_id] = stop_event

    def generate():
        full_content = ''
        try:
            if not provider:
                error_text = '未配置 LLM 提供商，请先在设置中添加 Provider。'
                yield f'data: {json.dumps({"id": assistant_msg_id, "delta": error_text, "done": False})}\n\n'
                full_content = error_text
                yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'
                return

            api_base = provider.get('apiBase', '').rstrip('/')
            api_key = provider.get('apiKey', '')
            model_id = conv.get('modelId', provider.get('models', [{}])[0].get('id', '') if provider.get('models') else '')

            if not api_base or not api_key:
                error_text = 'Provider API 配置不完整，请检查 apiBase 和 apiKey。'
                yield f'data: {json.dumps({"id": assistant_msg_id, "delta": error_text, "done": False})}\n\n'
                full_content = error_text
                yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'
                return

            messages = []
            system_prompt = conv.get('systemPrompt') or config.get('systemPrompt', '')
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            for msg in conv.get('messages', []):
                messages.append({'role': msg['role'], 'content': msg['content']})

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

            resp = requests.post(
                f'{api_base}/chat/completions',
                json=payload,
                headers=headers,
                stream=True,
                timeout=120,
            )

            if resp.status_code != 200:
                error_text = f'API 请求失败 (HTTP {resp.status_code}): {resp.text[:200]}'
                yield f'data: {json.dumps({"id": assistant_msg_id, "delta": error_text, "done": False})}\n\n'
                full_content = error_text
                yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'
                return

            for line in resp.iter_lines(decode_unicode=True):
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
                            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": content, "done": False})}\n\n'
                    except json.JSONDecodeError:
                        continue

            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'

        except requests.exceptions.Timeout:
            error_text = '请求超时，请检查网络连接或 API 地址。'
            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": error_text, "done": False})}\n\n'
            full_content = error_text
            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'
        except requests.exceptions.ConnectionError:
            error_text = '无法连接到 API 服务器，请检查 apiBase 配置。'
            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": error_text, "done": False})}\n\n'
            full_content = error_text
            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'
        except Exception as e:
            error_text = f'发生未知错误: {str(e)}'
            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": error_text, "done": False})}\n\n'
            full_content = error_text
            yield f'data: {json.dumps({"id": assistant_msg_id, "delta": "", "done": True, "content": full_content})}\n\n'
        finally:
            _stop_events.pop(assistant_msg_id, None)
            _save_assistant_message(conv_id, assistant_msg_id, full_content)

    def _save_assistant_message(cid, msg_id, content):
        try:
            d = _read_json(CONVERSATIONS_FILE, {'conversations': []})
            c = next((cv for cv in d['conversations'] if cv['id'] == cid), None)
            if c:
                c['messages'].append({
                    'id': msg_id,
                    'role': 'assistant',
                    'content': content,
                    'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
                    'model': conv.get('modelId', ''),
                })
                c['updatedAt'] = datetime.now(timezone.utc).isoformat()
                _write_json(CONVERSATIONS_FILE, d)
        except Exception:
            pass

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@chat_bp.route('/stop', methods=['POST'])
def stop_generation():
    body = request.get_json(silent=True)
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
def save_config():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400
    config = _read_json(CONFIG_FILE, {})
    for key in ('defaultProviderId', 'defaultModelId', 'temperature', 'maxTokens', 'topP', 'systemPrompt'):
        if key in body:
            config[key] = body[key]
    _write_json(CONFIG_FILE, config)
    return jsonify({'ok': True, 'config': config})


# ── Presets ────────────────────────────────────────────────

@chat_bp.route('/presets', methods=['GET'])
def list_presets():
    data = _read_json(PRESETS_FILE, {'presets': []})
    return jsonify({'ok': True, 'presets': data.get('presets', [])})


@chat_bp.route('/presets', methods=['POST'])
def save_preset():
    body = request.get_json(silent=True)
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
