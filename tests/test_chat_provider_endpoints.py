"""LLM 供应商配置模块端点级测试（B4：评审计划补测）。

覆盖：
- B6  _auth_headers：anthropic-version 协议级头（与 authType 无关）
- B1  GET /models/<id> 合并语义（手动项/改名保留、API 新增项加入、失败不写盘）
-      _parse_models_response：openai {data} / anthropic display_name / 裸数组
- B2  _normalize_anthropic_messages：合并连续同角色/去前导 assistant/剔空
- C2  _migrate_providers + providers.json 写盘带 schemaVersion
- 端点：provider-presets 数量、models/fetch 协议透传、save_providers 向后兼容/整批校验
"""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from quart import Quart

# 直接加载 routes/chat.py，绕过 routes/__init__.py 的整包蓝图导入
# （community 等蓝图依赖 pycrdt，测试环境无需整包加载）。
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_chat_module():
    spec = importlib.util.spec_from_file_location(
        'routes_chat', _REPO_ROOT / 'routes' / 'chat.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chat_mod = _load_chat_module()


@pytest.fixture
def chat_app(tmp_path, monkeypatch):
    """独立 Quart app + 隔离的 providers.json（不触碰仓库根真实数据）。"""
    provider_file = tmp_path / 'providers.json'
    provider_file.write_text(
        json.dumps({'schemaVersion': 1, 'providers': []}), encoding='utf-8')
    monkeypatch.setattr(chat_mod, 'PROVIDERS_FILE', str(provider_file))
    app = Quart(__name__)
    app.register_blueprint(chat_mod.chat_bp, url_prefix='/api/chat')
    return app, provider_file


def _client_call(app, method, path, **kw):
    """同步包装 Quart 异步 test client 调用。"""
    async def run():
        client = app.test_client()
        resp = await getattr(client, method)(path, **kw)
        return resp.status_code, await resp.get_json()
    return asyncio.run(run())


# ── B6：_auth_headers（anthropic-version 与 authType 解耦）──────────

def test_auth_headers_anthropic_bearer_includes_version_header():
    h = chat_mod._auth_headers('sk-x', 'bearer', 'anthropic')
    assert h['anthropic-version'] == '2023-06-01'
    assert h['Authorization'] == 'Bearer sk-x'
    assert 'x-api-key' not in h


def test_auth_headers_anthropic_none_includes_version_header():
    h = chat_mod._auth_headers('', 'none', 'anthropic')
    assert h['anthropic-version'] == '2023-06-01'


def test_auth_headers_openai_bearer_no_version_header():
    h = chat_mod._auth_headers('sk-x', 'bearer', 'openai')
    assert 'anthropic-version' not in h
    assert h['Authorization'] == 'Bearer sk-x'


# ── _parse_models_response：结构容错 ────────────────────────────────

def test_parse_models_openai_data_shape():
    models = chat_mod._parse_models_response({'data': [{'id': 'gpt-4'}]})
    assert models == [{'id': 'gpt-4', 'name': 'gpt-4', 'contextLength': None}]


def test_parse_models_anthropic_display_name():
    models = chat_mod._parse_models_response(
        {'data': [{'id': 'claude-3', 'display_name': 'Claude 3'}]})
    assert models[0]['name'] == 'Claude 3'


def test_parse_models_bare_array():
    models = chat_mod._parse_models_response([{'id': 'm1'}])
    assert models[0]['id'] == 'm1'


# ── B2：_normalize_anthropic_messages ───────────────────────────────

def test_normalize_anthropic_merges_consecutive_same_role():
    msgs = [
        {'role': 'user', 'content': 'a'},
        {'role': 'user', 'content': 'b'},
        {'role': 'assistant', 'content': 'c'},
    ]
    out = chat_mod._normalize_anthropic_messages(msgs)
    assert [m['role'] for m in out] == ['user', 'assistant']
    assert out[0]['content'] == 'a\nb'


def test_normalize_anthropic_drops_leading_assistant():
    out = chat_mod._normalize_anthropic_messages([
        {'role': 'assistant', 'content': 'lead'},
        {'role': 'user', 'content': 'hi'},
    ])
    assert [m['role'] for m in out] == ['user']


def test_normalize_anthropic_drops_empty_and_invalid():
    out = chat_mod._normalize_anthropic_messages([
        {'role': 'user', 'content': ''},
        {'role': 'tool', 'content': 'x'},
        {'role': 'user', 'content': 'ok'},
    ])
    assert len(out) == 1 and out[0]['content'] == 'ok'


# ── C2：_migrate_providers ──────────────────────────────────────────

def test_migrate_providers_old_data_gets_schema_version():
    data = chat_mod._migrate_providers({'providers': [{'id': 'x'}]})
    assert data['schemaVersion'] == 1


def test_migrate_providers_malformed_falls_back():
    assert chat_mod._migrate_providers({'providers': 'nope'}) == {
        'schemaVersion': 1, 'providers': []}


# ── 端点：provider-presets ──────────────────────────────────────────

def test_provider_presets_endpoint(chat_app):
    app, _ = chat_app
    code, body = _client_call(app, 'get', '/api/chat/provider-presets')
    assert code == 200
    assert len(body['presets']) >= 12


# ── B1：GET /models/<id> 合并语义 ───────────────────────────────────

def test_get_models_merge_preserves_manual_and_renamed(chat_app, monkeypatch):
    """S15-P0-1 白名单优先：只刷新已存在项字段，不新增 API 独有模型（防膨胀）、保序。"""
    app, provider_file = chat_app
    seed = {
        'schemaVersion': 1,
        'providers': [{
            'id': 'p1',
            'apiBase': 'https://api.example.com/v1',
            'apiKey': 'k',
            'protocol': 'openai',
            'authType': 'bearer',
            'models': [
                {'id': 'gpt-4', 'name': '我的 GPT-4'},     # 用户改名（API 也返回该 id）
                {'id': 'local-model', 'name': '私有模型'},  # 手动添加（API 不返回）
            ],
        }],
    }
    provider_file.write_text(json.dumps(seed), encoding='utf-8')
    monkeypatch.setattr(chat_mod, '_fetch_models_sync', lambda *a, **kw: (
        True, '',
        [
            {'id': 'gpt-4', 'name': 'gpt-4', 'contextLength': 8192},
            {'id': 'gpt-5', 'name': 'gpt-5', 'contextLength': 131072},  # API 独有，不入白名单
        ]))

    code, body = _client_call(app, 'get', '/api/chat/models/p1')
    assert code == 200
    ids = [m['id'] for m in body['models']]
    assert ids == ['gpt-4', 'local-model']               # 不新增 API 独有模型、保序
    renamed = next(m for m in body['models'] if m['id'] == 'gpt-4')
    assert renamed['name'] == '我的 GPT-4'               # 用户改名保留
    assert renamed['contextLength'] == 8192              # API 侧字段刷新
    # 落盘结果与服务端返回一致
    on_disk = json.loads(provider_file.read_text(encoding='utf-8'))
    assert [m['id'] for m in on_disk['providers'][0]['models']] == ['gpt-4', 'local-model']


def test_get_models_fetch_failure_returns_local_without_write(chat_app, monkeypatch):
    app, provider_file = chat_app
    seed = {
        'schemaVersion': 1,
        'providers': [{
            'id': 'p1',
            'apiBase': 'https://api.example.com/v1',
            'apiKey': 'k',
            'models': [{'id': 'm1', 'name': 'm1'}],
        }],
    }
    provider_file.write_text(json.dumps(seed), encoding='utf-8')
    monkeypatch.setattr(chat_mod, '_fetch_models_sync',
                        lambda *a, **kw: (False, 'network down', []))

    code, body = _client_call(app, 'get', '/api/chat/models/p1')
    assert code == 200
    assert [m['id'] for m in body['models']] == ['m1']
    # 失败不写盘（文件字节不变）
    assert json.loads(provider_file.read_text(encoding='utf-8')) == seed


def test_get_models_local_empty_writes_all(chat_app, monkeypatch):
    """S15-P0-1: 本地 models 为空 → 拉取结果整列写入（首次填充）。"""
    app, provider_file = chat_app
    seed = {
        'schemaVersion': 1,
        'providers': [{
            'id': 'p1',
            'apiBase': 'https://api.example.com/v1',
            'apiKey': 'k',
            'protocol': 'openai',
            'authType': 'bearer',
            'models': [],
        }],
    }
    provider_file.write_text(json.dumps(seed), encoding='utf-8')
    monkeypatch.setattr(chat_mod, '_fetch_models_sync', lambda *a, **kw: (
        True, '',
        [
            {'id': 'a', 'name': 'A', 'contextLength': 8192},
            {'id': 'b', 'name': 'B', 'contextLength': None},
        ]))

    code, body = _client_call(app, 'get', '/api/chat/models/p1')
    assert code == 200
    assert [m['id'] for m in body['models']] == ['a', 'b']
    on_disk = json.loads(provider_file.read_text(encoding='utf-8'))
    assert [m['id'] for m in on_disk['providers'][0]['models']] == ['a', 'b']


def test_get_models_null_context_length_not_overwritten(chat_app, monkeypatch):
    """S15-P0-1: API 返回 null/缺失字段不覆盖用户已填值（contextLength 保留）。"""
    app, provider_file = chat_app
    seed = {
        'schemaVersion': 1,
        'providers': [{
            'id': 'p1',
            'apiBase': 'https://api.example.com/v1',
            'apiKey': 'k',
            'protocol': 'openai',
            'authType': 'bearer',
            'models': [{'id': 'gpt-4', 'name': 'gpt-4', 'contextLength': 8192}],
        }],
    }
    provider_file.write_text(json.dumps(seed), encoding='utf-8')
    monkeypatch.setattr(chat_mod, '_fetch_models_sync', lambda *a, **kw: (
        True, '',
        [{'id': 'gpt-4', 'name': 'gpt-4', 'contextLength': None}],
    ))

    code, body = _client_call(app, 'get', '/api/chat/models/p1')
    assert code == 200
    model = next(m for m in body['models'] if m['id'] == 'gpt-4')
    assert model['contextLength'] == 8192, 'API null 不应覆盖用户已填 contextLength'


# ── 端点：POST /models/fetch（协议透传 + display_name 映射）──────────

def test_fetch_models_by_config_anthropic_passthrough(chat_app, monkeypatch):
    captured = {}

    def fake_fetch(api_base, api_key, protocol, auth_type):
        captured.update(api_base=api_base, api_key=api_key,
                        protocol=protocol, auth_type=auth_type)
        # _fetch_models_sync 返回的是已解析格式（name 由 display_name 映射而来）
        return True, '', [{'id': 'claude-3', 'name': 'Claude 3'}]

    monkeypatch.setattr(chat_mod, '_fetch_models_sync', fake_fetch)
    app, _ = chat_app
    code, body = _client_call(
        app, 'post', '/api/chat/models/fetch',
        json={'apiBase': 'https://api.anthropic.com', 'apiKey': 'k',
              'protocol': 'anthropic', 'authType': 'bearer'})
    assert code == 200
    assert body['models'][0]['name'] == 'Claude 3'
    assert captured == {'api_base': 'https://api.anthropic.com', 'api_key': 'k',
                        'protocol': 'anthropic', 'auth_type': 'bearer'}


def test_fetch_models_by_config_ollama_no_key(chat_app, monkeypatch):
    captured = {}

    def fake_fetch(api_base, api_key, protocol, auth_type):
        captured.update(protocol=protocol, auth_type=auth_type)
        return True, '', [{'id': 'llama3', 'name': 'llama3'}]

    monkeypatch.setattr(chat_mod, '_fetch_models_sync', fake_fetch)
    app, _ = chat_app
    code, body = _client_call(
        app, 'post', '/api/chat/models/fetch',
        json={'apiBase': 'http://localhost:11434/v1', 'apiKey': '',
              'protocol': 'openai', 'authType': 'none'})
    assert code == 200
    assert body['models'][0]['id'] == 'llama3'
    assert captured == {'protocol': 'openai', 'auth_type': 'none'}


# ── 端点：POST /providers（向后兼容 + 整批校验）──────────────────────

def test_save_providers_backward_compat_old_fields(chat_app, monkeypatch):
    # 隔离网络：apiBase 校验依赖 DNS 解析，沙箱环境不稳定，直接放行
    monkeypatch.setattr(chat_mod, 'validate_api_base', lambda base: (True, ''))
    app, provider_file = chat_app
    code, body = _client_call(
        app, 'post', '/api/chat/providers',
        json={'providers': [{'id': 'old', 'name': '旧供应商',
                             'apiBase': 'https://api.example.com/v1'}]})
    assert code == 200
    on_disk = json.loads(provider_file.read_text(encoding='utf-8'))
    assert on_disk['schemaVersion'] == 1               # C2：写盘带版本
    assert on_disk['providers'][0]['id'] == 'old'
    assert on_disk['providers'][0].get('protocol') is None  # 未声明则原样保留


def test_save_providers_rejects_missing_id_with_pid(chat_app):
    app, _ = chat_app
    code, body = _client_call(
        app, 'post', '/api/chat/providers',
        json={'providers': [{'name': 'no-id'}]})
    assert code == 400
    assert 'id is required' in body['error']
