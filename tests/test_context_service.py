"""ContextService 单元测试（5.1 源化缓存 + 5.2 压缩）。"""
import asyncio
import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.anyio

from services.context_service import (
    ContextService, estimate_tokens, estimate_message_tokens, PRUNE_MINIMUM,
)
from services.skill_registry import SkillDefinition, SkillRegistry


# ── estimate_tokens（M3 修复）─────────────────────────────────


def test_estimate_tokens_ascii_divided_by_four():
    assert estimate_tokens('abcdefgh') == 2  # 8 ASCII / 4


def test_estimate_tokens_cjk_one_per_char():
    """M3 核心：中文必须 ≈1 token/字符，而非 //4 低估 3~4 倍。"""
    text = '中' * 30000
    assert estimate_tokens(text) == 30000
    # 旧实现 len//4 会得到 7500，导致压缩永不触发
    assert estimate_tokens(text) != 7500


def test_estimate_tokens_mixed():
    # 3 CJK + 8 ASCII = 3 + 2 = 5
    assert estimate_tokens('你好世界abcdefgh') == 4 + 2


def test_estimate_tokens_empty():
    assert estimate_tokens('') == 0
    assert estimate_tokens(None) == 0


# ── estimate_message_tokens（tool_calls 计入预算）─────────────────


def test_estimate_message_tokens_counts_tool_calls_arguments():
    """工具轮 assistant 消息 content=None：arguments JSON 必须计入估算。

    OpenAI 存储格式：tool_calls[].function.arguments 为 JSON 字符串。
    不统计会让工具密集长对话被系统性低估，压缩触发过晚。
    """
    msg = {
        'role': 'assistant',
        'content': None,
        'tool_calls': [
            {
                'id': 'call_1', 'type': 'function',
                'function': {
                    'name': 'run_command',
                    'arguments': '{"command":"python build.py --all --verbose","cwd":"/a/b"}',
                },
            },
        ],
    }
    # content=None 不贡献；name + arguments 均应计入
    assert estimate_message_tokens(msg) > 0
    assert estimate_message_tokens(msg) > estimate_tokens('run_command')


def test_estimate_message_tokens_plain_message():
    """纯 content 消息与旧 estimate_tokens 等价。"""
    msg = {'role': 'user', 'content': '你好世界abcdefgh'}
    assert estimate_message_tokens(msg) == estimate_tokens('你好世界abcdefgh')


def test_estimate_message_tokens_memory_dict_arguments():
    """内存 dict 形态的 arguments（未序列化）不崩溃、可计数。"""
    msg = {
        'role': 'assistant',
        'content': None,
        'tool_calls': [
            {'id': 'c1', 'function': {'name': 'read_file', 'arguments': {'path': '/x/y'}}},
        ],
    }
    assert estimate_message_tokens(msg) > 0


def test_estimate_message_tokens_empty_message():
    assert estimate_message_tokens({}) == 0
    assert estimate_message_tokens({'role': 'assistant', 'content': None}) == 0


# ── FakeAgent 辅助 ──────────────────────────────────────────


class FakeAgent:
    AGENT_SYSTEM_PROMPT = (
        'BASE PROMPT\n## 当前项目\n- 路径:\n<<PROJECT_PATH>>\n'
        '- 结构:\n<<PROJECT_STRUCTURE>>\n- Git: <<GIT_BRANCH>>'
    )

    def __init__(self, skill_registry: SkillRegistry):
        self.skill_registry = skill_registry
        self._model_id = 'test-model'
        self.http_client = None
        self.executor = SimpleNamespace(project_bases=['/proj-a', '/proj-b'])
        self.structure_calls = 0
        self.git_calls = 0

    def _get_enabled_skills(self):
        return sorted(self.skill_registry.list_enabled(), key=lambda s: s.name)

    def _resolve_merged_skill_config(self, conv: dict) -> dict:
        return {}

    def _get_project_structure(self) -> str:
        self.structure_calls += 1
        return '[dir] src\n[file] main.py'

    def _get_git_branch(self) -> str:
        self.git_calls += 1
        return 'main'


@pytest.fixture
def skill_registry():
    r = SkillRegistry()
    return r


@pytest.fixture
def ctx(skill_registry):
    return ContextService(FakeAgent(skill_registry), FakeAgent.AGENT_SYSTEM_PROMPT)


# ── 5.1 build + 缓存 ────────────────────────────────────────


async def test_build_replaces_placeholders(ctx):
    prompt = await ctx.build({})
    assert '<<PROJECT_PATH>>' not in prompt
    assert '<<PROJECT_STRUCTURE>>' not in prompt
    assert '<<GIT_BRANCH>>' not in prompt
    for p in ctx._agent.executor.project_bases:
        assert p in prompt
    assert 'main' in prompt


async def test_build_ttl_caches_project_values(ctx):
    """TTL 缓存：连续两次 build 只查一次 git branch / structure。"""
    await ctx.build({})
    await ctx.build({})
    assert ctx._agent.git_calls == 1
    assert ctx._agent.structure_calls == 1


async def test_build_version_caches_skills(ctx, skill_registry):
    """技能源按 version 缓存：未变更时 _get_enabled_skills 结果复用。"""
    skill_registry.register(SkillDefinition(
        name='aaa', description='a', system_prompt='技能 A 提示'))
    await ctx.build({})  # 首次渲染，缓存 version
    v_after_first = skill_registry.version

    # 不变更技能 → 复用缓存（通过再次 build 不报错且行为一致验证）
    prompt2 = await ctx.build({})
    assert '技能 A 提示' in prompt2
    assert v_after_first == skill_registry.version

    # 变更技能 → version 自增 → 缓存失效 → 新技能出现
    skill_registry.register(SkillDefinition(
        name='bbb', description='b', system_prompt='技能 B 提示'))
    prompt3 = await ctx.build({})
    assert '技能 B 提示' in prompt3
    assert skill_registry.version > v_after_first


async def test_build_custom_prompt_keeps_user_text(ctx):
    """I4：自定义 prompt 整段作为基座，不套用静态源拆分。"""
    conv = {'agentConfig': {'systemPrompt': '你是自定义助手。路径 <<PROJECT_PATH>>'}}
    prompt = await ctx.build(conv)
    assert '你是自定义助手。' in prompt
    assert 'BASE PROMPT' not in prompt  # 不注入默认静态段
    # N2-I3：自定义 prompt 的占位符仍被替换
    assert '<<PROJECT_PATH>>' not in prompt
    assert '/proj-a' in prompt


async def test_build_no_skill_section_without_enabled_skills(ctx):
    prompt = await ctx.build({})
    assert '## 当前技能' not in prompt


# ── 5.2 _split_window ───────────────────────────────────────


def test_split_window_keeps_recent_above_minimum(ctx):
    msgs = [{'role': 'user', 'content': 'x' * 100, 'seq': i} for i in range(10)]
    # 1000 chars total < PRUNE_MINIMUM(20000) → 无法压缩
    recent, old = ctx._split_window(msgs, PRUNE_MINIMUM)
    assert old == []
    assert recent == msgs


def test_split_window_splits_when_above_minimum(ctx):
    # 每条 10000 字符，3 条 = 30000 > 20000
    msgs = [{'role': 'user', 'content': 'y' * 10000, 'seq': i} for i in range(3)]
    recent, old = ctx._split_window(msgs, PRUNE_MINIMUM)
    assert len(old) >= 1
    assert len(recent) >= 2  # 至少保留 2 条
    # recent 是末尾连续段
    assert recent[-1]['seq'] == 2


def test_split_window_preserves_tool_call_pairing(ctx):
    """近期不以 tool 开头：若 split 切在 tool_call/tool 之间，回拉 assistant。"""
    msgs = [
        {'role': 'user', 'content': 'q' * 15000, 'seq': 0},
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1'}], 'seq': 1},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': 'r' * 8000, 'seq': 2},
    ]
    recent, old = ctx._split_window(msgs, PRUNE_MINIMUM)
    # recent 不应以 tool 开头（需带上 assistant tool_calls）
    if recent:
        assert recent[0]['role'] != 'tool'


# ── 5.2 compact_if_needed ───────────────────────────────────


async def test_compact_returns_none_when_under_budget(ctx):
    conv = {
        'id': 'c1',
        'messages': [{'role': 'user', 'content': '短消息', 'seq': 0}],
        'compactionSummary': None,
        'compactedUntilSeq': -1,
    }
    new_msgs, summary = await ctx.compact_if_needed(conv, 'sys', 4096, {'apiBase': 'x'})
    assert new_msgs is None
    assert summary is None


async def test_compact_counts_ref_tokens_into_budget(ctx, monkeypatch, tmp_path):
    """S14-P0-2: @ 引用 token 计入压缩预算 — 仅凭 ref_tokens 即可触发压缩。"""
    from services.conversation_store import ConversationStore
    import server_quart

    store = ConversationStore(str(tmp_path / 'test.db'))
    await store.ensure_tables()
    await store.create({
        'id': 'c1', 'title': 't', 'providerId': 'p', 'modelId': 'm',
        'systemPrompt': '', 'createdAt': '', 'updatedAt': '',
        'agentConfig': {},
    })
    # 历史 3 条 ASCII 长消息（字符数跨过 PRUNE_MINIMUM=20000，token≈6250）：
    # 预算 8000 → 0.8*8000=6400；不带 ref_tokens 6250≤6400 不压缩，
    # 带 ref_tokens=300 → 6550>6400 触发压缩（引用内容参与压缩决策）。
    for i, chars in enumerate((1000, 12000, 12000)):
        await store.append_message('c1', {
            'id': f'm{i}', 'role': 'user', 'content': 'a' * chars,
            'timestamp': i,
        })
    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    async def fake_llm_stream(**kwargs):
        yield {'type': 'delta', 'delta': '摘要'}
    import agent_modules.agent_core.llm_stream as ls_mod
    monkeypatch.setattr(ls_mod, 'llm_stream', fake_llm_stream)

    conv = await store.get('c1')

    # 不带 ref_tokens：预算充足 → 不压缩
    new_msgs, _ = await ctx.compact_if_needed(conv, 'sys prompt', 8000, {'apiBase': 'x'})
    assert new_msgs is None

    # 带 ref_tokens=300：计入后超预算 → 触发压缩
    new_msgs2, summary = await ctx.compact_if_needed(
        conv, 'sys prompt', 8000, {'apiBase': 'x'}, ref_tokens=300,
    )
    assert new_msgs2 is not None
    assert summary == '摘要'


async def test_compact_triggers_when_over_budget(ctx, monkeypatch, tmp_path):
    """超预算 → 压缩：mock llm_stream 返回摘要，验证持久化与返回结构。"""
    from services.conversation_store import ConversationStore
    import services.context_service as cs_mod

    store = ConversationStore(str(tmp_path / 'test.db'))
    await store.ensure_tables()
    await store.create({
        'id': 'c1', 'title': 't', 'providerId': 'p', 'modelId': 'm',
        'systemPrompt': '', 'createdAt': '', 'updatedAt': '',
        'agentConfig': {},
    })
    # 注入大量历史（中文，每条 4000 字符=4000 token，总量远超 max_tokens*0.8 且远超 PRUNE_MINIMUM）
    for i in range(20):
        await store.append_message('c1', {
            'id': f'm{i}', 'role': 'user', 'content': '历史' * 2000,
            'timestamp': i,
        })
    conv = await store.get('c1')
    assert conv['compactedUntilSeq'] == -1

    # mock llm_stream 返回固定摘要
    async def fake_llm_stream(**kwargs):
        yield {'type': 'delta', 'delta': '这是压缩摘要'}
        yield {'type': 'usage', 'tokens_in': 10, 'tokens_out': 5}
    monkeypatch.setattr('agent_modules.agent_core.llm_stream.llm_stream', fake_llm_stream)
    # ContextService 内部 import llm_stream，需 patch 其引用
    import agent_modules.agent_core.llm_stream as ls_mod
    monkeypatch.setattr(ls_mod, 'llm_stream', fake_llm_stream)

    # get_conversation_store 返回内存 store
    import server_quart
    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    new_msgs, summary = await ctx.compact_if_needed(conv, 'sys prompt', 1000, {'apiBase': 'x'})

    assert summary == '这是压缩摘要'
    assert new_msgs is not None
    # 结构：[system, 摘要 system, *recent]
    assert new_msgs[0]['role'] == 'system'
    assert new_msgs[0]['content'] == 'sys prompt'
    assert '历史摘要' in new_msgs[1]['content']
    assert '这是压缩摘要' in new_msgs[1]['content']

    # 持久化：compactionSummary 有值，compactedUntilSeq 推进
    fresh = await store.get('c1')
    assert fresh['compactionSummary'] == '这是压缩摘要'
    assert fresh['compactedUntilSeq'] >= 0

    # 审计标记（role=system, name=compaction）
    audit = [m for m in fresh['messages'] if m.get('name') == 'compaction']
    assert len(audit) == 1


async def test_compact_skips_already_compacted_messages(ctx, monkeypatch, tmp_path):
    """已压缩的早期消息（seq <= compactedUntilSeq）不参与再次估算/压缩。"""
    from services.conversation_store import ConversationStore
    store = ConversationStore(str(tmp_path / 'test.db'))
    await store.ensure_tables()
    await store.create({
        'id': 'c2', 'title': 't', 'providerId': 'p', 'modelId': 'm',
        'systemPrompt': '', 'createdAt': '', 'updatedAt': '',
        'agentConfig': {},
    })
    for i in range(10):
        await store.append_message('c2', {
            'id': f'm{i}', 'role': 'user', 'content': '历史' * 500,
            'timestamp': i,
        })
    # 标记前 8 条已压缩
    await store.update('c2', {'compactionSummary': '旧摘要', 'compactedUntilSeq': 7})
    conv = await store.get('c2')

    import server_quart
    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    # 剩余未压缩消息少（seq 8,9）→ 不应触发压缩
    new_msgs, summary = await ctx.compact_if_needed(conv, 'sys', 100000, {'apiBase': 'x'})
    assert new_msgs is None
    assert summary is None


async def test_compact_summarization_failure_falls_back(ctx, monkeypatch, tmp_path):
    """_summarize 失败时降级为截断提示，不抛异常、不阻塞主流程。"""
    from services.conversation_store import ConversationStore
    store = ConversationStore(str(tmp_path / 'test.db'))
    await store.ensure_tables()
    await store.create({
        'id': 'c3', 'title': 't', 'providerId': 'p', 'modelId': 'm',
        'systemPrompt': '', 'createdAt': '', 'updatedAt': '',
        'agentConfig': {},
    })
    for i in range(20):
        await store.append_message('c3', {
            'id': f'm{i}', 'role': 'user', 'content': '历史' * 2000,
            'timestamp': i,
        })
    conv = await store.get('c3')

    # llm_stream 抛异常
    async def boom_stream(**kwargs):
        raise RuntimeError('summary LLM down')
        yield  # noqa: never reached
    import agent_modules.agent_core.llm_stream as ls_mod
    monkeypatch.setattr(ls_mod, 'llm_stream', boom_stream)
    import server_quart
    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    new_msgs, summary = await ctx.compact_if_needed(conv, 'sys', 1000, {'apiBase': 'x'})
    # 降级：仍有摘要（截断提示），仍持久化 compactedUntilSeq
    assert summary is not None
    assert new_msgs is not None
    assert '截断' in summary
