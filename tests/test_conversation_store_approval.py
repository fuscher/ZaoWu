"""ConversationStore 阶段三 tool_approval_rules 表 CRUD 测试。"""
import pytest

pytestmark = pytest.mark.anyio

from services.conversation_store import ConversationStore


@pytest.fixture
async def store(tmp_path):
    s = ConversationStore(str(tmp_path / 'test.db'))
    await s.ensure_tables()
    await s.create({
        'id': 'conv-1',
        'title': 'T',
        'providerId': 'p',
        'modelId': 'm',
        'systemPrompt': '',
        'createdAt': '2026-01-01T00:00:00+00:00',
        'updatedAt': '2026-01-01T00:00:00+00:00',
        'agentConfig': {'enabled': True},
    })
    return s


async def test_new_db_has_tool_approval_rules_table(store):
    async with store._connect() as db:
        cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_approval_rules'")
        row = await cur.fetchone()
    assert row is not None


async def test_list_approval_rules_empty(store):
    """无规则时返回空列表。"""
    rules = await store.list_approval_rules('conv-1')
    assert rules == []


async def test_add_and_list_session_rule(store):
    """会话级规则落库后能按 conv_id 查回。"""
    rid = await store.add_approval_rule('conv-1', 'run_command', 'command:git status', 'allow')
    assert rid > 0
    rules = await store.list_approval_rules('conv-1')
    assert len(rules) == 1
    r = rules[0]
    assert r['action'] == 'run_command'
    assert r['resource'] == 'command:git status'
    assert r['effect'] == 'allow'
    assert r['conversationId'] == 'conv-1'
    assert r['createdAt']


async def test_list_rules_includes_global(store):
    """全局规则（conv_id=None）对所有会话生效。"""
    await store.add_approval_rule(None, 'write_file', 'file:*', 'allow')  # 全局
    await store.add_approval_rule('conv-1', 'run_command', 'command:ls', 'allow')  # 会话级
    rules = await store.list_approval_rules('conv-1')
    # 全局 + 会话级都返回
    assert len(rules) == 2
    actions = {r['action'] for r in rules}
    assert actions == {'write_file', 'run_command'}


async def test_list_rules_isolated_per_conversation(store):
    """会话 A 的规则不泄漏到会话 B（N2-M3 核心验收）。"""
    await store.add_approval_rule('conv-1', 'write_file', 'file:*', 'allow')
    await store.create({
        'id': 'conv-2', 'title': 'T2', 'providerId': 'p', 'modelId': 'm',
        'systemPrompt': '', 'createdAt': '2026-01-01T00:00:00+00:00',
        'updatedAt': '2026-01-01T00:00:00+00:00', 'agentConfig': {'enabled': True},
    })
    rules_a = await store.list_approval_rules('conv-1')
    rules_b = await store.list_approval_rules('conv-2')
    assert len(rules_a) == 1
    assert rules_b == []  # conv-2 看不到 conv-1 的规则（除非全局）


async def test_list_rules_ordered_by_id_for_findlast(store):
    """规则按 id 升序返回，findLast 后声明优先：后插入的 id 更大、优先级更高。"""
    await store.add_approval_rule('conv-1', 'write_file', 'file:*', 'ask')      # id=1
    await store.add_approval_rule('conv-1', 'write_file', 'file:*', 'allow')    # id=2
    await store.add_approval_rule('conv-1', 'write_file', 'file:*', 'deny')     # id=3
    rules = await store.list_approval_rules('conv-1')
    effects = [r['effect'] for r in rules]
    assert effects == ['ask', 'allow', 'deny']
    ids = [r['id'] for r in rules]
    assert ids == sorted(ids)


async def test_delete_session_rules_keeps_global(store):
    """清除会话级规则不动全局规则。"""
    await store.add_approval_rule(None, 'write_file', 'file:*', 'allow')  # 全局
    await store.add_approval_rule('conv-1', 'run_command', 'command:ls', 'allow')  # 会话级
    deleted = await store.delete_approval_rules('conv-1')
    assert deleted == 1
    rules = await store.list_approval_rules('conv-1')
    # 会话级被删，全局保留
    assert len(rules) == 1
    assert rules[0]['conversationId'] is None


async def test_add_global_rule_with_null_conv_id(store):
    """conv_id=None 表示全局规则。"""
    rid = await store.add_approval_rule(None, 'edit_file', 'file:*', 'deny')
    assert rid > 0
    rules = await store.list_approval_rules('conv-1')
    assert len(rules) == 1
    assert rules[0]['conversationId'] is None
