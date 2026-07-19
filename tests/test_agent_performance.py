"""Stage 8 性能基准测试。

仅作为抽检，阈值参考 Stage_8.md 成功标准并留有一定余量，
避免在 CI 或低速磁盘上因环境波动而失败。
"""
import asyncio
import json
import os
import time

import pytest

import agent_modules.agent_core.agent_service as agent_module
from agent_modules.agent_core import AgentService
from services.tool_executor import ToolExecutor
from services.tool_registry import ToolRegistry


def _noop_validate_terminal_path(cwd):
    return None


def _perf_search_project(project):
    """性能测试用的简化版 search_project（仅做文件名匹配，保留返回结构）。"""
    def _search(query: str, project_path: str = None) -> dict:
        query_lower = query.lower()
        results = []
        total_files = 0
        total_matches = 0
        for root, _dirs, files in os.walk(project):
            for filename in files:
                if query_lower in filename.lower():
                    total_files += 1
                    total_matches += 1
                    results.append({
                        'path': os.path.join(root, filename),
                        'name': filename,
                        'matches': [{'type': 'filename'}],
                    })
        return {
            'ok': True,
            'results': results,
            'totalFiles': total_files,
            'totalMatches': total_matches,
            'query': query,
        }
    return _search


@pytest.fixture
def perf_project(tmp_path):
    project = tmp_path / 'perf_project'
    project.mkdir()

    # 1 MB 文件（read_file 基准）
    (project / 'large.txt').write_text('x' * (1024 * 1024), encoding='utf-8')

    # 用于搜索的代码文件
    src = project / 'src'
    src.mkdir()
    for i in range(20):
        (src / f'module_{i}.py').write_text(
            f'def function_{i}():\n    return "ZaoWu benchmark"\n',
            encoding='utf-8',
        )

    return project


def test_read_file_1mb_within_threshold(perf_project):
    executor = ToolExecutor(ToolRegistry.get_instance(), project_bases=[str(perf_project)])
    path = str(perf_project / 'large.txt')

    start = time.monotonic()
    result = asyncio.run(executor.execute('read_file', {'path': path}))
    elapsed = time.monotonic() - start

    assert result['success'] is True
    # ToolExecutor 会对结果做 8000 字符截断，因此只校验时间阈值
    assert elapsed < 0.2, f'read_file took {elapsed:.3f}s, threshold 0.2s'


def test_search_code_within_threshold(perf_project, monkeypatch):
    # _search_code_tool 在 tool_registry 命名空间中持有 search_project 引用
    monkeypatch.setattr('services.tool_registry.search_project', _perf_search_project(perf_project))
    executor = ToolExecutor(ToolRegistry.get_instance(), project_bases=[str(perf_project)])

    start = time.monotonic()
    result = asyncio.run(executor.execute('search_code', {'query': 'module', 'project_path': str(perf_project)}))
    elapsed = time.monotonic() - start

    assert result['success'] is True
    payload = json.loads(result['content'])
    assert payload['totalMatches'] > 0
    assert elapsed < 3.0, f'search_code took {elapsed:.3f}s, threshold 3.0s'


def test_run_command_within_threshold(perf_project, monkeypatch):
    monkeypatch.setattr('services.terminal_utils.validate_terminal_path', _noop_validate_terminal_path)
    executor = ToolExecutor(ToolRegistry.get_instance(), project_bases=[str(perf_project)])

    start = time.monotonic()
    result = asyncio.run(executor.execute('run_command', {'command': 'echo hello', 'cwd': str(perf_project)}))
    elapsed = time.monotonic() - start

    assert result['success'] is True
    assert 'hello' in result['content']
    assert elapsed < 1.0, f'run_command took {elapsed:.3f}s, threshold 1.0s'


def test_agent_single_loop_within_threshold(perf_project, tmp_path, monkeypatch):
    """单轮智能体循环（1 次工具调用）应在 5 秒内完成。"""
    from services.conversation_store import ConversationStore
    import server_quart

    monkeypatch.setattr(agent_module, 'PROVIDERS_FILE', str(tmp_path / 'providers.json'))

    (tmp_path / 'providers.json').write_text(json.dumps({
        'providers': [{
            'id': 'perf-provider',
            'apiBase': 'http://localhost:9999',
            'apiKey': 'x',
            'models': [{'id': 'perf-model'}],
        }]
    }), encoding='utf-8')

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    store = ConversationStore(str(tmp_path / 'test.db'))

    async def _init():
        await store.ensure_tables()
        await store.create({
            'id': 'conv-perf',
            'providerId': 'perf-provider',
            'modelId': 'perf-model',
            'agentConfig': {'enabled': True, 'maxIterations': 5},
            'createdAt': '2024-01-01T00:00:00+00:00',
            'updatedAt': '2024-01-01T00:00:00+00:00',
        })
        await store.append_message('conv-perf', {
            'id': 'u1', 'role': 'user', 'content': 'read large.txt', 'timestamp': 1,
        })

    loop.run_until_complete(_init())
    loop.close()

    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    service = AgentService(
        ToolRegistry.get_instance(),
        project_path=str(perf_project),
        limit_path=str(perf_project),
        stop_event=asyncio.Event(),
    )

    file_path = str(perf_project / 'large.txt')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'delta', 'delta': 'Reading the file.'}
        yield {
            'type': 'tool_call_part',
            'tool_call': {
                'requestId': 'call_perf',
                'name': 'read_file',
                'arguments': {'path': file_path},
            },
        }

    service._stream_llm = mock_stream_llm

    async def run():
        events = []
        async for event in service.process_message('conv-perf', 'read large.txt'):
            events.append(event)
        return events

    start = time.monotonic()
    events = loop.run_until_complete(run())
    elapsed = time.monotonic() - start
    loop.close()

    assert elapsed < 5.0, f'agent single loop took {elapsed:.3f}s, threshold 5.0s'

    types = [json.loads(ev[6:]).get('type') for ev in events]
    assert 'done' in types
